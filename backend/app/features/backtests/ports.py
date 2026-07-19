from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from backend.app.core.market.pit_models import PointInTimeSnapshot
from backend.app.core.portfolio.models import PortfolioSnapshot
from backend.app.features.backtests.execution import FilledAttempt, RejectedAttempt
from backend.app.features.backtests.models import (
    BacktestExperimentResult,
    OrderIntent,
    StrategyGroup,
)
from backend.app.ports.artifacts import ArtifactRepository

ALL_STRATEGY_FACTORS = frozenset({"P", "F", "R", "T", "V"})


@dataclass(frozen=True)
class BacktestDecisionContext:
    as_of_time: datetime
    next_trade_date: date
    strategy_version: str
    group: StrategyGroup
    snapshot: PointInTimeSnapshot
    portfolio: PortfolioSnapshot
    candidate_states: Mapping[str, str]
    factor_mask: frozenset[str] = ALL_STRATEGY_FACTORS


@dataclass(frozen=True)
class BacktestDecision:
    intents: tuple[OrderIntent, ...]
    candidate_states: Mapping[str, str]


class BacktestDecisionPort(Protocol):
    """Generate order intents without creating fills or mutating a portfolio ledger."""

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
    """Persist a structured experiment result and its artifact projections."""

    def publish_result(
        self,
        run_id: UUID,
        result: BacktestExperimentResult,
        artifacts: ArtifactRepository,
    ) -> None: ...
