from datetime import UTC, datetime

from backend.app.infrastructure.llm.deepseek_provider import DeepSeekFactorProvider
from backend.app.ports.policy import PolicyMaterial
from backend.app.ports.research_data import FinancialMaterial


def test_deepseek_provider_returns_schema_checked_factor_with_hashes() -> None:
    as_of = datetime(2026, 7, 29, 10, tzinfo=UTC)
    requests: list[dict[str, object]] = []

    def post(**kwargs: object) -> object:
        requests.append(kwargs)
        return {
            "choices": [
                {
                    "message": {
                        "content": """{
                            \"policy_direction\": \"neutral\",
                            \"implementation_stage\": \"planning\",
                            \"financial_light\": \"green\",
                            \"policy_strength\": 50,
                            \"policy_relevance\": 50,
                            \"financial_text_score\": 50,
                            \"llm_confidence\": 0.5,
                            \"evidence_confidence\": 0.5,
                            \"data_completeness\": 0.5,
                            \"red_flags\": [],
                            \"evidence\": [{
                                \"source_id\": \"policy-hash\",
                                \"published_at\": \"2026-07-29T10:00:00+00:00\",
                                \"quote\": \"official policy\"
                            }]
                        }"""
                    }
                }
            ]
        }

    provider = DeepSeekFactorProvider(api_key="secret", post=post, model="deepseek-v4-pro")
    factor = provider.extract(
        as_of_time=as_of,
        security_id="000568.SZ",
        policy_materials=(
            PolicyMaterial("policy-hash", as_of, as_of, "A", "policy-hash", "policy text"),
        ),
        financial_materials=(
            FinancialMaterial("000568.SZ", as_of.date(), as_of, {"roe": "0.2"}, "fin-hash"),
        ),
    )

    assert factor.security_id == "000568.SZ"
    assert factor.model_id == "deepseek-v4-pro"
    assert factor.payload["policy_direction"] == "neutral"
    assert len(factor.prompt_hash) == len(factor.input_hash) == len(factor.output_hash) == 64
    assert requests[0]["headers"] == {"Authorization": "Bearer secret"}
