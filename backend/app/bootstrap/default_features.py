from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from backend.app.bootstrap.feature_registry import FeatureModule
from backend.app.bootstrap.settings import Settings
from backend.app.features.runs.module import build_runs_feature
from backend.app.features.runs.service import RunsService


@dataclass(frozen=True)
class ApplicationDependencies:
    settings: Settings
    session_factory: sessionmaker[Session]
    runs_service: RunsService


def build_default_features(dependencies: ApplicationDependencies) -> tuple[FeatureModule, ...]:
    return (build_runs_feature(dependencies.runs_service),)
