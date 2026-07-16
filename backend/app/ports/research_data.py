from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class CalendarDay:
    trade_date: date
    is_open: bool
    available_at: datetime
    source_hash: str


@dataclass(frozen=True)
class UniverseSecurity:
    security_id: str
    name: str
    listed_on: date
    is_st: bool
    is_suspended: bool
    industry_id: str | None
    theme_ids: tuple[str, ...]
    available_at: datetime
    source_hash: str


@dataclass(frozen=True)
class ResearchBar:
    security_id: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    amount: Decimal
    price_adjustment: str
    adjustment_factor: Decimal
    available_at: datetime
    source_hash: str


@dataclass(frozen=True)
class ResearchQuote:
    security_id: str
    price: Decimal
    observed_at: datetime
    source_hash: str


@dataclass(frozen=True)
class ResearchFeeSchedule:
    record_id: str
    effective_from: date
    effective_to: date | None
    exchange: str
    asset_type: str
    commission_rate: Decimal
    minimum_commission: Decimal
    stamp_tax_sell_rate: Decimal
    transfer_rate: Decimal
    available_at: datetime
    source_hash: str


@dataclass(frozen=True)
class FinancialMaterial:
    security_id: str
    report_period: date
    published_at: datetime
    facts: dict[str, Decimal | str | None]
    source_hash: str


class ResearchMarketDataPort(Protocol):
    def trade_calendar(self, start: date, end: date) -> tuple[CalendarDay, ...]: ...
    def universe(self, as_of_time: datetime) -> tuple[UniverseSecurity, ...]: ...
    def quotes(
        self, security_ids: tuple[str, ...], as_of_time: datetime
    ) -> tuple[ResearchQuote, ...]: ...
    def daily_bars(self, security_id: str, as_of_time: datetime) -> tuple[ResearchBar, ...]: ...
    def financials(
        self, security_id: str, as_of_time: datetime
    ) -> tuple[FinancialMaterial, ...]: ...
    def fee_schedules(self, as_of_time: datetime) -> tuple[ResearchFeeSchedule, ...]: ...
