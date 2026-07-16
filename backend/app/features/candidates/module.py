from backend.app.bootstrap.feature_registry import FeatureModule
from .router import build_router


def build_candidate_feature() -> FeatureModule:
    return FeatureModule("candidates", build_router(), ())
