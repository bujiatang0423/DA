from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from backend.app.core.market.pit_models import DataKind, PointInTimeSnapshot
from backend.app.core.portfolio.models import PortfolioPosition


class PortfolioValuationError(RuntimeError):
    """Raised when a point-in-time close is unavailable for a holding."""


def calculate_equity(
    cash: Decimal,
    positions: Sequence[PortfolioPosition],
    snapshot: PointInTimeSnapshot,
) -> Decimal:
    """Calculate cash plus position market value from the latest PIT close."""
    observations = {item.security_id: item for item in snapshot.security_observations}
    market_value = Decimal("0")
    for position in positions:
        observation = observations.get(position.security_id)
        if observation is None:
            raise PortfolioValuationError(f"missing PIT close for {position.security_id}")
        bars = sorted(
            observation.records_of(DataKind.DAILY_BAR_RAW),
            key=lambda record: str(record.payload.get("trade_date", record.event_time)),
        )
        if not bars or bars[-1].payload.get("close") is None:
            raise PortfolioValuationError(f"missing PIT close for {position.security_id}")
        market_value += Decimal(str(bars[-1].payload["close"])) * position.quantity
    return cash + market_value
