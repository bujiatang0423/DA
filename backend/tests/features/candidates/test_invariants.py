from pathlib import Path

from backend.app.features.candidates.models import CandidateRecommendationResult


def test_candidate_results_are_manual_only_and_feature_does_not_parse_advice_text() -> None:
    fields = CandidateRecommendationResult.__dataclass_fields__
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("backend/app/features/candidates").glob("*.py")
    )

    assert fields["auto_trade_enabled"].default is False
    assert fields["human_confirm_required"].default is True
    assert "parse_markdown" not in source
    assert "/Users/bujiatang/workspace/LA" not in source
    assert "llm_raw_output.action" not in source
