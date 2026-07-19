from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

from backend.app.contracts.runs import RunKind, RunStatus
from backend.app.infrastructure.tasks.handlers import HandlerRegistry
from backend.app.infrastructure.tasks.worker import Worker


class FakeRuns:
    def __init__(self) -> None:
        self.run = SimpleNamespace(id=uuid4(), kind=RunKind.BACKTEST.value, request_payload={})
        self.claims: list[tuple[str, str]] = []
        self.transitions: list[tuple[RunStatus, str | None]] = []

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
    ) -> SimpleNamespace:
        del run_id, now, worker_id, lease_token
        self.transitions.append((target, error_code))
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
    assert runs.transitions == [(RunStatus.SUCCEEDED, None)]


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
    assert runs.transitions == [(RunStatus.FAILED, "JOB_EXECUTION_FAILED")]
