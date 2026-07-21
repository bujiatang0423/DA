from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.bootstrap.application import _MemoryRuns, create_app
from backend.app.bootstrap.application import build_application
from backend.app.bootstrap.backtest_worker import build_backtest_job_handler
from backend.app.bootstrap.settings import Settings
from backend.app.contracts.runs import RunStatus
from backend.app.contracts.runs import RunKind
from backend.app.features.backtests.module import build_backtests_feature
from backend.app.features.backtests.models import BacktestRequest
from backend.app.features.candidates.module import build_candidate_feature
from backend.app.features.holdings.module import build_holdings_feature
from backend.app.features.runs.module import build_runs_feature
from backend.app.features.runs.service import RunsService
from backend.app.infrastructure.persistence.models import Base
from backend.app.infrastructure.persistence.strict_pit_rows import TradingCalendarRow
from backend.app.infrastructure.tasks.handlers import HandlerRegistry
from backend.app.infrastructure.tasks.health import WorkerLeaseStore
from backend.app.infrastructure.tasks.worker import build_worker
from backend.tests.features.holdings.fakes import (
    FakeHoldingAnalysisRepository,
    FakePortfolioReader,
)
from backend.tests.features.holdings.factories import portfolio_snapshot


CREATE_CASES = (
    (
        "/api/v1/candidates",
        {"portfolio_id": "default", "as_of_time": "2026-07-20T09:30:00Z"},
        "/api/v1/candidates/{run_id}",
    ),
    (
        "/api/v1/holding-analyses",
        {"portfolio_id": "default", "as_of_time": "2026-07-20T09:30:00Z"},
        "/api/v1/holding-analyses/{run_id}",
    ),
    (
        "/api/v1/backtests",
        {
            "strategy_version": "v2.12",
            "start_date": "2023-01-02",
            "end_date": "2023-01-04",
            "initial_cash": "150000",
            "groups": ["A"],
        },
        "/api/v1/backtests/{run_id}",
    ),
)


@pytest.fixture
def contract_client() -> TestClient:
    runs = _MemoryRuns()
    holding_reader = FakePortfolioReader(
        portfolio_snapshot(datetime(2026, 7, 20, 9, 30, tzinfo=UTC))
    )
    return TestClient(
        create_app(
            (
                build_runs_feature(runs),
                build_candidate_feature(runs.submit),
                build_holdings_feature(
                    holding_reader,
                    submit=runs.submit,
                    result_repository=FakeHoldingAnalysisRepository(),
                ),
                build_backtests_feature(runs.submit),
            )
        )
    )


@pytest.mark.parametrize(("path", "payload", "result_template"), CREATE_CASES)
def test_long_running_submission_contract_is_idempotent_and_queryable(
    contract_client: TestClient,
    path: str,
    payload: dict[str, object],
    result_template: str,
) -> None:
    headers = {"Idempotency-Key": f"contract:{path}"}

    first = contract_client.post(path, json=payload, headers=headers)
    second = contract_client.post(path, json=payload, headers=headers)

    assert first.status_code == 202
    assert second.status_code == 202
    body = first.json()
    assert body["run_id"] == second.json()["run_id"]
    assert body["status"] == "queued"
    assert body["auto_trade_enabled"] is False
    assert body["human_confirm_required"] is True
    assert body["links"]["result"] == result_template.format(run_id=body["run_id"])
    assert first.headers["location"] == body["links"]["self"]

    run = contract_client.get(body["links"]["self"])

    assert run.status_code == 200
    assert run.json()["run_id"] == body["run_id"]
    assert run.json()["status"] == "queued"


