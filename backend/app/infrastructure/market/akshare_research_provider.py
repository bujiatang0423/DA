"""Fail-closed AkShare adapter for current research evidence.

This adapter deliberately does not substitute fixture values when AkShare does not
return an auditable record. Historical PIT persistence is handled by a separate
ingestion flow.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timedelta, tzinfo
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Protocol
from backend.app.ports.research_data import (
    CalendarDay,
    FinancialMaterial,
    ResearchBar,
    ResearchFeeSchedule,
    ResearchQuote,
    UniverseSecurity,
)


class AkShareClient(Protocol):
    def stock_zh_a_hist(self, **kwargs: object) -> RawFrame: ...

    def stock_financial_report_sina(self, **kwargs: object) -> RawFrame: ...


class RawFrame(Protocol):
    def iterrows(self) -> Iterable[tuple[object, Mapping[str, object]]]: ...


class AkShareResearchProvider:
    """Expose AkShare's public A-share data without fabricating unavailable evidence."""

    provider_name = "akshare"

    def __init__(self, client: AkShareClient, lookback_days: int = 365) -> None:
        self._client = client
        self._lookback_days = lookback_days

    def trade_calendar(self, start: date, end: date) -> tuple[CalendarDay, ...]:
        del start, end
        return ()

    def universe(self, as_of_time: datetime) -> tuple[UniverseSecurity, ...]:
        del as_of_time
        return ()

    def quotes(
        self, security_ids: tuple[str, ...], as_of_time: datetime
    ) -> tuple[ResearchQuote, ...]:
        del security_ids, as_of_time
        return ()

    def daily_bars(self, security_id: str, as_of_time: datetime) -> tuple[ResearchBar, ...]:
        _require_aware(as_of_time)
        start = as_of_time.date() - timedelta(days=self._lookback_days)
        frame = self._client.stock_zh_a_hist(
            symbol=_code(security_id),
            period="daily",
            start_date=start.strftime("%Y%m%d"),
            end_date=as_of_time.strftime("%Y%m%d"),
            adjust="",
        )
        rows = tuple(_rows(frame))
        result: list[ResearchBar] = []
        for row in rows:
            bar = _bar_from_row(security_id, row, as_of_time)
            if bar is not None:
                result.append(bar)
        return tuple(result)

    def financials(
        self, security_id: str, as_of_time: datetime
    ) -> tuple[FinancialMaterial, ...]:
        _require_aware(as_of_time)
        frame = self._client.stock_financial_report_sina(
            stock=_akshare_financial_symbol(security_id),
            symbol="利润表",
        )
        result: list[FinancialMaterial] = []
        for row in _rows(frame):
            material = _financial_from_row(security_id, row, as_of_time)
            if material is not None:
                result.append(material)
        return tuple(result)

    def fee_schedules(self, as_of_time: datetime) -> tuple[ResearchFeeSchedule, ...]:
        del as_of_time
        return ()


def _bar_from_row(
    security_id: str, row: dict[str, object], as_of_time: datetime
) -> ResearchBar | None:
    try:
        trade_date = _parse_date(row["日期"])
        prices = tuple(_decimal(row[field]) for field in ("开盘", "最高", "最低", "收盘"))
        volume = int(Decimal(str(row["成交量"])))
        amount = _decimal(row["成交额"])
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return None
    available_at = datetime.combine(trade_date, time(15), as_of_time.tzinfo)
    if trade_date > as_of_time.date() or available_at > as_of_time or min(prices) <= 0:
        return None
    if volume < 0 or amount < 0:
        return None
    return ResearchBar(
        security_id=security_id,
        trade_date=trade_date,
        open=prices[0],
        high=prices[1],
        low=prices[2],
        close=prices[3],
        volume=volume,
        amount=amount,
        price_adjustment="none",
        adjustment_factor=Decimal("1"),
        available_at=available_at,
        source_hash=_source_hash(row),
    )


def _financial_from_row(
    security_id: str, row: dict[str, object], as_of_time: datetime
) -> FinancialMaterial | None:
    try:
        report_period = _parse_date(row["报表日期"])
        published_at = _parse_datetime(row["公告日期"], as_of_time.tzinfo)
    except (KeyError, TypeError, ValueError):
        return None
    if published_at > as_of_time:
        return None
    facts = {
        key: _fact_value(value)
        for key, value in row.items()
        if key not in {"报表日期", "公告日期"}
    }
    return FinancialMaterial(
        security_id=security_id,
        report_period=report_period,
        published_at=published_at,
        facts=facts,
        source_hash=_source_hash(row),
    )


def _rows(frame: RawFrame) -> tuple[dict[str, object], ...]:
    return tuple(dict(row) for _, row in frame.iterrows())


def _code(security_id: str) -> str:
    return security_id.partition(".")[0]


def _akshare_financial_symbol(security_id: str) -> str:
    code, separator, exchange = security_id.partition(".")
    if not separator or exchange not in {"SH", "SZ"}:
        raise ValueError(f"unsupported A-share security id: {security_id}")
    return f"{exchange.lower()}{code}"


def _parse_date(value: object) -> date:
    return date.fromisoformat(str(value)[:10])


def _parse_datetime(value: object, timezone: tzinfo) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone)
    return parsed.replace(tzinfo=timezone)


def _decimal(value: object) -> Decimal:
    parsed = Decimal(str(value))
    if not parsed.is_finite():
        raise ValueError("non-finite decimal")
    return parsed


def _fact_value(value: object) -> Decimal | str | None:
    if value is None or str(value).strip() in {"", "--", "nan", "None"}:
        return None
    try:
        return _decimal(value)
    except (InvalidOperation, ValueError):
        return str(value)


def _source_hash(row: dict[str, object]) -> str:
    raw = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of_time must be timezone-aware")
