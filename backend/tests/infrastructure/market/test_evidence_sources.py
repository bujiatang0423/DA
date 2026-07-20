from dataclasses import dataclass
from datetime import date, datetime, UTC
from decimal import Decimal
from typing import Any

import pytest

from backend.app.core.market.pit_models import DataKind, SnapshotScope, TemporalRecord
from backend.app.infrastructure.market.research_adapters import (
    LlmEvidenceSource,
    MarketEvidenceSource,
    PolicyEvidenceSource,
    ResearchEvidenceSource,
)
from backend.app.infrastructure.market.research_source import ResearchBatch
from backend.app.infrastructure.llm.deepseek_factor import LlmFactorValidationError
from backend.app.ports.research_data import FinancialMaterial


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


def test_policy_source_excludes_material_not_observed_at_as_of_time() -> None:
    as_of = datetime(2026, 1, 1, tzinfo=UTC)

    class FutureObservedPolicy:
        def materials(self, *, as_of_time: datetime) -> tuple[Material, ...]:
            return (
                Material(
                    "p1",
                    as_of_time,
                    as_of_time.replace(day=2),
                    "A",
                    "policy-hash",
                    "text",
                ),
            )

    batch = PolicyEvidenceSource(FutureObservedPolicy()).fetch(
        as_of_time=as_of, scope=SnapshotScope()
    )

    assert batch.records == ()


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
            kwargs["as_of_time"],
            kwargs["security_id"],
            "m",
            "prompt",
            "input",
            "output",
            valid_factor_payload(kwargs["as_of_time"]),
        )


def valid_factor_payload(as_of_time: datetime) -> dict[str, object]:
    return {
        "policy_direction": "neutral",
        "implementation_stage": "planning",
        "financial_light": "unknown",
        "policy_strength": 50,
        "policy_relevance": 50,
        "financial_text_score": 50,
        "llm_confidence": 0.5,
        "evidence_confidence": 0.5,
        "data_completeness": 0.5,
        "red_flags": [],
        "evidence": [
            {
                "source_id": "p1",
                "published_at": as_of_time.isoformat(),
                "quote": "official evidence",
            }
        ],
    }


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


def test_market_source_excludes_future_financial_publication() -> None:
    as_of = datetime(2026, 1, 1, tzinfo=UTC)

    class FinancialMarket:
        def universe(self, as_of_time: datetime) -> tuple[Any, ...]:
            return (type("Security", (), {"security_id": "AAA"})(),)

        def daily_bars(self, security_id: str, as_of_time: datetime) -> tuple[Any, ...]:
            return ()

        def financials(
            self, security_id: str, as_of_time: datetime
        ) -> tuple[FinancialMaterial, ...]:
            return (
                FinancialMaterial(
                    security_id="AAA",
                    report_period=date(2025, 12, 31),
                    published_at=as_of_time.replace(day=2),
                    facts={"roe": Decimal("0.1")},
                    source_hash="future-financial",
                ),
            )

    batch = MarketEvidenceSource(FinancialMarket()).fetch(
        as_of_time=as_of,
        scope=SnapshotScope(
            security_ids=("AAA",),
            required_kinds=(DataKind.FINANCIAL_DISCLOSURE, DataKind.FINANCIAL_FACT),
        ),
    )

    assert batch.records == ()


def test_market_source_filters_future_records_from_research_records_fast_path() -> None:
    as_of = datetime(2026, 1, 1, tzinfo=UTC)

    class RecordsMarket:
        def research_records(
            self, *, as_of_time: datetime, scope: SnapshotScope
        ) -> tuple[TemporalRecord, ...]:
            return (
                TemporalRecord(
                    "financial_disclosure:AAA:2025-12-31",
                    DataKind.FINANCIAL_DISCLOSURE,
                    "AAA",
                    as_of_time,
                    as_of_time,
                    as_of_time.replace(day=2),
                    "future-financial",
                    {},
                ),
            )

    batch = MarketEvidenceSource(RecordsMarket()).fetch(
        as_of_time=as_of,
        scope=SnapshotScope(required_kinds=(DataKind.FINANCIAL_DISCLOSURE,)),
    )

    assert batch.records == ()