@pytest.mark.parametrize(
    "path",
    (*tuple(case[0] for case in CREATE_CASES), "/api/v1/holdings/analysis/submit"),
)
def test_openapi_describes_long_running_submission_envelopes(path: str) -> None:
    operation = build_application().openapi()["paths"][path]["post"]

    accepted = operation["responses"]["202"]
    validation = operation["responses"]["422"]

    assert accepted["headers"]["Location"]["schema"] == {"type": "string"}
    assert accepted["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/RunRef"
    }
    assert validation["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }


def test_retry_contract_requeues_failed_run_with_a_run_location() -> None:
    runs = _MemoryRuns()
    submitted = runs.submit(
        kind="backtest",
        payload={},
        idempotency_key=None,
        submitted_at=datetime(2026, 7, 20, 9, 30, tzinfo=UTC),
    )
    runs._rows[submitted.run_id] = runs._rows[submitted.run_id].model_copy(
        update={"status": RunStatus.FAILED}
    )
    client = TestClient(create_app((build_runs_feature(runs),)))

    response = client.post(f"/api/v1/runs/{submitted.run_id}/retry")

    assert response.status_code == 202
    assert response.headers["location"] == response.json()["links"]["self"]
    assert response.json()["status"] == "queued"


def test_openapi_describes_retry_submission_envelope() -> None:
    operation = build_application().openapi()["paths"]["/api/v1/runs/{run_id}/retry"]["post"]

    accepted = operation["responses"]["202"]

    assert accepted["headers"]["Location"]["schema"] == {"type": "string"}
    assert accepted["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/RunRef"
    }


def test_openapi_describes_generic_run_submission_envelope() -> None:
    operation = build_application().openapi()["paths"]["/api/v1/runs"]["post"]

    accepted = operation["responses"]["202"]
    validation = operation["responses"]["422"]

    assert accepted["headers"]["Location"]["schema"] == {"type": "string"}
    assert accepted["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/RunRef"
    }
    assert validation["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }


@pytest.fixture
def composed_sessions(postgres_engine: Engine) -> sessionmaker[Session]:
    Base.metadata.create_all(postgres_engine)
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE TABLE backtest_rejected_attempts, backtest_trades, "
                "backtest_curve_points, backtest_group_results, backtest_results, "
                "run_artifacts, run_events, runs, worker_leases, trading_calendar, "
                "portfolio_audit_events, portfolio_lot_projections, "
                "portfolio_snapshot_projections, portfolio_snapshot_revisions, "
                "portfolio_versions CASCADE"
            )
        )
    return sessionmaker(bind=postgres_engine, expire_on_commit=False)


@pytest.fixture
def composed_client(
    monkeypatch: pytest.MonkeyPatch,
    postgres_engine: Engine,
    composed_sessions: sessionmaker[Session],
) -> TestClient:
    del composed_sessions
    monkeypatch.setenv(
        "DA_DATABASE_URL",
        postgres_engine.url.render_as_string(hide_password=False),
    )
    monkeypatch.setenv("DA_ENVIRONMENT", "test")
    monkeypatch.setenv("DA_PIT_APPROVAL_SECRET", "test-pit-approval-secret-which-is-long-enough")
    return TestClient(build_application())


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("path", "payload"),
    (
        (
            "/api/v1/candidates",
            {"portfolio_id": "default", "as_of_time": "2026-07-20T09:30:00Z"},
        ),
        (
            "/api/v1/holding-analyses",
            {"portfolio_id": "default", "as_of_time": "2026-07-20T09:30:00Z"},
        ),
        (
            "/api/v1/holdings/analysis/submit",
            {"portfolio_id": "default", "as_of_time": "2026-07-20T09:30:00Z"},
        ),
        (
            "/api/v1/backtests",
            {
                "strategy_version": "v2.12",
                "start_date": "2023-01-02",
                "end_date": "2023-01-04",
                "initial_cash": "150000",
                "groups": ["A"],
            },
        ),
    ),
)
def test_composed_application_returns_a_run_status_location(
    composed_client: TestClient,
    path: str,
    payload: dict[str, object],
) -> None:
    response = composed_client.post(
        path,
        json=payload,
        headers={"Idempotency-Key": f"composed-{uuid4()}"},
    )

    assert response.status_code == 202
    assert response.headers["location"] == response.json()["links"]["self"]


