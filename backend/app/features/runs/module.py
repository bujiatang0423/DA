from backend.app.bootstrap.feature_registry import FeatureModule
from backend.app.features.runs.service import RunsService
from backend.app.features.runs.router import build_router


def build_runs_feature(service: RunsService) -> FeatureModule:
    return FeatureModule("runs", build_router(service), ())
