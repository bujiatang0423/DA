from datetime import datetime
from decimal import Decimal

import pytest

from backend.app.features.backtests.ledger import Fill, PortfolioLedger
from backend.app.features.backtests.models import OrderSide


def fill(
    fill_id: str,
    side: OrderSide,
    quantity: int,
    price: str,
    fee: str = "0",
    filled_at: datetime = datetime(2024, 1, 2, 10),
) -> Fill:
    return Fill(
        fill_id=fill_id,
        security_id="600000.SH",
        side=side,
        quantity=quantity,
        price=Decimal(price),
        fee=Decimal(fee),
        filled_at=filled_at,
    )


def test_multiple_buys_are_retained_as_individual_cost_basis_lots() -> None:
    ledger = PortfolioLedger.opening(Decimal("100000"))
    ledger.apply_fill(fill("buy-1", OrderSide.BUY, 100, "10", "5"))
    ledger.apply_fill(fill("buy-2", OrderSide.BUY, 100, "12", "3", datetime(2024, 1, 3, 10)))

    lots = ledger.to_portfolio_snapshot(datetime(2024, 1, 4, 15, 30)).lots
    assert [(lot.lot_id, lot.quantity, lot.average_cost) for lot in lots] == [
        ("sim-buy-1", 100, Decimal("10.05")),
        ("sim-buy-2", 100, Decimal("12.03")),
    ]


def test_partial_sale_uses_fifo_and_preserves_remaining_lot_cost_basis() -> None:
    ledger = PortfolioLedger.opening(Decimal("100000"))
    ledger.apply_fill(fill("buy-1", OrderSide.BUY, 100, "10", "5"))
    ledger.apply_fill(fill("buy-2", OrderSide.BUY, 100, "12", "3", datetime(2024, 1, 3, 10)))
    ledger.apply_fill(fill("sell-1", OrderSide.SELL, 150, "15", "6", datetime(2024, 1, 4, 10)))

    lots = ledger.to_portfolio_snapshot(datetime(2024, 1, 5, 15, 30)).lots
    assert [(lot.lot_id, lot.quantity, lot.average_cost) for lot in lots] == [
        ("sim-buy-2", 50, Decimal("12.03")),
    ]
    assert ledger.state.realized_pnl == Decimal("637.5")


def test_full_fifo_sale_removes_consumed_lots() -> None:
    ledger = PortfolioLedger.opening(Decimal("100000"))
    ledger.apply_fill(fill("buy-1", OrderSide.BUY, 100, "10"))
    ledger.apply_fill(fill("buy-2", OrderSide.BUY, 100, "12", filled_at=datetime(2024, 1, 3, 10)))
    ledger.apply_fill(fill("sell-1", OrderSide.SELL, 200, "15", filled_at=datetime(2024, 1, 4, 10)))

    assert ledger.to_portfolio_snapshot(datetime(2024, 1, 5, 15, 30)).lots == ()
    assert "600000.SH" not in ledger.state.positions


def test_duplicate_fill_is_rejected_without_mutating_ledger() -> None:
    ledger = PortfolioLedger.opening(Decimal("100000"))
    buy = fill("buy-1", OrderSide.BUY, 100, "10")
    ledger.apply_fill(buy)

    with pytest.raises(ValueError, match="duplicate fill"):
        ledger.apply_fill(buy)

    assert ledger.state.cash == Decimal("99000")
    assert ledger.state.version == 1


@pytest.mark.parametrize(
    "ledger, attempted_fill, message",
    [
        (
            PortfolioLedger.opening(Decimal("100")),
            fill("buy-1", OrderSide.BUY, 11, "10"),
            "negative cash",
        ),
        (
            PortfolioLedger.opening(Decimal("100000")),
            fill("sell-1", OrderSide.SELL, 1, "10"),
            "oversell",
        ),
    ],
)
def test_invalid_cash_or_sell_quantity_is_rejected(
    ledger: PortfolioLedger, attempted_fill: Fill, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        ledger.apply_fill(attempted_fill)

    assert ledger.state.version == 0


def test_snapshot_keeps_buy_day_lot_unavailable_until_next_day() -> None:
    ledger = PortfolioLedger.opening(Decimal("100000"))
    ledger.apply_fill(fill("buy-1", OrderSide.BUY, 100, "10"))

    same_day = ledger.to_portfolio_snapshot(datetime(2024, 1, 2, 15, 30))
    next_day = ledger.to_portfolio_snapshot(datetime(2024, 1, 3, 9, 30))

    assert same_day.lots[0].available_to_sell == 0
    assert next_day.lots[0].available_to_sell == 100
