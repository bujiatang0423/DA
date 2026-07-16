from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from backend.app.core.market.pit_models import LineageRef, SnapshotScope, TemporalRecord


@dataclass(frozen=True)
class ResearchBatch:
    records: tuple[TemporalRecord, ...]
    lineage: tuple[LineageRef, ...]


class ResearchSource(Protocol):
    provider: str
    def fetch(self, *, as_of_time: datetime, scope: SnapshotScope) -> ResearchBatch: ...
