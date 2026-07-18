from dataclasses import replace
from datetime import timedelta

import pytest

from backend.app.contracts.grades import LlmGrade
from backend.app.core.market.pit_models import DataKind, TemporalRecord
from backend.app.features.holdings.quality import InvalidLlmEvidence, llm_grade_from_snapshot
from backend.tests.features.holdings.factories import point_in_time_snapshot


def llm_record(
    record_id: str,
    grade: LlmGrade,
    *,
    valid: bool = True,
    future_available: bool = False,
) -> TemporalRecord:
    snapshot = point_in_time_snapshot()
    available_at = (
        snapshot.as_of_time + timedelta(minutes=1) if future_available else snapshot.as_of_time
    )
    return TemporalRecord(
        record_id=record_id,
        kind=DataKind.LLM_FACTOR,
        entity_id="000001.SZ",
        event_time=snapshot.as_of_time,
        observed_at=snapshot.as_of_time,
        available_at=available_at,
        source_artifact_hash=f"hash-{record_id}",
        payload={"grade": grade.value, "valid": valid},
    )


def test_llm_grade_prefers_forward_observed_evidence() -> None:
    snapshot = point_in_time_snapshot()
    snapshot = replace(
        snapshot,
        market_inputs=(
            llm_record("reconstructed", LlmGrade.RECONSTRUCTED),
            llm_record("forward", LlmGrade.FORWARD_OBSERVED),
        ),
    )

    assert llm_grade_from_snapshot(snapshot) is LlmGrade.FORWARD_OBSERVED


def test_invalid_llm_evidence_is_not_used() -> None:
    snapshot = replace(
        point_in_time_snapshot(),
        market_inputs=(llm_record("invalid", LlmGrade.FORWARD_OBSERVED, valid=False),),
    )

    assert llm_grade_from_snapshot(snapshot) is LlmGrade.NOT_USED


def test_future_llm_evidence_fails_closed() -> None:
    snapshot = replace(
        point_in_time_snapshot(),
        market_inputs=(llm_record("future", LlmGrade.FORWARD_OBSERVED, future_available=True),),
    )

    with pytest.raises(InvalidLlmEvidence, match="future"):
        llm_grade_from_snapshot(snapshot)
