from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from backend.app.contracts.strategy import AsOf, StrategyVersion
from .reason_codes import ReasonCode


class MarketState(StrEnum):
    STRONG = "strong"
    NEUTRAL = "neutral"
    WEAK = "weak"


class LedgerKind(StrEnum):
    CORE = "core"
    SWING = "swing"


class PolicyStage(StrEnum):
    PLANNING = "planning"
    PILOT = "pilot"
    EXECUTION = "execution"
    MATURE = "mature"
    EXIT = "exit"


class FinancialLight(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


@dataclass(frozen=True)
class MarketRegimeInput:
    index_close: float
    index_ma20: float
    index_ma20_5d_ago: float
    index_ma60: float
    breadth: float
    index_return_1d: float
    index_return_20d: float
    limit_down_count: int
    portfolio_open_drawdown: float
    portfolio_week_drawdown: float
    portfolio_month_drawdown: float
    week_cooldown_remaining: int
    month_cooldown_remaining: int
    cooldown_recovery_confirmed: bool
    current_state: MarketState
    candidate_streak: int
    low_confidence: bool


@dataclass(frozen=True)
class MarketRegimeDecision:
    state: MarketState
    max_exposure: float
    allow_new_risk: bool
    allow_swing: bool
    confidence: str
    week_cooldown_remaining: int
    month_cooldown_remaining: int
    reasons: tuple[ReasonCode, ...] = ()


@dataclass(frozen=True)
class PortfolioView:
    net_equity: float
    gross_exposure: float
    portfolio_risk: float
    position_count: int
    industry_weights: dict[str, float] = field(default_factory=dict)
    theme_weights: dict[str, float] = field(default_factory=dict)
    ledger_weights: dict[LedgerKind, float] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyEvidence:
    strength: float
    relevance: float
    age_days: int
    stage: PolicyStage
    evidence_confidence: float
    data_completeness: float


@dataclass(frozen=True)
class FactorScores:
    p: float
    f: float
    r: float
    t: float
    v: float
    s: float
    percentile: float


@dataclass(frozen=True)
class PositionSizingInput:
    net_equity: float
    planned_price: float
    pullback_low: float
    atr14: float
    average_turnover20: float
    ledger: LedgerKind


@dataclass(frozen=True)
class PositionSizingDecision:
    quantity: int
    initial_stop: float
    stop_distance: float
    notional: float
    order_risk: float
    reasons: tuple[ReasonCode, ...] = ()


@dataclass(frozen=True)
class ConstraintInput:
    portfolio: PortfolioView
    market_max_exposure: float
    ledger: LedgerKind
    industry: str
    theme: str | None
    order_notional: float
    order_risk: float
    is_broad_etf: bool


@dataclass(frozen=True)
class ConstraintDecision:
    allowed: bool
    reasons: tuple[ReasonCode, ...]


@dataclass(frozen=True)
class SecurityEvaluationInput:
    security_id: str
    name: str
    industry: str
    theme: str | None
    ledger: LedgerKind
    policy_evidence: tuple[PolicyEvidence, ...]
    financial_numeric_score: float
    financial_text_score: float
    financial_light: FinancialLight
    policy_direction: str
    rs20_percentile: float
    rs60_percentile: float
    industry_proxy: bool
    above_ma20: bool
    above_ma60: bool
    rising_ma20: bool
    breakout_or_valid_pullback: bool
    ma20_atr_distance: float
    breakout_volume_percentile: float
    obv_slope_percentile: float
    turnover_percentile: float
    planned_price: float
    close: float
    ma20: float
    ma60: float
    pullback_low: float
    atr14: float
    average_turnover20: float
    hard_filter_passed: bool
    policy_sources_available: bool
    llm_factor_valid: bool
    breakout_confirmed: bool
    pullback_confirmed: bool
    strengthened_confirmed: bool
    days_since_breakout: int
    held: bool
    r_multiple: float | None
    rank_percentile: float
    red_light: bool
    hard_stop: bool
    market_reduction: bool
    book_exit: bool
    rank_exit: bool
    stop_raise_required: bool
    quality_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class StrategyEvaluationRequest:
    as_of: AsOf
    strategy: StrategyVersion
    manifest_hash: str
    market: MarketRegimeInput
    portfolio: PortfolioView
    securities: tuple[SecurityEvaluationInput, ...]


@dataclass(frozen=True)
class SecurityEvaluation:
    security_id: str
    name: str
    industry: str
    theme: str | None
    factors: FactorScores | None
    market_state: MarketState
    hard_filter_passed: bool
    policy_sources_available: bool
    llm_factor_valid: bool
    financial_light: FinancialLight
    policy_direction: str
    breakout_confirmed: bool
    pullback_confirmed: bool
    strengthened_confirmed: bool
    days_since_breakout: int
    held: bool
    close: float
    ma20: float
    ma60: float
    atr14: float
    r_multiple: float | None
    rank_percentile: float
    red_light: bool
    hard_stop: bool
    market_reduction: bool
    book_exit: bool
    rank_exit: bool
    stop_raise_required: bool
    sizing: PositionSizingDecision | None
    constraint: ConstraintDecision
    quality_codes: tuple[str, ...]
    reasons: tuple[ReasonCode, ...]


@dataclass(frozen=True)
class StrategyEvaluation:
    as_of_time: datetime
    strategy_version: str
    manifest_hash: str
    market: MarketRegimeDecision
    securities: tuple[SecurityEvaluation, ...]
