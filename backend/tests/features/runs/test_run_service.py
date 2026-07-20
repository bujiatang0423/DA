from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from backend.app.bootstrap.application import create_app
from backend.app.features.runs.module import build_runs_feature
from backend.app.contracts.runs import RunKind, RunStatus
from backend.app.features.runs.service import RunsService
from backend.app.infrastructure.persistence.models import RunRow


@pytest.mark.parametrize(
    ("kind", "result_path"),
    (
        (RunKind.CANDIDATE_RECOMMENDATION, "/api/v1/candidates/{run_id}"),
        (RunKind.HOLDING_ANALYSIS, "/api/v1/holding-analyses/{run_id}"),
        (RunKind.BACKTEST, "/api/v1/backtests/{run_id}"),
        (RunKind.LEGACY_IMPORT, None),
    ),
)
def test_run_reference_exposes_only_available_business_result_links(
    kind: RunKind,
    result_path: str | None,
) -> None:
    run_id = uuid4()
    row = RunRow(
        id=run_id,
        kind=kind.value,
        status=RunStatus.SUCCEEDED.value,
        request_payload={},
        submitted_at=datetime.now(UTC),
        progress=100,
        retry_count=0,
    )

    reference = RunsService._ref(row)

    assert reference.links.artifacts == f"/api/v1/runs/{run_id}/artifacts"
    expected = result_path.format(run_id=run_id) if result_path is not None else None
    assert reference.links.result == expected


def test_run_detail_projects_observable_status_without_raw_failure_text(
    postgres_engine: Engine,
) -> None:
    run_id = uuid4()
    submitted_at = datetime(2026, 7, 19, 9, 30, tzinfo=UTC)
    heartbeat_at = datetime(2026, 7, 19, 9, 35, tzinfo=UTC)
    with postgres_engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE run_events, runs CASCADE"))
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)

    with factory.begin() as session:
        session.add(
            RunRow(
                id=run_id,
                kind=RunKind.BACKTEST.value,
                status=RunStatus.FAILED.value,
                request_payload={},
                submitted_at=submitted_at,
                stage="loading_market_data",
                progress=40,
                heartbeat_at=heartbeat_at,
                retry_count=2,
                error_code="PROVIDER_UNAVAILABLE",
                error_message="upstream diagnostic: connection reset",
            )
        )

    detail = RunsService(factory).get(run_id)

    assert detail.stage == "loading_market_data"
    assert detail.progress == 40
    assert detail.heartbeat_at == heartbeat_at
    assert detail.retry_count == 2
    assert detail.error_code == "PROVIDER_UNAVAILABLE"
    assert "connection reset" not in detail.model_dump_json()


@pytest.mark.postgres
def test_retrying_a_failed_run_preserves_its_idempotency_identity(
    postgres_engine: Engine,
) -> None:
    submitted_at = datetime(2026, 7, 20, 9, 30, tzinfo=UTC)
    retried_at = datetime(2026, 7, 20, 9, 35, tzinfo=UTC)
    with postgres_engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE run_events, runs CASCADE"))
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    service = RunsService(factory)
    submitted = service.submit(RunKind.BACKTEST, {"account": "private"}, "retry-key", submitted_at)
    claimed = service.claim_next(submitted_at, "worker-a", "token-a")
    assert claimed is not None
    service.transition(
        claimed.id,
        RunStatus.FAILED,
        submitted_at,
        "worker-a",
        "token-a",
        "PROVIDER_UNAVAILABLE",
    )

    client = TestClient(create_app((build_runs_feature(service),)))
    response = client.post(f"/api/v1/runs/{submitted.run_id}/retry")

    assert response.status_code == 202
    assert response.headers["location"] == f"/api/v1/runs/{submitted.run_id}"
    assert response.json()["run_id"] == submitted.run_id
    assert response.json()["status"] == RunStatus.QUEUED.value
    assert service.get(submitted.run_id).retry_count == 1
    with factory() as session:
        row = session.get(RunRow, UUID(submitted.run_id))
        assert row is not None
        assert row.idempotency_key == "retry-key"
        assert row.error_code is None
        assert row.claim_owner is None
        assert row.claim_token is None
        assert (
            session.execute(
                text(
                    "SELECT event_type FROM run_events WHERE run_id = :id ORDER BY id DESC LIMIT 1"
                ),
                {"id": row.id},
            ).scalar_one()
            == "retry_requested"
        )
    reclaimed = service.claim_next(retried_at, "worker-b", "token-b")
    assert reclaimed is not None
    assert reclaimed.id == UUID(submitted.run_id)


@pytest.mark.parametrize("status", (RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.SUCCEEDED))
@pytest.mark.postgres
def test_retry_endpoint_rejects_non_failed_runs_with_a_safe_stable_error(
    postgres_engine: Engine,
    status: RunStatus,
) -> None:
    now = datetime(2026, 7, 20, 9, 30, tzinfo=UTC)
    with postgres_engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE run_events, runs CASCADE"))
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    service = RunsService(factory)
    queued = service.submit(RunKind.BACKTEST, {"email": "person@example.test"}, None, now)
    with factory.begin() as session:
        row = session.get(RunRow, UUID(queued.run_id))
        assert row is not None
        row.status = status.value
    client = TestClient(create_app((build_runs_feature(service),)))

    response = client.post(f"/api/v1/runs/{queued.run_id}/retry")

    assert response.status_code == 409
    assert response.json() == {
        "code": "RUN_RETRY_NOT_ALLOWED",
        "message": "only failed runs can be retried",
        "request_id": response.headers["x-request-id"],
        "details": {},
    }
