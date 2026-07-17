from dataclasses import dataclass
from decimal import Decimal

from .models import AdviceAction


@dataclass(frozen=True, slots=True)
class PriorityFacts:
    hard_stop_triggered: bool = False
    effective_stop_triggered: bool = False
    delisting_or_major_violation: bool = False
    market_or_portfolio_reduction_required: bool = False
    swing_time_stop: bool = False
    swing_two_r_trim: bool = False
    swing_trailing_stop: bool = False
    swing_rank_exit: bool = False
    core_ma20_reduce: bool = False
    core_ma60_exit: bool = False
    core_rank_exit: bool = False
    core_trailing_stop: bool = False
    add_signal_confirmed: bool = False
    profit_at_least_one_r: bool = False
    score_not_below_entry: bool = False
    raised_stop_risk_not_higher: bool = False
    stop_raise_required: bool = False
    proposed_effective_stop: Decimal | None = None
    available_to_sell: int = 0
    quantity: int = 0


def decide_action(facts: PriorityFacts, *, strategy_book: str | None) -> tuple[AdviceAction, int]:
    if facts.delisting_or_major_violation or facts.hard_stop_triggered:
        return AdviceAction.EXIT_ALL, facts.available_to_sell
    if facts.effective_stop_triggered:
        return AdviceAction.EXIT_ALL, facts.available_to_sell
    if facts.market_or_portfolio_reduction_required:
        return AdviceAction.REDUCE_HALF, min(facts.available_to_sell, facts.quantity // 2)
    if strategy_book == "swing" and (facts.swing_time_stop or facts.swing_trailing_stop):
        return AdviceAction.EXIT_ALL, facts.available_to_sell
    if strategy_book == "swing" and facts.swing_two_r_trim:
        return AdviceAction.TRIM_ONE_THIRD, min(facts.available_to_sell, facts.quantity // 3)
    if strategy_book == "core" and facts.core_ma60_exit:
        return AdviceAction.EXIT_ALL, facts.available_to_sell
    if strategy_book == "core" and (facts.core_ma20_reduce or facts.core_trailing_stop):
        return AdviceAction.REDUCE_HALF, min(facts.available_to_sell, facts.quantity // 2)
    if facts.stop_raise_required and facts.raised_stop_risk_not_higher:
        return AdviceAction.RAISE_STOP, 0
    if facts.add_signal_confirmed and facts.profit_at_least_one_r and facts.score_not_below_entry:
        return AdviceAction.ADD, 0
    return AdviceAction.HOLD, 0
