from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.contracts.runs import RunKind, RunStatus
from backend.app.contracts.grades import DataGrade, LlmGrade
from backend.app.features.backtests.jobs import BacktestJobHandler
from backend.app.features.backtests.models import (
    BacktestExperimentResult,
    BacktestGroupResult,
    BacktestRequest,
    StrategyGroup,
)
from backend.app.features.backtests.repository import SqlBacktestRepository
from backend.app.features.backtests.service import BacktestService
from backend.app.features.candidates.jobs import CandidateJobHandler
from backend.app.features.holdings.jobs import HoldingAnalysisJobHandler
from backend.app.features.runs.service import RunsService
from backend.app.features.runs.artifacts import SqlArtifactRepository
from backend.app.infrastructure.persistence.models import Base
from backend.app.infrastructure.tasks.handlers import HandlerRegistry
from backend.app.infrastructure.tasks.health import WorkerLeaseStore
from backend.app.infrastructure.tasks.worker import build_worker


@pytest.fixture
def recovery_sessions(postgres_engine: Engine) -> sessionmaker[Session]:
    Base.metadata.create_all(postgres_engine)
    with postgres_engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE run_events, runs, worker_leases CASCADE"))
    return sessionmaker(bind=postgres_engine, expire_on_commit=False)


@pytest.mark.postgres
def test_restarted_worker_automatically_requeues_and_completes_a_stale_run(
    recovery_sessions: sessionmaker[Session],
) -> None:
    claimed_at = datetime(2026, 7, 20, 9, 30, tzinfo=UTC)
    restarted_at = claimed_at + timedelta(minutes=2)
    runs = RunsService(recovery_sessions)
    submitted = runs.submit(
        RunKind.CANDIDATE_RECOMMENDATION,
        {"portfolio_id": "default", "as_of_time": claimed_at.isoformat()},
        "restart-recovery",
        claimed_at,
    )
    claimed = runs.claim_next(claimed_at, "stopped-worker", "old-token")
    assert claimed is not None

    completed: list[UUID] = []
    handlers = HandlerRegistry()
    handlers.register(
        RunKind.CANDIDATE_RECOMMENDATION,
        lambda context: completed.append(context.run_id),
    )
    worker = build_worker(
        runs,
        handlers,
        lambda: restarted_at,
        WorkerLeaseStore(recovery_sessions),
        "restarted-worker",
        stale_after_seconds=60,
    )

    assert worker.run_once() is True
    assert completed == [UUID(submitted.run_id)]

    recovered = RunsService(recovery_sessions).get(submitted.run_id)
    assert recovered.status is RunStatus.SUCCEEDED
    assert recovered.retry_count == 1


@dataclass
class RecordingCandidateService:
    run_ids: list[str] = field(default_factory=list)

    def run(self, command: object) -> None:
        self.run_ids.append(str(command.run_id))


@dataclass
class RecordingHoldingService:
    run_ids: list[str] = field(default_factory=list)

    def run(self, command: object) -> None:
        self.run_ids.append(str(command.run_id))


class FixedStrictBacktestRunner:
    def run(self, request: BacktestRequest) -> BacktestExperimentResult:
        group = BacktestGroupResult(
            group=StrategyGroup.A,
            data_grade=DataGrade.PIT_VERIFIED,
            llm_grade=LlmGrade.NOT_USED,
            input_manifest_hash="certified-inputs",
            equity_curve=[],
            trades=[],
            metrics={},
        )
        return BacktestExperimentResult(
            request=request,
            input_manifest_hash="certified-experiment",
            groups=(group,),
        )


@pytest.mark.postgres
def test_restarted_run_center_reads_all_completed_job_lifecycles(
    recovery_sessions: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 20, 15, 30, tzinfo=UTC)
    initial_api = RunsService(recovery_sessions)
    candidate = initial_api.submit(
        RunKind.CANDIDATE_RECOMMENDATION,
        {"portfolio_id": "default", "as_of_time": now.isoformat()},
        "candidate-lifecycle",
        now,
    )
    holding = initial_api.submit(
        RunKind.HOLDING_ANALYSIS,
        {"portfolio_id": "default", "as_of_time": now.isoformat()},
        "holding-lifecycle",
        now,
    )
    backtest = initial_api.submit(
        RunKind.BACKTEST,
        {
            "strategy_version": "v2.12",
            "start_date": date(2026, 7, 16).isoformat(),
            "end_date": date(2026, 7, 17).isoformat(),
            "initial_cash": str(Decimal("100000")),
            "groups": ["A"],
        },
        "backtest-lifecycle",
        now,
    )
    candidate_service = RecordingCandidateService()
    holding_service = RecordingHoldingService()
    handlers = HandlerRegistry()
    handlers.register(RunKind.CANDIDATE_RECOMMENDATION, CandidateJobHandler(candidate_service))
    handlers.register(RunKind.HOLDING_ANALYSIS, HoldingAnalysisJobHandler(holding_service))
    handlers.register(
        RunKind.BACKTEST,
        BacktestJobHandler(
            BacktestService(
                FixedStrictBacktestRunner(),
                SqlBacktestRepository(recovery_sessions),
                SqlArtifactRepository(recovery_sessions, tmp_path),
            )
        ),
    )
    worker = build_worker(
        initial_api,
        handlers,
        lambda: now,
        WorkerLeaseStore(recovery_sessions),
        "lifecycle-worker",
        stale_after_seconds=60,
    )

    assert [worker.run_once() for _ in range(3)] == [True, True, True]

    restarted_api = RunsService(recovery_sessions)
    assert [
        restarted_api.get(run_id).status
        for run_id in (candidate.run_id, holding.run_id, backtest.run_id)
    ] == [
        RunStatus.SUCCEEDED,
        RunStatus.SUCCEEDED,
        RunStatus.SUCCEEDED,
    ]
    assert candidate_service.run_ids == [candidate.run_id]
    assert holding_service.run_ids == [holding.run_id]
    assert SqlBacktestRepository(recovery_sessions).fetch_result(UUID(backtest.run_id)) is not None
    assert len(restarted_api.artifacts(backtest.run_id)) == 1
