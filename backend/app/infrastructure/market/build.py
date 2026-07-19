from backend.app.infrastructure.market.research_adapters import (
    LlmEvidenceSource,
    MarketEvidenceSource,
    PolicyEvidenceSource,
    ResearchEvidenceSource,
)
from backend.app.infrastructure.market.research_warehouse import ResearchPointInTimeWarehouse
from backend.app.features.backtests.pit_certificate import PassedAuditReport, PitAuditAuthorizer
from backend.app.infrastructure.market.strict_reader import SqlStrictRecordReader
from backend.app.infrastructure.market.strict_warehouse import StrictPointInTimeWarehouse
from sqlalchemy.orm import Session


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


def build_strict_pit_warehouse(
    *,
    session: Session,
    audit_report: PassedAuditReport,
    authorizer: PitAuditAuthorizer,
) -> StrictPointInTimeWarehouse:
    """Build a certified strict warehouse; callers cannot select PIT grade directly."""
    return StrictPointInTimeWarehouse(
        SqlStrictRecordReader(session),
        authorizer.issue(audit_report),
    )
