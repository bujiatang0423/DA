from collections.abc import Callable
from datetime import datetime

from backend.app.bootstrap.feature_registry import FeatureModule
from backend.app.contracts.runs import RunKind, RunRef
from .jobs import CandidateJobHandler
from .repository import CandidateRepository
from .service import CandidateService
from .router import build_router


def build_candidate_feature(
    submit: Callable[[RunKind, dict[str, object], str | None, datetime], RunRef] | None = None,
    repository: CandidateRepository | None = None,
    service: CandidateService | None = None,
) -> FeatureModule:
    handlers = ((RunKind.CANDIDATE_RECOMMENDATION, CandidateJobHandler(service)),) if service else ()
    return FeatureModule("candidates", build_router(submit, repository), handlers)
