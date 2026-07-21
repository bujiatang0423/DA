from __future__ import annotations

from datetime import UTC, datetime, time
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.market.pit_models import DataKind, SnapshotScope


def test_strict_backtest_scope_only_requests_certifiable_persisted_inputs() -> None:
    scope = SnapshotScope.backtest((), history_start=datetime(2020, 1, 1, tzinfo=UTC))

    assert DataKind.LLM_FACTOR not in scope.required_kinds
    assert DataKind.REALTIME_QUOTE not in scope.required_kinds
    assert {
        DataKind.SECURITY_MASTER,
        DataKind.SECURITY_STATUS,
        DataKind.TRADING_CALENDAR,
        DataKind.DAILY_BAR_RAW,
        DataKind.INDEX_DAILY_BAR,
        DataKind.FEE_SCHEDULE,
    }.issubset(scope.required_kinds)


def test_local_e2e_harness_requires_an_explicit_test_only_switch() -> None:
    from backend.app.bootstrap.e2e import E2EConfigurationError, require_local_e2e_mode

    with pytest.raises(E2EConfigurationError, match="DA_E2E_LOCAL"):
        require_local_e2e_mode({})

    require_local_e2e_mode({"DA_E2E_LOCAL": "1", "DA_ENVIRONMENT": "test"})


def test_local_e2e_harness_rejects_non_test_environment() -> None:
    from backend.app.bootstrap.e2e import E2EConfigurationError, require_local_e2e_mode

    with pytest.raises(E2EConfigurationError, match="test environment"):
        require_local_e2e_mode({"DA_E2E_LOCAL": "1", "DA_ENVIRONMENT": "production"})


def test_frozen_e2e_warehouse_never_reads_a_provider() -> None:
    from backend.app.bootstrap.e2e import FrozenE2EWarehouse

    as_of_time = datetime(2020, 1, 2, 7, 30, tzinfo=UTC)
    snapshot = FrozenE2EWarehouse().snapshot(
        as_of_time=as_of_time,
        scope=SnapshotScope.candidate_recommendation(),
    )

    assert snapshot.as_of_time == as_of_time
    assert snapshot.quality.has_errors is False
    assert snapshot.market_inputs[0].kind is DataKind.MARKET_BREADTH
    assert snapshot.market_inputs[0].source_artifact_hash == "e" * 64


def test_frozen_e2e_warehouse_contains_candidate_evidence_inputs() -> None:
    from backend.app.bootstrap.e2e import FrozenE2EWarehouse

    as_of_time = datetime(2020, 1, 2, 7, 30, tzinfo=UTC)
    snapshot = FrozenE2EWarehouse().snapshot(
        as_of_time=as_of_time,
        scope=SnapshotScope.candidate_recommendation(),
    )

    kinds = {record.kind for observation in snapshot.security_observations for record in observation.records}
    kinds.update(record.kind for record in snapshot.market_inputs)
    assert {
        DataKind.SECURITY_MASTER,
        DataKind.DAILY_BAR_RAW,
        DataKind.FINANCIAL_FACT,
        DataKind.POLICY_DOCUMENT,
        DataKind.LLM_FACTOR,
    } <= kinds
    assert len(snapshot.security_observations) >= 3
    assert len(snapshot.lineage) >= 3


def test_local_e2e_application_uses_the_frozen_warehouse_only_in_test_mode() -> None:
    from backend.app.bootstrap.e2e import build_local_e2e_application, build_local_e2e_worker
    from backend.app.bootstrap.settings import Settings
    from backend.app.contracts.runs import RunKind

    app = build_local_e2e_application(
        Settings(_env_file=None, environment="test", provider_mode="fake"),
        sessionmaker(),
    )

    assert "/api/v1/candidates" in {route.path for route in app.routes}
    assert "/api/v1/holding-analyses" in {route.path for route in app.routes}
    worker = build_local_e2e_worker(
        Settings(_env_file=None, environment="test", provider_mode="fake"),
        sessionmaker(),
    )
    assert worker.handlers.resolve(RunKind.CANDIDATE_RECOMMENDATION) is not None
    assert worker.handlers.resolve(RunKind.HOLDING_ANALYSIS) is not None


@pytest.mark.postgres
def test_local_e2e_bootstrap_certifies_execution_scope(
    postgres_engine: Engine,
) -> None:
    from backend.app.bootstrap.e2e import (
        E2E_BACKTEST_START,
        _STRICT_E2E_TABLES,
        bootstrap_local_e2e_strict_pit,
    )
    from backend.app.bootstrap.settings import Settings
    from backend.app.infrastructure.market.build import build_strict_pit_warehouse
    from backend.app.infrastructure.persistence.models import Base, RunRow
    from backend.app.infrastructure.tasks.db_models import WorkerLeaseRow

    Base.metadata.create_all(postgres_engine)
    sessions = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        environment="test",
        provider_mode="fake",
        pit_approval_secret="local-e2e-pit-approval-secret-0001",
    )
    try:
        stale_run_id = uuid4()
        stale_worker_id = f"stale-e2e-worker-{uuid4()}"
        stale_run = RunRow(
            id=stale_run_id,
            kind="backtest",
            status="failed",
            request_payload={},
            idempotency_key=f"stale-{stale_run_id}",
            submitted_at=E2E_BACKTEST_START,
            progress=0,
            retry_count=0,
        )
        with sessions() as session:
            session.add(stale_run)
            session.add(
                WorkerLeaseRow(
                    worker_id=stale_worker_id,
                    lease_token="stale-e2e-worker-token",
                    heartbeat_at=E2E_BACKTEST_START,
                )
            )
            session.commit()
        bootstrap_local_e2e_strict_pit(settings, sessions)
        with sessions() as session:
            assert session.get(RunRow, stale_run.id) is None
            assert session.get(WorkerLeaseRow, stale_worker_id) is None
            warehouse = build_strict_pit_warehouse(
                session=session,
                approval_secret=settings.pit_approval_secret,
            )
            execution_scope = SnapshotScope(
                ("000001.SZ",),
                (
                    DataKind.DAILY_BAR_RAW,
                    DataKind.SECURITY_STATUS,
                    DataKind.FEE_SCHEDULE,
                ),
            )

            snapshot = warehouse.snapshot(
                as_of_time=datetime.combine(
                    E2E_BACKTEST_START.date(),
                    time(15, 30),
                    E2E_BACKTEST_START.tzinfo,
                ),
                scope=execution_scope,
            )

        assert snapshot.data_grade.value == "pit_verified"
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(text(f"TRUNCATE TABLE {_STRICT_E2E_TABLES} CASCADE"))
            connection.execute(text("TRUNCATE TABLE runs CASCADE"))