def test_market_source_maps_available_financial_disclosure_and_facts() -> None:
    as_of = datetime(2026, 1, 1, tzinfo=UTC)

    class FinancialMarket:
        def universe(self, as_of_time: datetime) -> tuple[Any, ...]:
            return ()

        def daily_bars(self, security_id: str, as_of_time: datetime) -> tuple[Any, ...]:
            return ()

        def financials(
            self, security_id: str, as_of_time: datetime
        ) -> tuple[FinancialMaterial, ...]:
            return (
                FinancialMaterial(
                    security_id="AAA",
                    report_period=date(2025, 12, 31),
                    published_at=as_of_time,
                    facts={"roe": Decimal("0.1")},
                    source_hash="financial-hash",
                ),
            )

    batch = MarketEvidenceSource(FinancialMarket()).fetch(
        as_of_time=as_of,
        scope=SnapshotScope(
            security_ids=("AAA",),
            required_kinds=(DataKind.FINANCIAL_DISCLOSURE, DataKind.FINANCIAL_FACT),
        ),
    )

    assert {record.kind for record in batch.records} == {
        DataKind.FINANCIAL_DISCLOSURE,
        DataKind.FINANCIAL_FACT,
    }
    assert all(record.available_at == as_of for record in batch.records)
    assert {item.source_artifact_hash for item in batch.lineage} == {"financial-hash"}


def test_llm_source_rejects_unvalidated_factor_before_snapshot_assembly() -> None:
    as_of = datetime(2026, 1, 1, tzinfo=UTC)

    class InvalidLlm:
        def extract(self, **kwargs: Any) -> Factor:  # noqa: ANN401
            return Factor(
                kwargs["as_of_time"],
                kwargs["security_id"],
                "m",
                "prompt",
                "input",
                "output",
                {"action": "buy"},
            )

    with pytest.raises(LlmFactorValidationError, match="forbidden"):
        LlmEvidenceSource(InvalidLlm(), Policy(), Market()).fetch(
            as_of_time=as_of, scope=SnapshotScope(("AAA",))
        )


def test_llm_source_accepts_evidence_from_a_public_financial_source() -> None:
    as_of = datetime(2026, 1, 1, tzinfo=UTC)

    class FinancialEvidenceMarket(Market):
        def financials(self, sid: str, as_of_time: datetime) -> tuple[FinancialMaterial, ...]:
            return (
                FinancialMaterial(
                    security_id=sid,
                    report_period=date(2025, 12, 31),
                    published_at=as_of_time,
                    facts={},
                    source_hash="financial-hash",
                ),
            )

    class FinancialEvidenceLlm:
        def extract(self, **kwargs: Any) -> Factor:  # noqa: ANN401
            payload = valid_factor_payload(kwargs["as_of_time"])
            payload["evidence"] = [
                {
                    "source_id": "financial-hash",
                    "published_at": kwargs["as_of_time"].isoformat(),
                    "quote": "published financial disclosure",
                }
            ]
            return Factor(
                kwargs["as_of_time"],
                kwargs["security_id"],
                "m",
                "prompt",
                "input",
                "output",
                payload,
            )

    batch = LlmEvidenceSource(FinancialEvidenceLlm(), Policy(), FinancialEvidenceMarket()).fetch(
        as_of_time=as_of, scope=SnapshotScope(("AAA",))
    )

    assert batch.records[0].kind is DataKind.LLM_FACTOR


def test_research_evidence_rejects_conflicting_provider_records() -> None:
    as_of = datetime(2026, 1, 1, tzinfo=UTC)

    class Source:
        provider = "fixture"

        def __init__(self, artifact_hash: str) -> None:
            self._artifact_hash = artifact_hash

        def fetch(self, *, as_of_time: datetime, scope: SnapshotScope) -> ResearchBatch:
            record = TemporalRecord(
                "policy_document:MARKET:POLICY:one",
                DataKind.POLICY_DOCUMENT,
                "MARKET:POLICY",
                as_of_time,
                as_of_time,
                as_of_time,
                self._artifact_hash,
                {"source_id": "one"},
            )
            return ResearchBatch((record,), ())

    with pytest.raises(ValueError, match="conflicting record"):
        ResearchEvidenceSource((Source("one"), Source("two"))).fetch(
            as_of_time=as_of, scope=SnapshotScope()
        )
