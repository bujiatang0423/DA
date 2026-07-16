from backend.app.contracts.grades import LlmGrade


def derive_llm_grade(manifest: dict[str, object] | None) -> tuple[LlmGrade, tuple[str, ...]]:
    if not manifest:
        return LlmGrade.NOT_USED, ("LLM_EVIDENCE_MISSING",)
    grade = LlmGrade(str(manifest.get("grade", LlmGrade.RECONSTRUCTED.value)))
    return (grade, ()) if manifest.get("valid", False) else (grade, ("LLM_FACTOR_INVALID",))
