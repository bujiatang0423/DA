from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from backend.app.features.backtests.execution import FilledAttempt
from backend.app.features.backtests.models import OrderSide
from backend.app.core.portfolio.models import PortfolioSnapshot


@dataclass(frozen=True)
class Fill:
    fill_id: str
    security_id: str
    side: OrderSide
    quantity: int
    price: Decimal
    fee: Decimal
    filled_at: datetime
    strategy_book: str = "core"


@dataclass
class PositionState:
    security_id: str
    quantity: int
    average_cost: Decimal
    acquired_date: date

    @property
    def sellable_quantity(self) -> int:
        return self.quantity


@dataclass
class PortfolioState:
    cash: Decimal
    positions: dict[str, PositionState] = field(default_factory=dict)
    realized_pnl: Decimal = Decimal(0)
    version: int = 0


class PortfolioLedger:
    def __init__(self, state: PortfolioState) -> None:
        self.state = state
        self.applied_fill_ids: set[str] = set()

    @classmethod
    def opening(cls, cash: Decimal) -> PortfolioLedger:
        return cls(PortfolioState(cash))

    def apply_fill(self, fill: Fill) -> None:
        if fill.fill_id in self.applied_fill_ids:
            raise ValueError(f"duplicate fill: {fill.fill_id}")
        if fill.quantity <= 0:
            raise ValueError("quantity must be positive")
        notional = fill.price * fill.quantity
        position = self.state.positions.get(fill.security_id)
        if fill.side is OrderSide.BUY:
            total = notional + fill.fee
            if total > self.state.cash:
                raise ValueError("negative cash")
            if position is None:
                self.state.positions[fill.security_id] = PositionState(
                    fill.security_id, fill.quantity, total / fill.quantity, fill.filled_at.date()
                )
            else:
                combined = position.average_cost * position.quantity + total
                position.quantity += fill.quantity
                position.average_cost = combined / position.quantity
            self.state.cash -= total
        else:
            if position is None or fill.quantity > position.quantity:
                raise ValueError("oversell")
            self.state.cash += notional - fill.fee
            self.state.realized_pnl += (
                fill.price - position.average_cost
            ) * fill.quantity - fill.fee
            position.quantity -= fill.quantity
            if position.quantity == 0:
                del self.state.positions[fill.security_id]
        self.state.version += 1
        self.applied_fill_ids.add(fill.fill_id)

    def apply_attempt(
        self,
        attempt: FilledAttempt,
        intent_security_id: str,
        side: OrderSide,
        strategy_book: str = "core",
    ) -> Fill:
        fill = Fill(
            attempt.order_id,
            intent_security_id,
            side,
            attempt.quantity,
            attempt.actual_price,
            attempt.fee,
            datetime.combine(attempt.trade_date, datetime.min.time()),
            strategy_book,
        )
        self.apply_fill(fill)
        return fill

    def to_portfolio_snapshot(self, as_of_time: datetime) -> PortfolioSnapshot:
        from backend.app.core.portfolio.models import (
            PortfolioLot,
            PortfolioSnapshot,
            PositionOrigin,
        )

        lots = tuple(
            PortfolioLot(
                f"sim-{security_id}",
                security_id,
                position.quantity,
                position.sellable_quantity,
                position.average_cost,
                datetime.combine(position.acquired_date, datetime.min.time()),
                PositionOrigin.SIMULATED_FILL,
                None,
                None,
                None,
                None,
                None,
                0,
            )
            for security_id, position in sorted(self.state.positions.items())
            if position.quantity > 0
        )
        return PortfolioSnapshot(
            "backtest", as_of_time, self.state.version, self.state.cash, self.state.cash, lots
        )
