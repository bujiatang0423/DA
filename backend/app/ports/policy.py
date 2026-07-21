from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class PolicyMaterial:
    source_id: str
    published_at: datetime
    first_observed_at: datetime
    evidence_grade: str
    content_hash: str
    text: str


@runtime_checkable
class PolicyPort(Protocol):
    def materials(self, *, as_of_time: datetime) -> tuple[PolicyMaterial, ...]: ...
