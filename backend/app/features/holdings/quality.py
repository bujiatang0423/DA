from collections.abc import Mapping

from backend.app.contracts.grades import LlmGrade
from backend.app.core.market.pit_models import DataKind, PointInTimeSnapshot, TemporalRecord


class InvalidLlmEvidence(ValueError):
    pass


_LLM_GRADE_RANK = {
    LlmGrade.NOT_USED: 0,
    LlmGrade.RECONSTRUCTED: 1,
    LlmGrade.FORWARD_OBSERVED: 2,
}


def llm_grade_from_manifest(manifest: Mapping[str, object] | None) -> LlmGrade:
    if not manifest:
        return LlmGrade.NOT_USED
    value = str(manifest.get("grade", "")).lower()
    if value in {LlmGrade.RECONSTRUCTED.value, LlmGrade.FORWARD_OBSERVED.value}:
        return LlmGrade(value)
    return LlmGrade.NOT_USED


def valid_evidence_refs(manifest: Mapping[str, object] | None) -> tuple[str, ...]:
    if not manifest or not bool(manifest.get("valid", False)):
        return ()
    refs = manifest.get("evidence_refs", ())
    if not isinstance(refs, (list, tuple)):
        return ()
    return tuple(str(ref) for ref in refs)


def _llm_records(snapshot: PointInTimeSnapshot) -> tuple[TemporalRecord, ...]:
    market_records = tuple(
        record for record in snapshot.market_inputs if record.kind is DataKind.LLM_FACTOR
    )
    security_records = tuple(
        record
        for observation in snapshot.security_observations
        for record in observation.records
        if record.kind is DataKind.LLM_FACTOR
    )
    return market_records + security_records


def llm_grade_from_snapshot(snapshot: PointInTimeSnapshot) -> LlmGrade:
    records = _llm_records(snapshot)
    if not records:
        return LlmGrade.NOT_USED
    if any(record.available_at > snapshot.as_of_time for record in records):
        raise InvalidLlmEvidence("future LLM evidence is invalid for this snapshot")
    manifests = tuple(dict(record.payload) for record in records)
    if any(manifest.get("valid") is False for manifest in manifests):
        return LlmGrade.NOT_USED
    grades = tuple(
        llm_grade_from_manifest(manifest)
        for manifest in manifests
        if manifest.get("grade") is not None
    )
    return max(
        grades,
        default=LlmGrade.RECONSTRUCTED,
        key=lambda grade: _LLM_GRADE_RANK[grade],
    )
