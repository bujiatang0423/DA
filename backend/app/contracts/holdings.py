from datetime import datetime
from decimal import Decimal

from pydantic import Field, field_validator

from .common import ContractModel, require_aware


class HoldingAnalysisRequest(ContractModel):
    portfolio_id: str = Field(min_length=1, max_length=64)
    as_of_time: datetime
    prices: dict[str, Decimal] = Field(default_factory=dict)
    atr14: dict[str, Decimal] = Field(default_factory=dict)
    market_max_exposure: Decimal = Field(default=Decimal("1"), ge=0, le=1)
    portfolio_drawdown: Decimal = Field(default=Decimal("0"), ge=0)

    _aware = field_validator("as_of_time")(require_aware)


class HoldingRisk(ContractModel):
    security_id: str
    origin: str
    strategy_book: str | None = None
    quantity: int
    average_cost: Decimal
    last_price: Decimal | None
    market_value: Decimal
    unrealized_pnl: Decimal | None
    unrealized_return: Decimal | None
    highest_close: Decimal | None
    drawdown_from_high: Decimal | None
    effective_stop: Decimal | None
    stop_breached: bool
    risk_status: str
    reasons: list[str]


class HoldingAnalysisResponse(ContractModel):
    portfolio_id: str
    as_of_time: datetime
    equity: Decimal
    gross_exposure: Decimal
    exposure_ratio: Decimal
    market_max_exposure: Decimal
    portfolio_drawdown: Decimal
    risks: list[HoldingRisk]
    warnings: list[str]
