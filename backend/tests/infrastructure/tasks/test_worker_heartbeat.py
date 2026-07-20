from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from backend.app.contracts.runs import RunKind, RunStatus
from backend.app.features.backtests.ports import BacktestSnapshotQualityError
from backend.app.features.holdings.service import HoldingMarketDataMissing
from backend.app.infrastructure.tasks.handlers import HandlerRegistry
from backend.app.infrastructure.tasks.worker import Worker


class FakeRuns:
    def __init__(self) -> None:
        self.run = SimpleNamespace(id=uuid4(), kind=RunKind.BACKTEST.value, request_payload={})
        self.claims: list[tuple[str, str]] = []
        self.transitions: list[tuple[RunStatus, str | None, str | None]] = []

    def claim_next(self, now: datetime, worker_id: str, lease_token: str) -> SimpleNamespace | None:
        del now
        self.claims.append((worker_id, lease_token))
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
        error_message: str | None = None,
    ) -> SimpleNamespace:
        del run_id, now, worker_id, lease_token
        self.transitions.append((target, error_code, error_message))
        return self.run

    def requeue_stale(self, cutoff: datetime, now: datetime) -> tuple[object, ...]:
        del cutoff, now
        return ()


class FakeLeases:
    def __init__(self) -> None:
        self.heartbeats: list[tuple[str, str]] = []

    def acquire(self, worker_id: str, lease_token: str, now: datetime) -> bool:
        del now
        self.heartbeats.append((worker_id, lease_token))
        return True

    def heartbeat(self, worker_id: str, lease_token: str, now: datetime) -> bool:
        del now
        self.heartbeats.append((worker_id, lease_token))
        return True


def test_worker_heartbeats_its_durable_lease_before_claim_and_after_handler() -> None:
    runs = FakeRuns()
    leases = FakeLeases()
    handlers = HandlerRegistry()
    handlers.register(RunKind.BACKTEST, lambda context: None)

    worker = Worker(
        runs,
        handlers,
        lambda: datetime(2026, 7, 19, 9, 30, tzinfo=UTC),
        leases,
        "worker-a",
        "token-a",
    )

    assert worker.run_once() is True
    assert leases.heartbeats == [("worker-a", "token-a"), ("worker-a", "token-a")]
    assert runs.claims == [("worker-a", "token-a")]
    assert runs.transitions == [(RunStatus.SUCCEEDED, None, None)]


def test_worker_records_a_stable_failure_code_without_exception_text() -> None:
    runs = FakeRuns()
    leases = FakeLeases()
    handlers = HandlerRegistry()
    handlers.register(
        RunKind.BACKTEST,
        lambda context: (_ for _ in ()).throw(RuntimeError("account 12345678 failed")),
    )
    worker = Worker(
        runs,
        handlers,
        lambda: datetime(2026, 7, 19, 9, 30, tzinfo=UTC),
        leases,
        "worker-a",
        "token-a",
    )

    assert worker.run_once() is True
    assert runs.transitions == [
        (RunStatus.FAILED, "JOB_EXECUTION_FAILED", "任务执行失败，请稍后重试。")
    ]


@pytest.mark.parametrize(
    ("kind", "failure", "expected_code", "expected_message"),
    [
        (
            RunKind.CANDIDATE_RECOMMENDATION,
            RuntimeError("account 12345678 failed"),
            "JOB_EXECUTION_FAILED",
            "任务执行失败，请稍后重试。",
        ),
        (
            RunKind.HOLDING_ANALYSIS,
            HoldingMarketDataMissing("portfolio 12345678 unavailable"),
            "HOLDING_MARKET_DATA_MISSING",
            "持仓分析所需市场数据不可用。",
        ),
        (
            RunKind.BACKTEST,
            BacktestSnapshotQualityError(),
            "BACKTEST_SNAPSHOT_QUALITY_ERROR",
            "回测所需点时数据未通过验证。",
        ),
    ],
)
def test_worker_maps_business_failures_to_stable_safe_run_details(
    kind: RunKind,
    failure: Exception,
    expected_code: str,
    expected_message: str,
) -> None:
    runs = FakeRuns()
    runs.run.kind = kind.value
    leases = FakeLeases()
    handlers = HandlerRegistry()
    handlers.register(kind, lambda context: (_ for _ in ()).throw(failure))
    worker = Worker(
        runs,
        handlers,
        lambda: datetime(2026, 7, 19, 9, 30, tzinfo=UTC),
        leases,
        "worker-a",
        "token-a",
    )

    assert worker.run_once() is True
    assert runs.transitions == [(RunStatus.FAILED, expected_code, expected_message)]
