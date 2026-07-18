from datetime import date, datetime
from decimal import Decimal

import pytest

from backend.app.features.backtests.execution import DailyBar, ExecutionSimulator, FilledAttempt
from backend.app.features.backtests.fees import RESEARCH_FEE_SCHEDULE, calculate_fee
from backend.app.features.backtests.ledger import Fill, PortfolioLedger
from backend.app.features.backtests.metrics import calculate_metrics
from backend.app.features.backtests.models import BacktestRequest, OrderIntent, OrderSide
from backend.app.features.backtests.walk_forward import HoldoutLock, HoldoutViolation
from backend.app.features.backtests.engine import BacktestEngine
from backend.app.features.backtests.ports import BacktestDecision, BacktestDecisionContext
from backend.app.features.backtests.models import StrategyGroup
from backend.app.core.market.pit_models import PointInTimeSnapshot, SnapshotQuality
from backend.app.contracts.grades import DataGrade


def intent(side: OrderSide = OrderSide.BUY, quantity: int = 1000) -> OrderIntent:
    return OrderIntent(
        order_id="o1",
        security_id="600000.SH",
        side=side,
        quantity=quantity,
        signal_date=date(2024, 1, 1),
        earliest_trade_date=date(2024, 1, 2),
        strategy_book="core",
        priority=100,
        signal_close=Decimal("10"),
    )


def test_request_forbids_result_fields_and_inverted_dates() -> None:
    req = BacktestRequest(
        strategy_version="v2.12",
        start_date=date(2020, 1, 1),
        end_date=date(2024, 1, 1),
        initial_cash=Decimal("100000"),
        groups=["A"],
    )
    assert req.with_group(req.groups[0]).groups == ["A"]
    with pytest.raises(ValueError):
        req.with_period(date(2024, 1, 1), date(2020, 1, 1))


def test_fee_schedule_and_ledger_costs() -> None:
    assert calculate_fee(RESEARCH_FEE_SCHEDULE, OrderSide.SELL, Decimal("10000")) == Decimal(
        "10.10"
    )
    ledger = PortfolioLedger.opening(Decimal("100000"))
    ledger.apply_fill(
        Fill(
            "f1",
            "600000.SH",
            OrderSide.BUY,
            1000,
            Decimal("10"),
            Decimal("5"),
            datetime(2024, 1, 2),
        )
    )
    assert ledger.state.positions["600000.SH"].average_cost == Decimal("10.005")
    ledger.apply_fill(
        Fill(
            "f2",
            "600000.SH",
            OrderSide.SELL,
            300,
            Decimal("12"),
            Decimal("8.60"),
            datetime(2024, 1, 3),
        )
    )
    assert ledger.state.positions["600000.SH"].quantity == 700


def test_execution_rejects_t_plus_one_and_rounds_buy_lot() -> None:
    sim = ExecutionSimulator()
    bar = DailyBar(
        date(2024, 1, 1), Decimal("10"), Decimal("10"), Decimal("9"), Decimal("9.5"), 1_000_000
    )
    rejected = sim.attempt(intent(), bar)
    assert rejected.reason_code == "T_PLUS_ONE"
    bar = DailyBar(
        date(2024, 1, 2), Decimal("10"), Decimal("10"), Decimal("9"), Decimal("9.5"), 500_000
    )
    result = sim.attempt(intent(quantity=1000), bar)
    assert result.quantity == 1000


def test_metrics_and_holdout_lock() -> None:
    metrics = calculate_metrics([Decimal("100"), Decimal("110"), Decimal("99")], Decimal("100"))
    assert metrics["max_drawdown"] == "0.1"
    with pytest.raises(HoldoutViolation):
        HoldoutLock(date(2024, 1, 1), date(2024, 12, 31)).assert_not_touched(
            date(2024, 6, 1), date(2024, 6, 2)
        )


def test_engine_executes_next_day_intent_and_publishes_trade_metrics() -> None:
    class Days:
        def between(self, start_date: date, end_date: date) -> tuple[date, ...]:
            return (date(2024, 1, 1), date(2024, 1, 2))

    class Warehouse:
        def snapshot(self, *, as_of_time: datetime, scope: object) -> PointInTimeSnapshot:
            return PointInTimeSnapshot(
                as_of_time, scope, DataGrade.RESEARCH, (), (), SnapshotQuality(()), (), "x"
            )

    class Decisions:
        def decide(self, context: BacktestDecisionContext) -> BacktestDecision:
            return BacktestDecision((intent(quantity=100),), {})

    class Execution:
        def execute(
            self, order: OrderIntent, trade_date: date, available_to_sell: int
        ) -> FilledAttempt:
            return FilledAttempt(
                order.order_id,
                trade_date,
                order.quantity,
                Decimal("10"),
                Decimal("10"),
                Decimal("1"),
                Decimal("0"),
            )

    request = BacktestRequest(
        strategy_version="v2.12",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 2),
        initial_cash=Decimal("10000"),
        groups=[StrategyGroup.A],
    )
    result = BacktestEngine(Days(), Warehouse(), Decisions(), Execution()).run(
        request, StrategyGroup.A
    )
    assert len(result.trades) == 1
    assert result.trades[0]["trade_date"] == "2024-01-02"
    assert result.metrics["observations"] == 2


def test_next_decision_receives_lots_from_prior_simulated_fill() -> None:
    class Days:
        def between(self, start_date: date, end_date: date) -> tuple[date, ...]:
            return (date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3))

    class Warehouse:
        def snapshot(self, *, as_of_time: datetime, scope: object) -> PointInTimeSnapshot:
            return PointInTimeSnapshot(
                as_of_time, scope, DataGrade.RESEARCH, (), (), SnapshotQuality(()), (), "x"
            )

    class Decisions:
        def __init__(self) -> None:
            self.contexts: list[BacktestDecisionContext] = []

        def decide(self, context: BacktestDecisionContext) -> BacktestDecision:
            self.contexts.append(context)
            intents = (intent(quantity=100),) if len(self.contexts) == 1 else ()
            return BacktestDecision(intents, {})

    class Execution:
        def execute(
            self, order: OrderIntent, trade_date: date, available_to_sell: int
        ) -> FilledAttempt:
            return FilledAttempt(
                order.order_id,
                trade_date,
                order.quantity,
                Decimal("10"),
                Decimal("10"),
                Decimal("1"),
                Decimal("0"),
            )

    decisions = Decisions()
    request = BacktestRequest(
        strategy_version="v2.12",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 3),
        initial_cash=Decimal("10000"),
        groups=[StrategyGroup.A],
    )

    BacktestEngine(Days(), Warehouse(), decisions, Execution()).run(request, StrategyGroup.A)

    portfolio = decisions.contexts[1].portfolio
    assert portfolio.version == 1
    assert portfolio.cash == Decimal("8999")
    assert portfolio.lots[0].security_id == "600000.SH"
    assert portfolio.lots[0].quantity == 100
    assert portfolio.lots[0].available_to_sell == 0
    assert portfolio.lots[0].average_cost == Decimal("10.01")
