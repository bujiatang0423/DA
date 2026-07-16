from backend.app.bootstrap.feature_registry import FeatureModule

from .router import build_router


def build_backtests_feature() -> FeatureModule:
    return FeatureModule("backtests", build_router(), ())
