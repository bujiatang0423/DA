from .models import CandidateRecommendationResult


def render_markdown(result: CandidateRecommendationResult) -> str:
    lines = [
        "---",
        f"strategy_version: {result.strategy_version}",
        "auto_trade_enabled: false",
        "human_confirm_required: true",
        "---",
        f"# Candidate recommendation ({result.as_of_time.isoformat()})",
    ]
    for item in result.items:
        lines.append(
            f"- {item.security_id} | {item.bucket.value} | {item.state.value} | S={item.factors.s}"
        )
    return "\n".join(lines) + "\n"


def render_candidate_markdown(result: CandidateRecommendationResult) -> str:
    return render_markdown(result)
