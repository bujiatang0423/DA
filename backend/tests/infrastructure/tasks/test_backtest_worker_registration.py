from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.bootstrap.backtest_worker import (
    BacktestWorkerConfigurationError,
    build_backtest_job_handler,
)
from backend.app.bootstrap.settings import Settings
from backend.app.contracts.runs import RunKind, RunStatus
from backend.app.features.runs.service import RunsService
from backend.app.infrastructure.persistence.models import Base, RunRow
from backend.app.infrastructure.tasks.handlers import HandlerRegistry
from backend.app.infrastructure.tasks.health import WorkerLeaseStore
from backend.app.infrastructure.tasks.worker import build_worker
from backend.app.worker_main import register_worker_handlers


NOW = datetime(2026, 7, 20, 9, 30, tzinfo=UTC)


@pytest.fixture
def worker_sessions(postgres_engine: Engine) -> sessionmaker[Session]:
    Base.metadata.create_all(postgres_engine)
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE TABLE backtest_rejected_attempts, backtest_trades, "
                "backtest_curve_points, backtest_group_results, backtest_results, "
                "run_artifacts, run_events, runs, worker_leases CASCADE"
            )
        )
    return sessionmaker(bind=postgres_engine, expire_on_commit=False)


def test_backtest_worker_composition_requires_a_pit_approval_secret(
    worker_sessions: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        provider_mode="fake",
        artifact_root=tmp_path,
    )

    with pytest.raises(BacktestWorkerConfigurationError, match="PIT approval secret"):
        build_backtest_job_handler(settings, worker_sessions)


def test_worker_registry_includes_backtest_only_after_strict_composition_is_constructible(
    worker_sessions: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        provider_mode="fake",
        artifact_root=tmp_path,
        pit_approval_secret="test-pit-approval-secret-which-is-long-enough",
    )
    handlers = HandlerRegistry()

    register_worker_handlers(
        settings,
        worker_sessions,
        SimpleNamespace(candidate_service=object(), holding_service=object()),
        handlers,
    )

    assert handlers.resolve(RunKind.BACKTEST) is not None


def test_worker_registry_omits_backtest_when_the_pit_secret_is_missing(
    worker_sessions: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    settings = Settings(environment="test", provider_mode="fake", artifact_root=tmp_path)
    handlers = HandlerRegistry()

    register_worker_handlers(
        settings,
        worker_sessions,
        SimpleNamespace(candidate_service=object(), holding_service=object()),
        handlers,
    )

    with pytest.raises(LookupError, match="backtest"):
        handlers.resolve(RunKind.BACKTEST)


@pytest.mark.postgres
def test_real_backtest_worker_fails_closed_without_an_approved_pit_certificate(
    worker_sessions: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        provider_mode="fake",
        artifact_root=tmp_path,
        pit_approval_secret="test-pit-approval-secret-which-is-long-enough",
    )
    runs = RunsService(worker_sessions)
    run = runs.submit(
        RunKind.BACKTEST,
        {
            "strategy_version": "v2.12",
            "start_date": "2020-06-01",
            "end_date": "2020-06-02",
            "initial_cash": str(Decimal("10000")),
            "groups": ["A"],
        },
        "strict-backtest-without-certificate",
        NOW,
    )
    handlers = HandlerRegistry()
    handlers.register(RunKind.BACKTEST, build_backtest_job_handler(settings, worker_sessions))
    worker = build_worker(
        runs,
        handlers,
        lambda: NOW,
        WorkerLeaseStore(worker_sessions),
        "backtest-worker",
    )

    assert worker.run_once() is True
    with worker_sessions() as session:
        row = session.get(RunRow, run.run_id)
        assert row is not None
        assert row.status == RunStatus.FAILED.value
        assert row.error_code == "JOB_EXECUTION_FAILED"
        assert session.execute(text("SELECT count(*) FROM backtest_results")).scalar_one() == 0
