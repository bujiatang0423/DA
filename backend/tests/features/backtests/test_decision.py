from dataclasses import replace
from datetime import date

from backend.app.core.strategy.types import (
    ConstraintDecision,
    FactorScores,
    MarketRegimeDecision,
    PositionSizingDecision,
)
from backend.app.features.backtests.decision import MaskedV212BacktestDecisionPort
from backend.app.features.backtests.experiments import FACTOR_MASKS
from backend.app.features.backtests.models import StrategyGroup
from backend.app.features.backtests.ports import BacktestDecisionContext
from backend.tests.features.holdings.factories import (
    point_in_time_snapshot,
    portfolio_snapshot,
    security_evaluation,
    strategy_evaluation,
)


class RecordingInputBuilder:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def build(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return object()


class FixedStrategy:
    def __init__(self, evaluation: object) -> None:
        self._evaluation = evaluation
        self.calls: list[object] = []

    def evaluate(self, request: object) -> object:
        self.calls.append(request)
        return self._evaluation


def test_factor_mask_changes_the_v212_backtest_candidate_order() -> None:
    snapshot = point_in_time_snapshot()
    portfolio = portfolio_snapshot(snapshot.as_of_time)
    evaluation = strategy_evaluation(
        snapshot.as_of_time,
        securities=(
            replace(
                security_evaluation(),
                held=False,
                factors=FactorScores(100, 100, 0, 0, 0, 40, 0),
                sizing=PositionSizingDecision(100, 9.5, 1.0, 1000, 100),
                constraint=ConstraintDecision(True, ()),
            ),
        ),
    )
    evaluation = replace(
        evaluation,
        market=MarketRegimeDecision(
            evaluation.market.state,
            evaluation.market.max_exposure,
            True,
            evaluation.market.allow_swing,
            evaluation.market.confidence,
            evaluation.market.week_cooldown_remaining,
            evaluation.market.month_cooldown_remaining,
            evaluation.market.reasons,
        ),
    )
    input_builder = RecordingInputBuilder()
    strategy = FixedStrategy(evaluation)
    port = MaskedV212BacktestDecisionPort(input_builder, strategy, minimum_score=30)
    base = BacktestDecisionContext(
        as_of_time=snapshot.as_of_time,
        next_trade_date=date(2026, 7, 20),
        strategy_version="v2.12",
        group=StrategyGroup.A,
        snapshot=snapshot,
        portfolio=portfolio,
        candidate_states={},
        factor_mask=FACTOR_MASKS[StrategyGroup.A],
    )

    group_a = port.decide(base)
    group_d = port.decide(
        replace(base, group=StrategyGroup.D, factor_mask=FACTOR_MASKS[StrategyGroup.D])
    )

    assert group_a.intents == ()
    assert len(group_d.intents) == 1
    assert group_d.intents[0].security_id == "000001.SZ"
    assert group_d.intents[0].earliest_trade_date == date(2026, 7, 20)
    assert len(input_builder.calls) == 2
    assert len(strategy.calls) == 2
