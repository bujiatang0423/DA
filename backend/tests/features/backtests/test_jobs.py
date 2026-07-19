from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

from backend.app.contracts.runs import RunKind, RunStatus
from backend.app.features.backtests.jobs import BacktestJobHandler
from backend.app.features.backtests.module import build_backtests_feature
from backend.app.features.backtests.service import BacktestService
from backend.app.infrastructure.tasks.handlers import HandlerRegistry
from backend.app.infrastructure.tasks.worker import Worker
from backend.tests.features.backtests.fakes import (
    MemoryArtifactRepository,
    MemoryBacktestRepository,
)
from backend.tests.features.backtests.test_repository import fixed_result as result_fixture


class FixedExperimentRunner:
    def run(self, request: object) -> object:
        result = result_fixture.__wrapped__()
        return result.model_copy(update={"request": request})


class FakeRuns:
    def __init__(self, payload: dict[str, object]) -> None:
        self.run = SimpleNamespace(
            id=UUID("00000000-0000-0000-0000-000000000006"),
            kind=RunKind.BACKTEST.value,
            request_payload=payload,
        )
        self.status: RunStatus | None = None

    def claim_next(self, now: datetime, worker_id: str, lease_token: str) -> object:
        del now, worker_id, lease_token
        return self.run

    def heartbeat(
        self,
        run_id: UUID,
        stage: str,
        progress: int,
        now: datetime,
        worker_id: str,
        lease_token: str,
    ) -> bool:
        del run_id, stage, progress, now, worker_id, lease_token
        return True

    def transition(
        self,
        run_id: UUID,
        target: RunStatus,
        now: datetime,
        worker_id: str,
        lease_token: str,
        error_code: str | None = None,
    ) -> object:
        del run_id, now, worker_id, lease_token, error_code
        self.status = target
        return self.run

    def requeue_stale(self, cutoff: datetime, now: datetime) -> tuple[object, ...]:
        del cutoff, now
        return ()


class FakeLeases:
    def acquire(self, worker_id: str, lease_token: str, now: datetime) -> bool:
        del worker_id, lease_token, now
        return True

    def heartbeat(self, worker_id: str, lease_token: str, now: datetime) -> bool:
        del worker_id, lease_token, now
        return True


def test_backtest_handler_runs_engine_and_publishes_before_worker_succeeds() -> None:
    request = {
        "strategy_version": "v2.12",
        "start_date": "2023-01-02",
        "end_date": "2023-01-04",
        "initial_cash": "150000",
        "groups": ["A", "B"],
    }
    runs = FakeRuns(request)
    results = MemoryBacktestRepository()
    handler = BacktestJobHandler(
        BacktestService(FixedExperimentRunner(), results, MemoryArtifactRepository())
    )
    handlers = HandlerRegistry()
    handlers.register(RunKind.BACKTEST, handler)

    worker = Worker(
        runs,
        handlers,
        lambda: datetime(2026, 7, 19, 9, 30, tzinfo=UTC),
        FakeLeases(),
        "worker-a",
        "token-a",
    )

    assert worker.run_once() is True
    assert runs.status is RunStatus.SUCCEEDED
    assert results.results[runs.run.id].request.strategy_version == "v2.12"


def test_backtest_module_registers_the_real_job_handler() -> None:
    service = BacktestService(
        FixedExperimentRunner(), MemoryBacktestRepository(), MemoryArtifactRepository()
    )

    feature = build_backtests_feature(service=service)

    assert feature.job_handlers[0][0] is RunKind.BACKTEST
    assert isinstance(feature.job_handlers[0][1], BacktestJobHandler)
