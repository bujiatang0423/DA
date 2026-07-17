from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from backend.app.core.market.pit_models import DataKind, SnapshotScope
from backend.app.core.market.strategy_inputs import StrategyInputBuilder
from backend.app.core.portfolio.models import PortfolioSnapshot
from backend.app.core.strategy.service import V212StrategyEngine
from backend.app.core.strategy.types import (
    MarketRegimeDecision,
    MarketState,
    PortfolioView,
    StrategyEvaluation,
)
from backend.app.ports.point_in_time import PointInTimeWarehouse
from backend.app.ports.portfolio import PortfolioReader
from .models import CandidateRecommendationResult
from .quality import derive_llm_grade
from .repository import CandidateRepository
from .strategy_projection import project_security


@dataclass(frozen=True, slots=True)
class CandidateRecommendationCommand:
    run_id: str
    portfolio_id: str
    as_of_time: datetime
    strategy_version: Literal["v2.12"] = "v2.12"


class CandidateService:
    def __init__(
        self,
        warehouse: PointInTimeWarehouse,
        portfolios: PortfolioReader,
        input_builder: StrategyInputBuilder,
        strategy: V212StrategyEngine,
        repository: CandidateRepository,
    ) -> None:
        self._warehouse = warehouse
        self._portfolios = portfolios
        self._input_builder = input_builder
        self._strategy = strategy
        self._repository = repository

    @property
    def repository(self) -> CandidateRepository:
        return self._repository

    def run(self, command: CandidateRecommendationCommand) -> CandidateRecommendationResult:
        snapshot = self._warehouse.snapshot(
            as_of_time=command.as_of_time, scope=SnapshotScope.candidate_recommendation()
        )
        if snapshot.as_of_time != command.as_of_time:
            raise ValueError("point-in-time mismatch")
        portfolio: PortfolioSnapshot = self._portfolios.snapshot(
            portfolio_id=command.portfolio_id, as_of_time=command.as_of_time
        )
        if snapshot.quality.has_errors:
            evaluation = StrategyEvaluation(
                as_of_time=command.as_of_time,
                strategy_version=command.strategy_version,
                manifest_hash=snapshot.manifest_hash,
                market=MarketRegimeDecision(MarketState.WEAK, 0.0, False, False, "low", 0, 0, ()),
                portfolio_summary=PortfolioView(
                    net_equity=float(portfolio.equity),
                    gross_exposure=0.0,
                    portfolio_risk=0.0,
                    position_count=len(portfolio.positions),
                ),
                securities=(),
            )
        else:
            prepared = self._input_builder.build(
                snapshot=snapshot, portfolio=portfolio, strategy_version=command.strategy_version
            )
            evaluation = self._strategy.evaluate(prepared)
        llm_manifest = _llm_manifest(snapshot)
        llm_grade, llm_quality = derive_llm_grade(llm_manifest)
        items = tuple(
            sorted(
                (project_security(item) for item in evaluation.securities),
                key=lambda item: (
                    item.bucket.value,
                    item.factors.percentile_rank,
                    item.security_id,
                ),
            )
        )
        result = CandidateRecommendationResult(
            run_id=command.run_id,
            as_of_time=command.as_of_time,
            strategy_version=command.strategy_version,
            manifest_hash=snapshot.manifest_hash,
            data_grade=snapshot.data_grade,
            llm_grade=llm_grade,
            market_state=evaluation.market.state.value,
            market_confidence=evaluation.market.confidence,
            quality_codes=tuple(issue.code for issue in snapshot.quality.issues) + llm_quality,
            items=items,
        )
        self._repository.save(result)
        return result


def _llm_manifest(snapshot: object) -> dict[str, object] | None:
    records = getattr(snapshot, "market_inputs", ())
    llm = [record for record in records if record.kind is DataKind.LLM_FACTOR]
    if not llm:
        return None
    return {"grade": "reconstructed", "valid": True}
