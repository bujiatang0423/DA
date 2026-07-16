from backend.app.bootstrap.feature_registry import FeatureModule
from backend.app.core.portfolio.analysis import HoldingAnalysisService
from backend.app.ports.portfolio import PortfolioReader
from .router import build_router


def build_holdings_feature(reader: PortfolioReader) -> FeatureModule:
    return FeatureModule("holdings", build_router(HoldingAnalysisService(reader)), ())
