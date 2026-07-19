from backend.app.bootstrap.feature_registry import FeatureModule
from backend.app.features.legacy_import.router import build_router
from backend.app.features.legacy_import.web_service import LegacyImportWebService


def build_legacy_import_feature(service: LegacyImportWebService) -> FeatureModule:
    return FeatureModule("legacy-import", build_router(service), ())
