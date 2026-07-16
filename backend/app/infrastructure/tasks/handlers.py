from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID
from backend.app.contracts.runs import RunKind


@dataclass(frozen=True)
class JobContext:
    run_id: UUID
    payload: dict[str, object]
    heartbeat: Callable[[str, int], None]


JobHandler = Callable[[JobContext], object]


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[RunKind, JobHandler] = {}

    def register(self, kind: RunKind, handler: JobHandler) -> None:
        if kind in self._handlers:
            raise ValueError(f"duplicate handler: {kind.value}")
        self._handlers[kind] = handler

    def resolve(self, kind: RunKind) -> JobHandler:
        if kind not in self._handlers:
            raise LookupError(kind.value)
        return self._handlers[kind]