@pytest.mark.postgres
def test_candidate_idempotency_survives_application_rebuild(
    composed_client: TestClient,
) -> None:
    payload = {
        "portfolio_id": "candidate-restart",
        "as_of_time": "2026-07-20T09:30:00Z",
    }
    headers = {"Idempotency-Key": "candidate-restart-key"}

    first = composed_client.post("/api/v1/candidates", json=payload, headers=headers)
    replay = composed_client.post("/api/v1/candidates", json=payload, headers=headers)
    assert first.status_code == replay.status_code == 202
    assert first.json()["run_id"] == replay.json()["run_id"]

    rebuilt_client = TestClient(build_application())
    after_rebuild = rebuilt_client.post("/api/v1/candidates", json=payload, headers=headers)

    assert after_rebuild.status_code == 202
    assert after_rebuild.json()["run_id"] == first.json()["run_id"]


@pytest.mark.postgres
def test_composed_application_maps_a_real_portfolio_version_conflict_to_409(
    composed_client: TestClient,
) -> None:
    payload = {
        "portfolio_id": "composition-contract",
        "as_of_time": "2026-07-20T09:30:00Z",
        "cash": "100000",
        "equity": "100000",
        "positions": [],
        "expected_version": 0,
        "reason": "create a composition contract fixture",
    }

    first = composed_client.put("/api/v1/holdings/maintenance", json=payload)
    second = composed_client.put("/api/v1/holdings/maintenance", json=payload)

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["code"] == "PORTFOLIO_VERSION_CONFLICT"
    assert second.json()["request_id"] == second.headers["x-request-id"]


@pytest.mark.postgres
def test_composed_application_exposes_the_safe_strict_pit_failure(
    composed_client: TestClient,
    composed_sessions: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    request = BacktestRequest(
        strategy_version="v2.12",
        start_date=datetime(2020, 6, 1, tzinfo=UTC).date(),
        end_date=datetime(2020, 6, 2, tzinfo=UTC).date(),
        initial_cash=Decimal("10000"),
        groups=("A",),
    )
    with composed_sessions() as session:
        session.add_all(
            (
                TradingCalendarRow(
                    id="composed-calendar-1",
                    source_record_id="composed-calendar-1",
                    exchange="SSE",
                    trade_date=request.start_date,
                    is_open=True,
                    available_at=datetime(2020, 5, 30, tzinfo=UTC),
                    source_artifact_hash="a" * 64,
                ),
                TradingCalendarRow(
                    id="composed-calendar-2",
                    source_record_id="composed-calendar-2",
                    exchange="SSE",
                    trade_date=request.end_date,
                    is_open=True,
                    available_at=datetime(2020, 5, 30, tzinfo=UTC),
                    source_artifact_hash="a" * 64,
                ),
            )
        )
        session.commit()
    runs = RunsService(composed_sessions)
    run = runs.submit(
        RunKind.BACKTEST,
        request.model_dump(mode="json"),
        f"strict-pit-{uuid4()}",
        datetime(2026, 7, 20, 9, 30, tzinfo=UTC),
    )
    settings = Settings(
        environment="test",
        provider_mode="production",
        artifact_root=tmp_path,
        pit_approval_secret="test-pit-approval-secret-which-is-long-enough",
    )
    handlers = HandlerRegistry()
    handlers.register(RunKind.BACKTEST, build_backtest_job_handler(settings, composed_sessions))
    worker = build_worker(
        runs,
        handlers,
        lambda: datetime(2026, 7, 20, 9, 30, tzinfo=UTC),
        WorkerLeaseStore(composed_sessions),
        "composed-contract-worker",
    )

    assert worker.run_once() is True
    response = composed_client.get(run.links.self)

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error_code"] == "BACKTEST_SNAPSHOT_QUALITY_ERROR"
    assert response.json()["error_message"] == "回测所需点时数据未通过验证。"
