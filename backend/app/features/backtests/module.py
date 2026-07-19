from collections.abc import Callable
from datetime import datetime

from backend.app.bootstrap.feature_registry import FeatureModule
from backend.app.contracts.runs import RunKind, RunRef

from .router import build_router
from .jobs import BacktestJobHandler
from .repository import BacktestResultRepository
from .service import BacktestService


def build_backtests_feature(
    submit: Callable[[RunKind, dict[str, object], str | None, datetime], RunRef] | None = None,
    repository: BacktestResultRepository | None = None,
    service: BacktestService | None = None,
) -> FeatureModule:
    handlers = ((RunKind.BACKTEST, BacktestJobHandler(service)),) if service else ()
    return FeatureModule("backtests", build_router(submit, repository), handlers)
