from pathlib import Path

from backend.app.contracts.grades import DataGrade, LlmGrade
from backend.app.features.candidates.models import CandidateRecommendationResult


def test_candidate_results_are_always_manual_only() -> None:
    fields = CandidateRecommendationResult.__dataclass_fields__

    assert fields["auto_trade_enabled"].default is False
    assert fields["human_confirm_required"].default is True


def test_candidate_feature_has_no_unsafe_runtime_dependencies_or_markdown_input_parser() -> None:
    feature_root = Path("backend/app/features/candidates")
    source = "\n".join(path.read_text(encoding="utf-8") for path in feature_root.glob("*.py"))

    assert "parse_markdown" not in source
    assert "/Users/bujiatang/workspace/LA" not in source
    assert "llm_raw_output.action" not in source
    assert DataGrade.RESEARCH.value == "research"
    assert LlmGrade.NOT_USED.value == "not_used"
