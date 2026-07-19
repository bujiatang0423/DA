from __future__ import annotations

from dataclasses import dataclass, replace

from backend.app.core.market.strategy_inputs import StrategyInputBuilder
from backend.app.core.strategy.service import V212StrategyEngine
from backend.app.core.strategy.types import (
    FactorScores,
    FinancialLight,
    PolicyEvidence,
    PolicyStage,
    SecurityEvaluation,
    StrategyEvaluationRequest,
)

from .models import OrderIntent, OrderSide
from .ports import BacktestDecision, BacktestDecisionContext


FACTOR_WEIGHTS: dict[str, float] = {
    "P": 0.20,
    "F": 0.20,
    "R": 0.25,
    "T": 0.20,
    "V": 0.15,
}


@dataclass(frozen=True)
class MaskedV212BacktestDecisionPort:
    """Adapt V2.12 strategy evaluation to factor-isolated backtest order intents."""

    input_builder: StrategyInputBuilder
    strategy: V212StrategyEngine
    minimum_score: float = 60.0

    def decide(self, context: BacktestDecisionContext) -> BacktestDecision:
        prepared = self.input_builder.build(
            snapshot=context.snapshot,
            portfolio=context.portfolio,
            strategy_version=context.strategy_version,
        )
        evaluation = self.strategy.evaluate(_masked_request(prepared, context.factor_mask))
        intents = tuple(
            intent
            for security in evaluation.securities
            if (
                intent := _order_intent(
                    security,
                    context,
                    evaluation.market.allow_new_risk,
                    self.minimum_score,
                )
            )
            is not None
        )
        states = dict(context.candidate_states)
        states.update({intent.security_id: "selected" for intent in intents})
        return BacktestDecision(intents, states)


def _masked_request(
    request: object,
    factor_mask: frozenset[str],
) -> object:
    if not isinstance(request, StrategyEvaluationRequest):
        return request
    securities = tuple(_mask_security_input(item, factor_mask) for item in request.securities)
    return replace(request, securities=securities)


def _mask_security_input(
    security: object,
    factor_mask: frozenset[str],
) -> object:
    if "P" not in factor_mask:
        security = replace(
            security,
            policy_evidence=(_neutral_policy_evidence(),),
            policy_sources_available=True,
        )
    if "F" not in factor_mask:
        security = replace(
            security,
            financial_numeric_score=50.0,
            financial_text_score=50.0,
            financial_light=FinancialLight.GREEN,
            llm_factor_valid=True,
        )
    return security


def _neutral_policy_evidence() -> PolicyEvidence:
    return PolicyEvidence(
        strength=50.0,
        relevance=100.0,
        age_days=0,
        stage=PolicyStage.EXECUTION,
        evidence_confidence=1.0,
        data_completeness=1.0,
    )


def _order_intent(
    security: SecurityEvaluation,
    context: BacktestDecisionContext,
    allow_new_risk: bool,
    minimum_score: float,
) -> OrderIntent | None:
    if (
        security.held
        or security.factors is None
        or security.sizing is None
        or not security.constraint.allowed
        or not allow_new_risk
        or _masked_score(security.factors, context.factor_mask) < minimum_score
    ):
        return None
    return OrderIntent(
        order_id=f"{context.as_of_time.isoformat()}:{context.group.value}:{security.security_id}",
        security_id=security.security_id,
        side=OrderSide.BUY,
        quantity=security.sizing.quantity,
        signal_date=context.as_of_time.date(),
        earliest_trade_date=context.next_trade_date,
        strategy_book="core",
        priority=100,
        signal_close=security.close,
        stop_price=security.sizing.initial_stop,
    )


def _masked_score(factors: FactorScores, factor_mask: frozenset[str]) -> float:
    selected_weight = sum(FACTOR_WEIGHTS[name] for name in factor_mask)
    if selected_weight == 0:
        raise ValueError("factor mask cannot be empty")
    values = {
        "P": factors.p,
        "F": factors.f,
        "R": factors.r,
        "T": factors.t,
        "V": factors.v,
    }
    return sum(FACTOR_WEIGHTS[name] * values[name] for name in factor_mask) / selected_weight
