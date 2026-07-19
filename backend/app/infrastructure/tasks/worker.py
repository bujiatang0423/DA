from collections.abc import Callable
from time import sleep
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from backend.app.contracts.runs import RunKind, RunStatus
from .handlers import HandlerRegistry, JobContext


class RunStore(Protocol):
    def claim_next(self, now: datetime, worker_id: str, lease_token: str) -> object | None: ...
    def heartbeat(
        self,
        run_id: object,
        stage: str,
        progress: int,
        now: datetime,
        worker_id: str,
        lease_token: str,
    ) -> bool: ...
    def transition(
        self,
        run_id: object,
        target: RunStatus,
        now: datetime,
        worker_id: str,
        lease_token: str,
        error_code: str | None = None,
    ) -> object | None: ...
    def requeue_stale(self, cutoff: datetime, now: datetime) -> tuple[object, ...]: ...


class WorkerLease(Protocol):
    def acquire(self, worker_id: str, lease_token: str, now: datetime) -> bool: ...

    def heartbeat(self, worker_id: str, lease_token: str, now: datetime) -> bool: ...


class Worker:
    def __init__(
        self,
        runs: RunStore,
        handlers: HandlerRegistry,
        clock: Callable[[], datetime],
        leases: WorkerLease,
        worker_id: str,
        lease_token: str | None = None,
    ) -> None:
        self.runs = runs
        self.handlers = handlers
        self.clock = clock
        self.leases = leases
        self.worker_id = worker_id
        self.lease_token = lease_token or uuid4().hex

    def run_once(self) -> bool:
        if not self.leases.acquire(self.worker_id, self.lease_token, self.clock()):
            return False
        run = self.runs.claim_next(self.clock(), self.worker_id, self.lease_token)
        if run is None:
            return False
        try:
            handler = self.handlers.resolve(RunKind(run.kind))
            context = JobContext(
                run.id,
                run.request_payload,
                lambda stage, progress: self.runs.heartbeat(
                    run.id,
                    stage,
                    progress,
                    self.clock(),
                    self.worker_id,
                    self.lease_token,
                ),
            )
            handler(context)
        except Exception:
            if not self.leases.heartbeat(self.worker_id, self.lease_token, self.clock()):
                return True
            self.runs.transition(
                run.id,
                RunStatus.FAILED,
                self.clock(),
                self.worker_id,
                self.lease_token,
                "JOB_EXECUTION_FAILED",
            )
            return True
        if not self.leases.heartbeat(self.worker_id, self.lease_token, self.clock()):
            return True
        self.runs.transition(
            run.id, RunStatus.SUCCEEDED, self.clock(), self.worker_id, self.lease_token
        )
        return True

    def recover_stale(self, stale_after_seconds: int) -> tuple[object, ...]:
        from datetime import timedelta

        now = self.clock()
        return self.runs.requeue_stale(now - timedelta(seconds=stale_after_seconds), now)


def build_worker(
    runs: RunStore,
    handlers: HandlerRegistry,
    clock: Callable[[], datetime],
    leases: WorkerLease,
    worker_id: str,
) -> Worker:
    return Worker(runs, handlers, clock, leases, worker_id)


def run(
    worker: Worker,
    sleep_fn: Callable[[float], None] = sleep,
    stop: Callable[[], bool] | None = None,
    interval: float = 1.0,
) -> None:
    should_stop = stop or (lambda: False)
    while not should_stop():
        worker.run_once()
        if not should_stop():
            sleep_fn(interval)
