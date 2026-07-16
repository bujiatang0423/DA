from collections.abc import Callable
from datetime import datetime
from backend.app.contracts.runs import RunKind, RunStatus
from .handlers import HandlerRegistry, JobContext
class Worker:
    def __init__(self, runs: object, handlers: HandlerRegistry, clock: Callable[[], datetime]) -> None: self.runs=runs; self.handlers=handlers; self.clock=clock
    def run_once(self) -> bool:
        run=self.runs.claim_next(self.clock())
        if run is None:return False
        try:self.handlers.resolve(RunKind(run.kind))(JobContext(run.id,run.request_payload,lambda stage,progress:self.runs.heartbeat(run.id,stage,progress,self.clock())))
        except Exception:self.runs.transition(run.id,RunStatus.FAILED,self.clock()); return True
        self.runs.transition(run.id,RunStatus.SUCCEEDED,self.clock()); return True
def run() -> None: pass
