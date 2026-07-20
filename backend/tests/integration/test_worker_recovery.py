from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Event, Thread
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


class ObservingRuns:
    def __init__(self, delegate: RunsService, expected_time: datetime, refreshed: Event) -> None:
        self._delegate = delegate
        self._expected_time = expected_time
        self._refreshed = refreshed
        self.updates: list[bool] = []

    def claim_next(self, now: datetime, worker_id: str, lease_token: str) -> object | None:
        return self._delegate.claim_next(now, worker_id, lease_token)

    def heartbeat(
        self,
        run_id: object,
        stage: str,
        progress: int,
        now: datetime,
        worker_id: str,
        lease_token: str,
    ) -> bool:
        updated = self._delegate.heartbeat(
            UUID(str(run_id)), stage, progress, now, worker_id, lease_token
        )
        if now == self._expected_time:
            self.updates.append(updated)
            self._refreshed.set()
        return updated

    def transition(
        self,
        run_id: object,
        target: RunStatus,
        now: datetime,
        worker_id: str,
        lease_token: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> object | None:
        return self._delegate.transition(
            UUID(str(run_id)),
            target,
            now,
            worker_id,
            lease_token,
            error_code,
            error_message,
        )

    def requeue_stale(self, cutoff: datetime, now: datetime) -> tuple[object, ...]:
        return self._delegate.requeue_stale(cutoff, now)


class ObservingLeaseStore:
    def __init__(
        self, delegate: WorkerLeaseStore, expected_time: datetime, refreshed: Event
    ) -> None:
        self._delegate = delegate
        self._expected_time = expected_time
        self._refreshed = refreshed

    def acquire(self, worker_id: str, lease_token: str, now: datetime) -> bool:
        return self._delegate.acquire(worker_id, lease_token, now)

    def heartbeat(self, worker_id: str, lease_token: str, now: datetime) -> bool:
        refreshed = self._delegate.heartbeat(worker_id, lease_token, now)
        if refreshed and now == self._expected_time:
            self._refreshed.set()
        return refreshed


@pytest.mark.postgres
def test_live_handler_heartbeats_while_only_a_stopped_run_is_requeued(
    recovery_sessions: sessionmaker[Session],
) -> None:
    now = datetime(2026, 7, 20, 9, 30, tzinfo=UTC)
    advanced = now + timedelta(seconds=2)
    current_time = [now]
    runs = RunsService(recovery_sessions)
    live = runs.submit(
        RunKind.CANDIDATE_RECOMMENDATION,
        {},
        "live",
        now - timedelta(microseconds=1),
    )
    stopped = runs.submit(RunKind.CANDIDATE_RECOMMENDATION, {}, "stopped", now)
    started = Event()
    release = Event()
    refreshed = Event()
    lease_refreshed = Event()
    handlers = HandlerRegistry()

    def block(context: object) -> None:
        del context
        started.set()
        assert release.wait(timeout=2)

    handlers.register(RunKind.CANDIDATE_RECOMMENDATION, block)
    observed_runs = ObservingRuns(runs, advanced, refreshed)
    live_worker = build_worker(
        observed_runs,
        handlers,
        lambda: current_time[0],
        ObservingLeaseStore(WorkerLeaseStore(recovery_sessions), advanced, lease_refreshed),
        "live-worker",
        stale_after_seconds=1,
        heartbeat_interval_seconds=0.01,
    )
    running = Thread(target=live_worker.run_once)
    running.start()
    try:
        assert started.wait(timeout=1)
        stopped_claim = runs.claim_next(now, "stopped-worker", "stopped-token")
        assert stopped_claim is not None
        current_time[0] = advanced
        assert lease_refreshed.wait(timeout=1)
        assert refreshed.wait(timeout=1)
        assert observed_runs.updates == [True]

        recovered: list[UUID] = []
        recovery_handlers = HandlerRegistry()
        recovery_handlers.register(
            RunKind.CANDIDATE_RECOMMENDATION,
            lambda context: recovered.append(context.run_id),
        )
        recovery_worker = build_worker(
            runs,
            recovery_handlers,
            lambda: advanced,
            WorkerLeaseStore(recovery_sessions),
            "recovery-worker",
            stale_after_seconds=1,
            heartbeat_interval_seconds=0.01,
        )
        assert recovery_worker.run_once() is True
        assert recovered == [UUID(stopped.run_id)]
        assert RunsService(recovery_sessions).get(live.run_id).status is RunStatus.RUNNING
        assert RunsService(recovery_sessions).get(live.run_id).retry_count == 0
    finally:
        release.set()
        running.join(timeout=2)
    assert not running.is_alive()
    assert RunsService(recovery_sessions).get(live.run_id).status is RunStatus.SUCCEEDED


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
