from backend.app.bootstrap.feature_registry import FeatureModule
from backend.app.core.portfolio.analysis import HoldingAnalysisService
from backend.app.ports.portfolio import PortfolioReader
from .router import build_router
from .maintenance_router import build_maintenance_router
from backend.app.infrastructure.persistence.portfolio_maintenance import (
    SqlPortfolioMaintenanceService,
)
from backend.app.contracts.runs import RunKind
from .jobs import HoldingAnalysisJobHandler
from .service import V212HoldingAnalysisService
from .repository import HoldingResultRepository


def build_holdings_feature(
    reader: PortfolioReader,
    maintenance: SqlPortfolioMaintenanceService | None = None,
    submit: object | None = None,
    result_repository: HoldingResultRepository | None = None,
    analysis_service: V212HoldingAnalysisService | None = None,
) -> FeatureModule:
    router = build_router(HoldingAnalysisService(reader), submit, result_repository)
    if maintenance is not None:
        router.include_router(build_maintenance_router(maintenance))
    handlers = (
        ((RunKind.HOLDING_ANALYSIS, HoldingAnalysisJobHandler(analysis_service)),)
        if analysis_service
        else ()
    )
    return FeatureModule("holdings", router, handlers)
