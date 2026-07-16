from datetime import date, datetime
from decimal import Decimal

import pytest

from backend.app.features.backtests.execution import DailyBar, ExecutionSimulator
from backend.app.features.backtests.fees import RESEARCH_FEE_SCHEDULE, calculate_fee
from backend.app.features.backtests.ledger import Fill, PortfolioLedger
from backend.app.features.backtests.metrics import calculate_metrics
from backend.app.features.backtests.models import BacktestRequest, OrderIntent, OrderSide
from backend.app.features.backtests.walk_forward import HoldoutLock, HoldoutViolation


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
