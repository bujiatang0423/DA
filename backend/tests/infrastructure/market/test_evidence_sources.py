from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Any

from backend.app.core.market.pit_models import DataKind, SnapshotScope
from backend.app.infrastructure.market.research_adapters import (
    LlmEvidenceSource,
    PolicyEvidenceSource,
)


UTC = UTC


@dataclass
class Material:
    source_id: str
    published_at: datetime
    first_observed_at: datetime
    evidence_grade: str
    content_hash: str
    text: str


class Policy:
    def materials(self, *, as_of_time: datetime) -> tuple[Material, ...]:
        return (Material("p1", as_of_time, as_of_time, "A", "policy-hash", "text"),)


def test_policy_source_maps_available_at_hash_and_lineage() -> None:
    as_of = datetime(2026, 1, 1, tzinfo=UTC)
    batch = PolicyEvidenceSource(Policy()).fetch(as_of_time=as_of, scope=SnapshotScope())
    item = batch.records[0]
    assert item.kind is DataKind.POLICY_DOCUMENT
    assert item.available_at == as_of and item.source_artifact_hash == "policy-hash"
    assert batch.lineage[0].source_artifact_hash == "policy-hash"


@dataclass
class Factor:
    as_of_time: datetime
    security_id: str
    model_id: str
    prompt_hash: str
    input_hash: str
    output_hash: str
    payload: dict


class Market:
    def universe(self, as_of_time: datetime) -> tuple[Any, ...]:
        return (type("S", (), {"security_id": "AAA"})(),)

    def financials(self, sid: str, as_of_time: datetime) -> tuple[Any, ...]:
        return ()


class Llm:
    def extract(self, **kwargs: Any) -> Factor:  # noqa: ANN401
        return Factor(
            kwargs["as_of_time"], kwargs["security_id"], "m", "prompt", "input", "output", {}
        )


def test_llm_source_preserves_output_hash_and_identity_lineage() -> None:
    as_of = datetime(2026, 1, 1, tzinfo=UTC)
    batch = LlmEvidenceSource(Llm(), Policy(), Market()).fetch(
        as_of_time=as_of, scope=SnapshotScope(("AAA",))
    )
    item = batch.records[0]
    assert item.kind is DataKind.LLM_FACTOR and item.available_at == as_of
    assert (
        item.payload["output_hash"] == "output"
        and batch.lineage[0].source_artifact_hash == "output"
    )
