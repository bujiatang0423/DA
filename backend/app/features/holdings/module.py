from backend.app.bootstrap.feature_registry import FeatureModule
from backend.app.core.portfolio.analysis import HoldingAnalysisService
from backend.app.ports.portfolio import PortfolioReader
from .router import build_router
from .maintenance_router import build_maintenance_router
from backend.app.infrastructure.persistence.portfolio_maintenance import (
    SqlPortfolioMaintenanceService,
)


def build_holdings_feature(
    reader: PortfolioReader,
    maintenance: SqlPortfolioMaintenanceService | None = None,
) -> FeatureModule:
    router = build_router(HoldingAnalysisService(reader))
    if maintenance is not None:
        router.include_router(build_maintenance_router(maintenance))
    return FeatureModule("holdings", router, ())
