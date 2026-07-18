from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from backend.app.features.backtests.fees import FeeSchedule, RESEARCH_FEE_SCHEDULE, calculate_fee
from backend.app.features.backtests.models import OrderIntent, OrderSide


@dataclass(frozen=True)
class DailyBar:
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    suspended: bool = False
    limit_up: bool = False
    limit_down: bool = False


@dataclass(frozen=True)
class FilledAttempt:
    order_id: str
    trade_date: date
    quantity: int
    theoretical_price: Decimal
    actual_price: Decimal
    fee: Decimal
    slippage: Decimal
    reason_code: str | None = None
    fee_schedule_version: str = ""


@dataclass(frozen=True)
class RejectedAttempt:
    order_id: str
    trade_date: date
    quantity: int
    reason_code: str
    fee_schedule_version: str = ""


def stop_price(bar: DailyBar, stop: Decimal, slippage: Decimal) -> Decimal | None:
    if bar.open <= stop:
        return bar.open * (Decimal(1) - slippage)
    if bar.low <= stop:
        return stop * (Decimal(1) - slippage)
    return None


class ExecutionSimulator:
    def __init__(self, fee_schedule: FeeSchedule = RESEARCH_FEE_SCHEDULE) -> None:
        self.fee_schedule = fee_schedule

    def attempt(
        self,
        intent: OrderIntent,
        bar: DailyBar,
        *,
        available_to_sell: int = 0,
        slippage_bps: int = 10,
    ) -> FilledAttempt | RejectedAttempt:
        if intent.earliest_trade_date > bar.trade_date:
            return self._reject(intent, bar, "T_PLUS_ONE")
        if bar.suspended:
            return self._reject(intent, bar, "SUSPENDED")
        if intent.side is OrderSide.BUY and bar.limit_up:
            return self._reject(intent, bar, "LIMIT_UP_LOCKED")
        if intent.side is OrderSide.SELL and bar.limit_down:
            return self._reject(intent, bar, "LIMIT_DOWN_LOCKED")
        if intent.side is OrderSide.BUY and bar.open > intent.signal_close * Decimal("1.03"):
            return self._reject(intent, bar, "BUY_GAP_TOO_HIGH")
        if intent.side is OrderSide.SELL:
            quantity = min(intent.quantity, available_to_sell)
        else:
            quantity = min(intent.quantity, int(bar.volume * intent.max_participation_rate))
            quantity = quantity // 100 * 100
        if quantity <= 0:
            return self._reject(intent, bar, "VOLUME_PARTICIPATION")
        slip = Decimal(slippage_bps) / Decimal(10000)
        if intent.side is OrderSide.BUY:
            price = bar.open * (Decimal(1) + slip)
        else:
            price = bar.open * (Decimal(1) - slip)
            if intent.stop_price is not None:
                price = stop_price(bar, intent.stop_price, slip) or price
        fee = calculate_fee(self.fee_schedule, intent.side, price * quantity)
        return FilledAttempt(
            intent.order_id,
            bar.trade_date,
            quantity,
            bar.open,
            price,
            fee,
            slip,
            fee_schedule_version=self.fee_schedule.version,
        )

    def _reject(
        self,
        intent: OrderIntent,
        bar: DailyBar,
        reason_code: str,
    ) -> RejectedAttempt:
        return RejectedAttempt(
            intent.order_id,
            bar.trade_date,
            0,
            reason_code,
            self.fee_schedule.version,
        )
