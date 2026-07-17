from datetime import date, datetime
from decimal import Decimal

from pydantic import Field, field_validator

from .common import ContractModel, require_aware


class PortfolioPositionInput(ContractModel):
    batch_id: str = Field(default="default", min_length=1, max_length=64)
    security_id: str = Field(min_length=1, max_length=32)
    buy_date: date | None = None
    quantity: int = Field(gt=0)
    average_cost: Decimal = Field(gt=0)
    available_to_sell: int | None = Field(default=None, ge=0)
    effective_stop: Decimal | None = Field(default=None, gt=0)
    highest_close: Decimal | None = Field(default=None, gt=0)
    strategy_book: str | None = Field(default=None, max_length=16)


class PortfolioMaintenanceRequest(ContractModel):
    portfolio_id: str = Field(min_length=1, max_length=64)
    as_of_time: datetime
    cash: Decimal = Field(ge=0)
    equity: Decimal = Field(ge=0)
    positions: list[PortfolioPositionInput] = Field(default_factory=list)
    expected_version: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=500)

    _aware = field_validator("as_of_time")(require_aware)


class PortfolioMaintenanceResponse(ContractModel):
    portfolio_id: str
    as_of_time: datetime
    version: int
    cash: Decimal
    equity: Decimal
    positions: list[PortfolioPositionInput]
