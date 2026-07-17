from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from backend.app.core.market.pit_models import PointInTimeSnapshot
from backend.app.core.portfolio.models import PortfolioSnapshot
from backend.app.features.backtests.models import (
    BacktestExperimentResult,
    OrderIntent,
    StrategyGroup,
)
from backend.app.features.backtests.execution import FilledAttempt, RejectedAttempt


@dataclass(frozen=True)
class BacktestDecisionContext:
    as_of_time: datetime
    next_trade_date: date
    strategy_version: str
    group: StrategyGroup
    snapshot: PointInTimeSnapshot
    portfolio: PortfolioSnapshot
    candidate_states: Mapping[str, str]


@dataclass(frozen=True)
class BacktestDecision:
    intents: tuple[OrderIntent, ...]
    candidate_states: Mapping[str, str]


class BacktestDecisionPort(Protocol):
    def decide(self, context: BacktestDecisionContext) -> BacktestDecision: ...


class BacktestExecutionPort(Protocol):
    """Execute one intent at a simulated next-day open."""

    def execute(
        self, intent: OrderIntent, trade_date: date, available_to_sell: int
    ) -> FilledAttempt | RejectedAttempt: ...


class BacktestTradingDayPort(Protocol):
    def between(self, start_date: date, end_date: date) -> tuple[date, ...]: ...


class BacktestSnapshotPort(Protocol):
    def snapshot(self, *, as_of_time: datetime, scope: object) -> PointInTimeSnapshot: ...


class BacktestRepository(Protocol):
    def publish_result(self, result: BacktestExperimentResult) -> None: ...
