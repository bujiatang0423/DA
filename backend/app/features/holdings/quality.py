from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from string import hexdigits

from backend.app.contracts.grades import LlmGrade
from backend.app.core.market.pit_models import DataKind, PointInTimeSnapshot, TemporalRecord


class InvalidLlmEvidence(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class HoldingEvidence:
    refs: tuple[str, ...]

    @property
    def is_available(self) -> bool:
        return bool(self.refs)


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


def holding_evidence(snapshot: PointInTimeSnapshot, security_id: str) -> HoldingEvidence:
    records = (*snapshot.market_inputs, *_security_records(snapshot, security_id))
    lineage_hashes = {
        normalized
        for lineage in snapshot.lineage
        if (normalized := _normalized_artifact_hash(lineage.source_artifact_hash)) is not None
    }
    refs = {
        _safe_evidence_ref(record, lineage_hashes)
        for record in records
        if _is_point_in_time_visible(record, snapshot.as_of_time)
    }
    return HoldingEvidence(tuple(sorted(ref for ref in refs if ref is not None)))


def _security_records(
    snapshot: PointInTimeSnapshot,
    security_id: str,
) -> tuple[TemporalRecord, ...]:
    for observation in snapshot.security_observations:
        if observation.security_id == security_id:
            return observation.records
    return ()


def _safe_evidence_ref(record: TemporalRecord, lineage_hashes: set[str]) -> str | None:
    artifact_hash = _normalized_artifact_hash(record.source_artifact_hash)
    if artifact_hash is None or artifact_hash not in lineage_hashes:
        return None
    return f"pit:{record.kind.value}:{artifact_hash}"


def _normalized_artifact_hash(artifact_hash: str) -> str | None:
    if len(artifact_hash) != 64 or any(character not in hexdigits for character in artifact_hash):
        return None
    return artifact_hash.lower()


def _is_point_in_time_visible(record: TemporalRecord, as_of_time: datetime) -> bool:
    times = (record.event_time, record.observed_at, record.available_at, as_of_time)
    if any(value.tzinfo is None or value.utcoffset() is None for value in times):
        return False
    as_of_utc = as_of_time.astimezone(UTC)
    return all(value.astimezone(UTC) <= as_of_utc for value in times[:3])


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
