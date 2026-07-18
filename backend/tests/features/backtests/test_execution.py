from datetime import date
from decimal import Decimal

import pytest

from backend.app.features.backtests.execution import (
    DailyBar,
    ExecutionSimulator,
    FilledAttempt,
    RejectedAttempt,
    stop_price,
)
from backend.app.features.backtests.models import OrderIntent, OrderSide


def _intent(
    *,
    side: OrderSide = OrderSide.BUY,
    quantity: int = 1_000,
    earliest_trade_date: date = date(2024, 1, 2),
    signal_close: Decimal = Decimal("10"),
    participation: Decimal = Decimal("0.002"),
) -> OrderIntent:
    return OrderIntent(
        order_id="attempt-1",
        security_id="600000.SH",
        side=side,
        quantity=quantity,
        signal_date=date(2024, 1, 1),
        earliest_trade_date=earliest_trade_date,
        strategy_book="core",
        priority=100,
        signal_close=signal_close,
        max_participation_rate=participation,
    )


def _bar(**changes: object) -> DailyBar:
    values: dict[str, object] = {
        "trade_date": date(2024, 1, 2),
        "open": Decimal("10"),
        "high": Decimal("10.3"),
        "low": Decimal("9.7"),
        "close": Decimal("10"),
        "volume": 100_000,
    }
    values.update(changes)
    return DailyBar(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("intent", "bar", "available_to_sell", "reason_code"),
    [
        (_intent(earliest_trade_date=date(2024, 1, 3)), _bar(), 0, "T_PLUS_ONE"),
        (_intent(), _bar(suspended=True), 0, "SUSPENDED"),
        (_intent(), _bar(limit_up=True), 0, "LIMIT_UP_LOCKED"),
        (_intent(side=OrderSide.SELL), _bar(limit_down=True), 1_000, "LIMIT_DOWN_LOCKED"),
        (_intent(), _bar(open=Decimal("10.31")), 0, "BUY_GAP_TOO_HIGH"),
    ],
)
def test_execution_records_every_rejected_attempt(
    intent: OrderIntent,
    bar: DailyBar,
    available_to_sell: int,
    reason_code: str,
) -> None:
    result = ExecutionSimulator().attempt(intent, bar, available_to_sell=available_to_sell)

    assert isinstance(result, RejectedAttempt)
    assert result.order_id == intent.order_id
    assert result.trade_date == bar.trade_date
    assert result.quantity == 0
    assert result.reason_code == reason_code
    assert result.fee_schedule_version == "research-cn-a-2023-08-28"


def test_execution_applies_participation_lot_rounding_slippage_and_fee_audit() -> None:
    result = ExecutionSimulator().attempt(_intent(), _bar(), available_to_sell=0)

    assert isinstance(result, FilledAttempt)
    assert result.quantity == 200
    assert result.theoretical_price == Decimal("10")
    assert result.actual_price == Decimal("10.010")
    assert result.slippage == Decimal("0.001")
    assert result.fee == Decimal("5.02")
    assert result.fee_schedule_version == "research-cn-a-2023-08-28"


def test_sell_respects_t_plus_one_but_can_fill_an_odd_lot() -> None:
    result = ExecutionSimulator().attempt(
        _intent(side=OrderSide.SELL, quantity=37),
        _bar(),
        available_to_sell=37,
    )

    assert isinstance(result, FilledAttempt)
    assert result.quantity == 37
    assert result.actual_price == Decimal("9.990")


def test_stop_model_uses_open_for_gap_and_stop_for_intraday_cross() -> None:
    slippage = Decimal("0.001")

    assert stop_price(_bar(open=Decimal("9.5")), Decimal("10"), slippage) == Decimal("9.4905")
    assert stop_price(_bar(low=Decimal("9.5")), Decimal("10"), slippage) == Decimal("9.990")


@pytest.mark.parametrize(
    ("bar", "expected_price"),
    [
        (_bar(open=Decimal("10.2"), low=Decimal("9.5")), Decimal("9.990")),
        (_bar(open=Decimal("9.5")), Decimal("9.4905")),
        (_bar(open=Decimal("10.2"), low=Decimal("10.1")), Decimal("10.1898")),
    ],
)
def test_sell_stop_attempt_uses_triggered_or_normal_open_price(
    bar: DailyBar,
    expected_price: Decimal,
) -> None:
    intent = _intent(side=OrderSide.SELL, quantity=100, signal_close=Decimal("10"))
    intent = intent.model_copy(update={"stop_price": Decimal("10")})

    result = ExecutionSimulator().attempt(intent, bar, available_to_sell=100)

    assert isinstance(result, FilledAttempt)
    assert result.actual_price == expected_price
