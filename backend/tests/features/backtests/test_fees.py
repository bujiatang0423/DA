from decimal import Decimal

from backend.app.features.backtests.fees import RESEARCH_FEE_SCHEDULE, calculate_fee
from backend.app.features.backtests.models import OrderSide


def test_research_fee_schedule_has_minimum_commission_tax_and_transfer_fee() -> None:
    notional = Decimal("10000")

    assert calculate_fee(RESEARCH_FEE_SCHEDULE, OrderSide.BUY, notional) == Decimal("5.10")
    assert calculate_fee(RESEARCH_FEE_SCHEDULE, OrderSide.SELL, notional) == Decimal("10.10")
