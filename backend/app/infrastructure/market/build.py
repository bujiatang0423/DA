from backend.app.infrastructure.market.research_adapters import (
    LlmEvidenceSource,
    MarketEvidenceSource,
    PolicyEvidenceSource,
    ResearchEvidenceSource,
)
from backend.app.infrastructure.market.official_evidence import (
    OfficialEvidenceReader,
    OfficialEvidenceSource,
)
from backend.app.infrastructure.market.research_warehouse import ResearchPointInTimeWarehouse
from backend.app.infrastructure.market.strict_reader import SqlStrictRecordReader
from backend.app.infrastructure.market.strict_certificates import SqlPitCertificateAuthority
from backend.app.infrastructure.market.strict_warehouse import StrictPointInTimeWarehouse
from sqlalchemy.orm import Session


def build_point_in_time_warehouse(
    *,
    market: object,
    policy: object,
    llm: object,
    official_evidence: OfficialEvidenceReader | None = None,
    benchmark_ids: tuple[str, ...] = ("000985.CSI", "000001.SH"),
) -> ResearchPointInTimeWarehouse:
    sources: list[object] = [
        MarketEvidenceSource(market, benchmark_ids, official_evidence=official_evidence)
    ]
    if official_evidence is not None:
        sources.append(OfficialEvidenceSource(official_evidence))
    else:
        sources.append(PolicyEvidenceSource(policy))
    sources.append(LlmEvidenceSource(llm, policy, market, official_evidence=official_evidence))
    return ResearchPointInTimeWarehouse(
        (
            ResearchEvidenceSource(tuple(sources)),
        )
    )


def build_strict_pit_warehouse(
    *,
    session: Session,
    approval_secret: str,
) -> StrictPointInTimeWarehouse:
    """Build a warehouse that authorizes only persisted, approved audit reports."""
    return StrictPointInTimeWarehouse(
        SqlStrictRecordReader(session),
        SqlPitCertificateAuthority(session, approval_secret),
    )
