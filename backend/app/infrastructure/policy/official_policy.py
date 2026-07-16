from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from backend.app.ports.policy import PolicyMaterial


@dataclass(frozen=True)
class RawPolicyDocument:
    source_id: str
    published_at: datetime
    first_observed_at: datetime
    evidence_grade: str
    official_source_id: str | None
    content_hash: str
    text: str


class OfficialPolicyClient(Protocol):
    def fetch(self, *, as_of_time: datetime) -> tuple[RawPolicyDocument, ...]: ...


class OfficialPolicyAdapter:
    def __init__(self, client: OfficialPolicyClient) -> None:
        self._client = client

    def materials(self, *, as_of_time: datetime) -> tuple[PolicyMaterial, ...]:
        out = []
        for x in self._client.fetch(as_of_time=as_of_time):
            available = max(x.published_at, x.first_observed_at)
            if available > as_of_time:
                continue
            if not (x.evidence_grade == "A" or (x.evidence_grade == "B" and x.official_source_id)):
                continue
            out.append(
                PolicyMaterial(
                    x.source_id,
                    x.published_at,
                    x.first_observed_at,
                    x.evidence_grade,
                    x.content_hash,
                    x.text,
                )
            )
        return tuple(out)
