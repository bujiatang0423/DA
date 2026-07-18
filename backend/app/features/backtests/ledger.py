from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from backend.app.core.portfolio.models import PortfolioSnapshot
from backend.app.features.backtests.execution import FilledAttempt
from backend.app.features.backtests.models import OrderSide


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
    entry_score: Decimal | None = None
    initial_risk_per_share: Decimal | None = None
    effective_stop: Decimal | None = None
    highest_close: Decimal | None = None


@dataclass
class PositionLot:
    lot_id: str
    security_id: str
    acquired_at: datetime
    quantity: int
    remaining_quantity: int
    average_cost: Decimal
    strategy_book: str
    entry_score: Decimal | None = None
    initial_risk_per_share: Decimal | None = None
    effective_stop: Decimal | None = None
    highest_close: Decimal | None = None
    add_count: int = 0


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
    lots: list[PositionLot] = field(default_factory=list)
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
        if fill.side is OrderSide.BUY:
            self._apply_buy(fill)
        else:
            self._apply_sell(fill)
        self.state.version += 1
        self.applied_fill_ids.add(fill.fill_id)

    def position(self, security_id: str) -> PositionState:
        return self.state.positions[security_id]

    def _apply_buy(self, fill: Fill) -> None:
        total = fill.price * fill.quantity + fill.fee
        if total > self.state.cash:
            raise ValueError("negative cash")
        self.state.lots.append(
            PositionLot(
                lot_id=f"sim-{fill.fill_id}",
                security_id=fill.security_id,
                acquired_at=fill.filled_at,
                quantity=fill.quantity,
                remaining_quantity=fill.quantity,
                average_cost=total / fill.quantity,
                strategy_book=fill.strategy_book,
                entry_score=fill.entry_score,
                initial_risk_per_share=fill.initial_risk_per_share,
                effective_stop=fill.effective_stop,
                highest_close=fill.highest_close,
            )
        )
        self.state.cash -= total
        self._refresh_position(fill.security_id)

    def _apply_sell(self, fill: Fill) -> None:
        available = sum(
            lot.remaining_quantity
            for lot in self.state.lots
            if lot.security_id == fill.security_id
        )
        if fill.quantity > available:
            raise ValueError("oversell")

        remaining = fill.quantity
        realized_pnl = Decimal(0)
        for lot in self.state.lots:
            if lot.security_id != fill.security_id or remaining == 0:
                continue
            sold = min(remaining, lot.remaining_quantity)
            lot.remaining_quantity -= sold
            remaining -= sold
            realized_pnl += (fill.price - lot.average_cost) * sold

        self.state.cash += fill.price * fill.quantity - fill.fee
        self.state.realized_pnl += realized_pnl - fill.fee
        self._refresh_position(fill.security_id)

    def _refresh_position(self, security_id: str) -> None:
        lots = [
            lot
            for lot in self.state.lots
            if lot.security_id == security_id and lot.remaining_quantity > 0
        ]
        quantity = sum(lot.remaining_quantity for lot in lots)
        if quantity == 0:
            self.state.positions.pop(security_id, None)
            return
        total_cost = sum((lot.average_cost * lot.remaining_quantity for lot in lots), Decimal(0))
        acquired_date = min(lot.acquired_at.date() for lot in lots)
        self.state.positions[security_id] = PositionState(
            security_id, quantity, total_cost / quantity, acquired_date
        )

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
            StrategyBook,
        )

        lots = tuple(
            PortfolioLot(
                lot_id=lot.lot_id,
                security_id=lot.security_id,
                quantity=lot.remaining_quantity,
                available_to_sell=self._sellable_quantity(lot, as_of_time.date()),
                average_cost=lot.average_cost,
                effective_at=lot.acquired_at,
                origin=PositionOrigin.SIMULATED_FILL,
                strategy_book=StrategyBook(lot.strategy_book),
                entry_score=lot.entry_score,
                initial_risk_per_share=lot.initial_risk_per_share,
                effective_stop=lot.effective_stop,
                highest_close=lot.highest_close,
                add_count=lot.add_count,
            )
            for lot in self.state.lots
            if lot.remaining_quantity > 0
        )
        return PortfolioSnapshot(
            "backtest", as_of_time, self.state.version, self.state.cash, self.state.cash, lots
        )

    @staticmethod
    def _sellable_quantity(lot: PositionLot, as_of_date: date) -> int:
        if lot.acquired_at.date() >= as_of_date:
            return 0
        return lot.remaining_quantity
