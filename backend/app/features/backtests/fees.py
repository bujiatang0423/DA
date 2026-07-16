from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from backend.app.features.backtests.models import OrderSide


@dataclass(frozen=True)
class FeeSchedule:
    version: str
    commission_rate: Decimal
    minimum_commission: Decimal
    stamp_tax_sell_rate: Decimal
    transfer_rate: Decimal


RESEARCH_FEE_SCHEDULE = FeeSchedule(
    "research-cn-a-2023-08-28",
    Decimal("0.0003"),
    Decimal("5"),
    Decimal("0.0005"),
    Decimal("0.00001"),
)


def calculate_fee(schedule: FeeSchedule, side: OrderSide, notional: Decimal) -> Decimal:
    commission = max(schedule.minimum_commission, notional * schedule.commission_rate)
    transfer = notional * schedule.transfer_rate
    stamp = notional * schedule.stamp_tax_sell_rate if side is OrderSide.SELL else Decimal(0)
    return (commission + transfer + stamp).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
