from datetime import datetime
from typing import Protocol

from backend.app.contracts.runs import RunKind, RunRef


class RunSubmitter(Protocol):
    def submit(
        self,
        kind: RunKind,
        payload: dict[str, object],
        idempotency_key: str | None,
        submitted_at: datetime,
    ) -> RunRef: ...
