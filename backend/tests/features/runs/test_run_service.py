from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from backend.app.contracts.runs import RunKind, RunStatus
from backend.app.features.runs.service import RunsService
from backend.app.infrastructure.persistence.models import RunRow


@pytest.mark.parametrize(
    ("kind", "result_path"),
    (
        (RunKind.CANDIDATE_RECOMMENDATION, "/api/v1/candidates/{run_id}"),
        (RunKind.HOLDING_ANALYSIS, "/api/v1/holding-analyses/{run_id}"),
        (RunKind.BACKTEST, None),
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
