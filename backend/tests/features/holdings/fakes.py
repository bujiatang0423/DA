from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace

from backend.app.core.market.pit_models import PointInTimeSnapshot, SnapshotScope
from backend.app.core.portfolio.models import PortfolioSnapshot
from backend.app.core.strategy.types import PortfolioView, StrategyEvaluation
from backend.app.features.holdings.models import HoldingAnalysisResult


@dataclass
class FakeHoldingAnalysisRepository:
    saved: list[HoldingAnalysisResult] = field(default_factory=list)

    def save(self, result: HoldingAnalysisResult) -> None:
        self.saved.append(result)

    def get(self, run_id: str) -> HoldingAnalysisResult | None:
        return next((result for result in self.saved if result.run_id == run_id), None)

    def latest(self, portfolio_id: str) -> HoldingAnalysisResult | None:
        matches = [result for result in self.saved if result.portfolio_id == portfolio_id]
        return max(matches, key=lambda result: (result.as_of_time, result.run_id), default=None)


@dataclass
class FakePointInTimeWarehouse:
    snapshot_value: PointInTimeSnapshot
    requests: list[tuple[datetime, SnapshotScope]] = field(default_factory=list)

    def snapshot(self, *, as_of_time: datetime, scope: SnapshotScope) -> PointInTimeSnapshot:
        self.requests.append((as_of_time, scope))
        return self.snapshot_value


@dataclass
class FakePortfolioReader:
    snapshot_value: PortfolioSnapshot
    requests: list[tuple[str, datetime]] = field(default_factory=list)

    def snapshot(self, *, portfolio_id: str, as_of_time: datetime) -> PortfolioSnapshot:
        self.requests.append((portfolio_id, as_of_time))
        return self.snapshot_value


@dataclass
class FakeStrategyInputBuilder:
    prepared_value: object
    error: Exception | None = None
    requests: list[tuple[PointInTimeSnapshot, PortfolioSnapshot, str]] = field(default_factory=list)

    @classmethod
    def for_context(
        cls,
        snapshot: PointInTimeSnapshot,
        portfolio: PortfolioSnapshot,
    ) -> "FakeStrategyInputBuilder":
        prepared = SimpleNamespace(
            as_of=SimpleNamespace(as_of_time=snapshot.as_of_time),
            strategy=SimpleNamespace(version="v2.12"),
            manifest_hash=snapshot.manifest_hash,
            portfolio=PortfolioView(
                net_equity=float(portfolio.equity),
                gross_exposure=0.65,
                portfolio_risk=0.0125,
                position_count=len(portfolio.positions),
            ),
        )
        return cls(prepared)

    def build(
        self,
        *,
        snapshot: PointInTimeSnapshot,
        portfolio: PortfolioSnapshot,
        strategy_version: str,
    ) -> object:
        self.requests.append((snapshot, portfolio, strategy_version))
        if self.error is not None:
            raise self.error
        return self.prepared_value


@dataclass
class FakeStrategyDecisionPort:
    evaluation: StrategyEvaluation
    requests: list[object] = field(default_factory=list)

    def evaluate(self, request: object) -> StrategyEvaluation:
        self.requests.append(request)
        return self.evaluation
