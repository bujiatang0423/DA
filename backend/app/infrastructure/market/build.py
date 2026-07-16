from backend.app.infrastructure.market.research_adapters import (
    LlmEvidenceSource,
    MarketEvidenceSource,
    PolicyEvidenceSource,
    ResearchEvidenceSource,
)
from backend.app.infrastructure.market.research_warehouse import ResearchPointInTimeWarehouse


def build_point_in_time_warehouse(
    *,
    market: object,
    policy: object,
    llm: object,
    benchmark_ids: tuple[str, ...] = ("000985.CSI", "000001.SH"),
) -> ResearchPointInTimeWarehouse:
    return ResearchPointInTimeWarehouse(
        (
            ResearchEvidenceSource(
                (
                    MarketEvidenceSource(market, benchmark_ids),
                    PolicyEvidenceSource(policy),
                    LlmEvidenceSource(llm, policy, market),
                )
            ),
        )
    )
