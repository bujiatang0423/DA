from collections.abc import Callable
from time import sleep
from datetime import datetime
from typing import Protocol
from backend.app.contracts.runs import RunKind, RunStatus
from .handlers import HandlerRegistry, JobContext

class RunStore(Protocol):
    def claim_next(self, now: datetime) -> object | None: ...
    def heartbeat(self, run_id: object, stage: str, progress: int, now: datetime) -> None: ...
    def transition(self, run_id: object, target: RunStatus, now: datetime) -> None: ...
    def requeue_stale(self, cutoff: datetime, now: datetime) -> tuple[object, ...]: ...
class Worker:
    def __init__(self, runs: RunStore, handlers: HandlerRegistry, clock: Callable[[], datetime]) -> None:
        self.runs = runs
        self.handlers = handlers
        self.clock = clock

    def run_once(self) -> bool:
        run = self.runs.claim_next(self.clock())
        if run is None:
            return False
        try:
            handler = self.handlers.resolve(RunKind(run.kind))
            context = JobContext(run.id, run.request_payload,
                                 lambda stage, progress: self.runs.heartbeat(
                                     run.id, stage, progress, self.clock()))
            handler(context)
        except Exception:
            self.runs.transition(run.id, RunStatus.FAILED, self.clock())
            return True
        self.runs.transition(run.id, RunStatus.SUCCEEDED, self.clock())
        return True

    def recover_stale(self, stale_after_seconds: int) -> tuple[object, ...]:
        from datetime import timedelta
        now = self.clock()
        return self.runs.requeue_stale(now - timedelta(seconds=stale_after_seconds), now)


def build_worker(runs: object, handlers: HandlerRegistry,
                 clock: Callable[[], datetime]) -> Worker:
    return Worker(runs, handlers, clock)


def run(worker: Worker, sleep_fn: Callable[[float], None] = sleep,
        stop: Callable[[], bool] | None = None, interval: float = 1.0) -> None:
    should_stop = stop or (lambda: False)
    while not should_stop():
        worker.run_once()
        if not should_stop():
            sleep_fn(interval)
