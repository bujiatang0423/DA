from decimal import Decimal

from backend.app.core.portfolio.models import PortfolioPosition
from backend.app.core.strategy.types import SecurityEvaluation

from .models import HoldingAdviceItem, HoldingFactors
from .priority import PriorityFacts, decide_action


def project_position(
    position: PortfolioPosition, evaluation: SecurityEvaluation
) -> HoldingAdviceItem:
    factors = evaluation.factors
    if factors is None:
        factor_values = HoldingFactors(*(Decimal("0") for _ in range(7)))
    else:
        factor_values = HoldingFactors(
            Decimal(str(factors.p)),
            Decimal(str(factors.f)),
            Decimal(str(factors.r)),
            Decimal(str(factors.t)),
            Decimal(str(factors.v)),
            Decimal(str(factors.s)),
            Decimal(str(factors.percentile)),
        )
    facts = PriorityFacts(
        hard_stop_triggered=evaluation.hard_stop,
        market_or_portfolio_reduction_required=evaluation.market_reduction,
        swing_rank_exit=evaluation.rank_exit,
        core_rank_exit=evaluation.rank_exit,
        core_ma20_reduce=evaluation.book_exit,
        stop_raise_required=evaluation.stop_raise_required,
        available_to_sell=position.available_to_sell,
        quantity=position.quantity,
        proposed_effective_stop=position.effective_stop,
    )
    action, planned_quantity = decide_action(
        facts, strategy_book=position.strategy_book.value if position.strategy_book else None
    )
    reasons = tuple(evaluation.reasons)
    return HoldingAdviceItem(
        security_id=position.security_id,
        security_name=evaluation.name,
        origin=position.origin,
        strategy_book=position.strategy_book,
        quantity=position.quantity,
        available_to_sell=position.available_to_sell,
        average_cost=position.average_cost,
        close=Decimal(str(evaluation.close)),
        market_state=evaluation.market_state.value,
        factors=factor_values,
        r_multiple=Decimal(str(evaluation.r_multiple))
        if evaluation.r_multiple is not None
        else None,
        effective_stop=position.effective_stop,
        proposed_effective_stop=position.effective_stop,
        advised_action=action,
        planned_quantity=planned_quantity,
        pending_target_action=None,
        reason_codes=reasons,
        quality_codes=evaluation.quality_codes,
        evidence_refs=(),
    )
