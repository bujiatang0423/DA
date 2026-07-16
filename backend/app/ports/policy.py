from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class PolicyMaterial:
    source_id: str
    published_at: datetime
    first_observed_at: datetime
    evidence_grade: str
    content_hash: str
    text: str


class PolicyPort(Protocol):
    def materials(self, *, as_of_time: datetime) -> tuple[PolicyMaterial, ...]: ...
