from datetime import UTC, datetime
from decimal import Decimal

from backend.app.bootstrap.e2e import FrozenE2EWarehouse
from backend.app.core.market.pit_models import SnapshotScope
from backend.app.core.portfolio.models import PortfolioPosition, PositionOrigin
from backend.app.core.portfolio.valuation import calculate_equity


def test_equity_uses_latest_point_in_time_close() -> None:
    as_of_time = datetime(2026, 7, 21, 15, 30, tzinfo=UTC)
    security_id = "601899.SH"
    snapshot = FrozenE2EWarehouse().snapshot(
        as_of_time=as_of_time,
        scope=SnapshotScope.holding_analysis((security_id,)),
    )
    position = PortfolioPosition(
        security_id=security_id,
        strategy_book=None,
        origin=PositionOrigin.RECORDED_TRADE,
        quantity=10,
        available_to_sell=10,
        average_cost=Decimal("1"),
        effective_stop=None,
        highest_close=None,
        entry_score=None,
        initial_risk_per_share=None,
        add_count=0,
    )

    assert calculate_equity(Decimal("100"), (position,), snapshot) == Decimal("470.6")
