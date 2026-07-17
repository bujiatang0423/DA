from collections.abc import Mapping

from backend.app.contracts.grades import LlmGrade


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
