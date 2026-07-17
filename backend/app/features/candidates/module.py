from collections.abc import Callable
from datetime import datetime

from backend.app.bootstrap.feature_registry import FeatureModule
from backend.app.contracts.runs import RunKind, RunRef
from .router import build_router


def build_candidate_feature(
    submit: Callable[[RunKind, dict[str, object], str | None, datetime], RunRef] | None = None,
) -> FeatureModule:
    return FeatureModule("candidates", build_router(submit), ())
