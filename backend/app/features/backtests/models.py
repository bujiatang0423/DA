from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.contracts.grades import DataGrade, LlmGrade


class StrategyGroup(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class BacktestRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    strategy_version: str
    start_date: date
    end_date: date
    initial_cash: Decimal = Field(gt=0)
    groups: list[StrategyGroup] = Field(min_length=1)
    buy_slippage_bps: int = Field(default=10, ge=0)
    sell_slippage_bps: int = Field(default=10, ge=0)
    fee_schedule_version: str = "research-cn-a-2023-08-28"

    @model_validator(mode="after")
    def validate_dates(self) -> BacktestRequest:
        if self.start_date > self.end_date:
            raise ValueError("start_date must not exceed end_date")
        return self

    def with_period(self, start_date: date, end_date: date) -> BacktestRequest:
        return type(self).model_validate(
            {**self.model_dump(), "start_date": start_date, "end_date": end_date}
        )

    def with_group(self, group: StrategyGroup) -> BacktestRequest:
        return type(self).model_validate({**self.model_dump(), "groups": [group]})


class OrderIntent(BaseModel):
    model_config = ConfigDict(frozen=True)
    order_id: str
    security_id: str
    side: OrderSide
    quantity: int = Field(gt=0)
    signal_date: date
    earliest_trade_date: date
    strategy_book: str
    priority: int = Field(ge=1)
    reason_codes: tuple[str, ...] = ()
    signal_close: Decimal = Field(gt=0)
    stop_price: Decimal | None = Field(default=None, gt=0)
    max_participation_rate: Decimal = Field(default=Decimal("0.002"), gt=0, le=1)


class BacktestGroupResult(BaseModel):
    group: StrategyGroup
    data_grade: DataGrade
    llm_grade: LlmGrade
    input_manifest_hash: str
    equity_curve: list[dict[str, str]]
    trades: list[dict[str, str]]
    metrics: dict[str, str | int | None]
    warnings: list[str] = []


class BacktestExperimentResult(BaseModel):
    request: BacktestRequest
    input_manifest_hash: str
    groups: tuple[BacktestGroupResult, ...]
    warnings: list[str] = []


class BacktestRunSummary(BaseModel):
    run_id: str
    status: str
    strategy_version: str
    input_manifest_hash: str
    groups: tuple[BacktestGroupResult, ...]
    created_at: datetime
