from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from backend.app.core.market.pit_models import SnapshotScope
from backend.app.core.market.strategy_inputs import StrategyInputBuilder
from backend.app.core.portfolio.models import PortfolioSnapshot
from backend.app.core.strategy.service import V212StrategyEngine
from backend.app.ports.point_in_time import PointInTimeWarehouse
from backend.app.ports.portfolio import PortfolioReader
from .models import (
    HoldingAnalysisResult,
    HoldingFactors,
    HoldingRiskSummary,
    AdviceAction,
    HoldingAdviceItem,
)
from .quality import llm_grade_from_manifest
from .repository import HoldingResultRepository
from .strategy_projection import project_position


@dataclass(frozen=True)
class HoldingAnalysisCommand:
    run_id: str
    portfolio_id: str
    as_of_time: datetime


class V212HoldingAnalysisService:
    def __init__(
        self,
        warehouse: PointInTimeWarehouse,
        portfolios: PortfolioReader,
        builder: StrategyInputBuilder,
        strategy: V212StrategyEngine,
        repository: HoldingResultRepository,
    ) -> None:
        self._warehouse, self._portfolios, self._builder, self._strategy, self._repository = (
            warehouse,
            portfolios,
            builder,
            strategy,
            repository,
        )

    def run(self, command: HoldingAnalysisCommand) -> HoldingAnalysisResult:
        snapshot = self._warehouse.snapshot(
            as_of_time=command.as_of_time, scope=SnapshotScope.holding_analysis(())
        )
        portfolio: PortfolioSnapshot = self._portfolios.snapshot(
            portfolio_id=command.portfolio_id, as_of_time=command.as_of_time
        )
        quality_codes = tuple(issue.code for issue in snapshot.quality.issues)
        if snapshot.quality.has_errors:
            items = tuple(
                HoldingAdviceItem(
                    security_id=position.security_id,
                    security_name=position.security_id,
                    origin=position.origin,
                    strategy_book=position.strategy_book,
                    quantity=position.quantity,
                    available_to_sell=position.available_to_sell,
                    average_cost=position.average_cost,
                    close=Decimal("0"),
                    market_state="weak",
                    factors=HoldingFactors(*(Decimal("0") for _ in range(7))),
                    r_multiple=None,
                    effective_stop=position.effective_stop,
                    proposed_effective_stop=position.effective_stop,
                    advised_action=AdviceAction.MANUAL_REVIEW,
                    planned_quantity=0,
                    pending_target_action=None,
                    reason_codes=(),
                    quality_codes=quality_codes,
                    evidence_refs=(),
                )
                for position in portfolio.positions
            )
            manifest_hash = snapshot.manifest_hash
            grade = snapshot.data_grade
            llm_grade = llm_grade_from_manifest(None)
            market_state = "weak"
        else:
            prepared = self._builder.build(
                snapshot=snapshot, portfolio=portfolio, strategy_version="v2.12"
            )
            evaluation = self._strategy.evaluate(prepared)
            by_id = {item.security_id: item for item in evaluation.securities}
            items = tuple(
                project_position(position, by_id[position.security_id])
                for position in portfolio.positions
                if position.security_id in by_id
            )
            manifest_hash, grade, llm_grade, market_state = (
                snapshot.manifest_hash,
                snapshot.data_grade,
                llm_grade_from_manifest(None),
                evaluation.market.state.value,
            )
        result = HoldingAnalysisResult(
            run_id=command.run_id,
            portfolio_id=command.portfolio_id,
            as_of_time=command.as_of_time,
            strategy_version="v2.12",
            manifest_hash=manifest_hash,
            data_grade=grade,
            llm_grade=llm_grade,
            summary=HoldingRiskSummary(
                portfolio.equity, portfolio.cash, Decimal("0"), Decimal("0"), market_state
            ),
            items=items,
        )
        self._repository.save(result)
        return result
