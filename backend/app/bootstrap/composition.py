from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from backend.app.bootstrap.settings import Settings
from backend.app.core.market.strategy_inputs import StrategyInputBuilder
from backend.app.core.strategy.service import V212StrategyEngine
from backend.app.features.candidates.repository import SqlCandidateRepository
from backend.app.features.candidates.service import CandidateService
from backend.app.features.holdings.repository import SqlHoldingResultRepository
from backend.app.features.holdings.service import V212HoldingAnalysisService
from backend.app.infrastructure.persistence.portfolio_reader import SqlPortfolioReader
from backend.app.ports.point_in_time import PointInTimeWarehouse
from backend.app.infrastructure.market.unavailable import UnavailableResearchWarehouse


@dataclass(frozen=True)
class ApplicationComponents:
    strategy_engine: V212StrategyEngine
    warehouse: PointInTimeWarehouse
    candidate_service: CandidateService
    holding_service: V212HoldingAnalysisService
    holding_repository: SqlHoldingResultRepository


def build_components(settings: Settings, sessions: sessionmaker[Session]) -> ApplicationComponents:
    """Build shared strategy dependencies without duplicating feature logic.

    Production data providers can replace the fail-closed warehouse at this boundary. Until all
    provider adapters are configured, the default remains explicit and produces no executable item.
    """
    del settings
    warehouse: PointInTimeWarehouse = UnavailableResearchWarehouse()
    strategy = V212StrategyEngine()
    service = CandidateService(
        warehouse,
        SqlPortfolioReader(sessions),
        StrategyInputBuilder(),
        strategy,
        SqlCandidateRepository(sessions),
    )
    holding_repository = SqlHoldingResultRepository(sessions)
    holding_service = V212HoldingAnalysisService(
        warehouse,
        SqlPortfolioReader(sessions),
        StrategyInputBuilder(),
        strategy,
        holding_repository,
    )
    return ApplicationComponents(strategy, warehouse, service, holding_service, holding_repository)
