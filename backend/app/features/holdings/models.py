from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from backend.app.contracts.grades import DataGrade, LlmGrade
from backend.app.core.portfolio.models import PositionOrigin, StrategyBook
from backend.app.core.strategy.reason_codes import ReasonCode


class AdviceAction(StrEnum):
    HOLD = "hold"
    EXIT_ALL = "exit_all"
    REDUCE_HALF = "reduce_half"
    TRIM_ONE_THIRD = "trim_one_third"
    RAISE_STOP = "raise_stop"
    ADD = "add"
    PENDING_EXIT = "pending_exit"
    MANUAL_REVIEW = "manual_review"


@dataclass(frozen=True, slots=True)
class HoldingFactors:
    p: Decimal
    f: Decimal
    r: Decimal
    t: Decimal
    v: Decimal
    s: Decimal
    percentile_rank: Decimal


@dataclass(frozen=True, slots=True)
class HoldingRiskSummary:
    equity: Decimal
    cash: Decimal
    gross_exposure_pct: Decimal
    portfolio_risk_pct: Decimal
    market_state: str


@dataclass(frozen=True, slots=True)
class HoldingAdviceItem:
    security_id: str
    security_name: str
    origin: PositionOrigin
    strategy_book: StrategyBook | None
    quantity: int
    available_to_sell: int
    average_cost: Decimal
    close: Decimal
    market_state: str
    factors: HoldingFactors
    r_multiple: Decimal | None
    effective_stop: Decimal | None
    proposed_effective_stop: Decimal | None
    advised_action: AdviceAction
    planned_quantity: int
    pending_target_action: AdviceAction | None
    reason_codes: tuple[ReasonCode, ...]
    quality_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HoldingAnalysisResult:
    run_id: str
    portfolio_id: str
    as_of_time: datetime
    strategy_version: str
    manifest_hash: str
    data_grade: DataGrade
    llm_grade: LlmGrade
    summary: HoldingRiskSummary
    items: tuple[HoldingAdviceItem, ...]

    @property
    def auto_trade_enabled(self) -> bool:
        return False

    @property
    def human_confirm_required(self) -> bool:
        return True
