from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from backend.app.core.market.pit_models import PointInTimeSnapshot, SnapshotScope
from backend.app.core.market.strategy_inputs import StrategyInputBuilder, StrategyInputError
from backend.app.core.portfolio.models import PortfolioSnapshot
from backend.app.core.strategy.types import StrategyEvaluation, StrategyEvaluationRequest
from backend.app.ports.point_in_time import PointInTimeWarehouse
from backend.app.ports.portfolio import PortfolioReader
from backend.app.ports.strategy import StrategyDecisionPort

from .models import HoldingAnalysisResult, HoldingRiskSummary
from .quality import llm_grade_from_snapshot
from .repository import HoldingAnalysisRepository
from .strategy_projection import project_position


class HoldingAnalysisInvariantError(RuntimeError):
    code = "HOLDING_ANALYSIS_INVARIANT_VIOLATION"


class HoldingMarketDataMissing(RuntimeError):
    code = "HOLDING_MARKET_DATA_MISSING"


@dataclass(frozen=True, slots=True)
class HoldingAnalysisCommand:
    run_id: str
    portfolio_id: str
    as_of_time: datetime
    strategy_version: Literal["v2.12"] = "v2.12"


class HoldingAnalysisService:
    def __init__(
        self,
        warehouse: PointInTimeWarehouse,
        portfolios: PortfolioReader,
        builder: StrategyInputBuilder,
        strategy: StrategyDecisionPort,
        repository: HoldingAnalysisRepository,
    ) -> None:
        self._warehouse = warehouse
        self._portfolios = portfolios
        self._builder = builder
        self._strategy = strategy
        self._repository = repository

    def run(self, command: HoldingAnalysisCommand) -> HoldingAnalysisResult:
        if command.as_of_time.tzinfo is None or command.as_of_time.utcoffset() is None:
            raise HoldingAnalysisInvariantError("holding as_of_time must be timezone-aware")

        portfolio = self._portfolios.snapshot(
            portfolio_id=command.portfolio_id,
            as_of_time=command.as_of_time,
        )
        security_ids = tuple(sorted({position.security_id for position in portfolio.positions}))
        snapshot = self._warehouse.snapshot(
            as_of_time=command.as_of_time,
            scope=SnapshotScope.holding_analysis(security_ids),
        )
        self._validate_inputs(command, portfolio, snapshot)
        if snapshot.quality.has_errors:
            raise HoldingMarketDataMissing(self._missing_data_detail(snapshot))

        try:
            prepared = self._builder.build(
                snapshot=snapshot,
                portfolio=portfolio,
                strategy_version=command.strategy_version,
            )
        except StrategyInputError as exc:
            raise HoldingMarketDataMissing(
                f"{HoldingMarketDataMissing.code}: strategy inputs unavailable"
            ) from exc
        evaluation = self._strategy.evaluate(prepared)
        self._validate_evaluation(command, snapshot, prepared, evaluation)

        evaluations_by_security = {item.security_id: item for item in evaluation.securities}
        missing = tuple(sid for sid in security_ids if sid not in evaluations_by_security)
        if missing:
            raise HoldingMarketDataMissing(
                f"{HoldingMarketDataMissing.code}: missing evaluations for {','.join(missing)}"
            )
        items = tuple(
            project_position(position, evaluations_by_security[position.security_id])
            for position in portfolio.positions
        )
        portfolio_view = prepared.portfolio
        result = HoldingAnalysisResult(
            run_id=command.run_id,
            portfolio_id=command.portfolio_id,
            as_of_time=command.as_of_time,
            strategy_version=command.strategy_version,
            manifest_hash=snapshot.manifest_hash,
            data_grade=snapshot.data_grade,
            llm_grade=llm_grade_from_snapshot(snapshot),
            summary=HoldingRiskSummary(
                equity=portfolio.equity,
                cash=portfolio.cash,
                gross_exposure_pct=Decimal(str(portfolio_view.gross_exposure * 100)),
                portfolio_risk_pct=Decimal(str(portfolio_view.portfolio_risk * 100)),
                market_state=evaluation.market.state.value,
            ),
            items=items,
        )
        self._repository.save(result)
        return result

    @staticmethod
    def _validate_inputs(
        command: HoldingAnalysisCommand,
        portfolio: PortfolioSnapshot,
        snapshot: PointInTimeSnapshot,
    ) -> None:
        if portfolio.as_of_time != command.as_of_time:
            raise HoldingAnalysisInvariantError("portfolio decision time mismatch")
        if snapshot.as_of_time != command.as_of_time:
            raise HoldingAnalysisInvariantError("point-in-time snapshot mismatch")

    @staticmethod
    def _validate_evaluation(
        command: HoldingAnalysisCommand,
        snapshot: PointInTimeSnapshot,
        prepared: StrategyEvaluationRequest,
        evaluation: StrategyEvaluation,
    ) -> None:
        prepared_as_of = getattr(getattr(prepared, "as_of", None), "as_of_time", None)
        prepared_strategy = getattr(getattr(prepared, "strategy", None), "version", None)
        prepared_manifest = getattr(prepared, "manifest_hash", None)
        if prepared_as_of != command.as_of_time or evaluation.as_of_time != command.as_of_time:
            raise HoldingAnalysisInvariantError("strategy decision time mismatch")
        if prepared_strategy != command.strategy_version:
            raise HoldingAnalysisInvariantError("prepared strategy version mismatch")
        if evaluation.strategy_version != command.strategy_version:
            raise HoldingAnalysisInvariantError("evaluation strategy version mismatch")
        if prepared_manifest != snapshot.manifest_hash:
            raise HoldingAnalysisInvariantError("prepared manifest mismatch")
        if evaluation.manifest_hash != snapshot.manifest_hash:
            raise HoldingAnalysisInvariantError("evaluation manifest mismatch")

    @staticmethod
    def _missing_data_detail(snapshot: PointInTimeSnapshot) -> str:
        codes = ",".join(sorted({issue.code for issue in snapshot.quality.issues}))
        return f"{HoldingMarketDataMissing.code}: {codes or 'snapshot quality error'}"


V212HoldingAnalysisService = HoldingAnalysisService
