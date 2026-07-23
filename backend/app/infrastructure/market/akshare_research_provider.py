"""Fail-closed AkShare adapter for current research evidence.

This adapter deliberately does not substitute fixture values when AkShare does not
return an auditable record. Historical PIT persistence is handled by a separate
ingestion flow.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime, time, timedelta, tzinfo
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Protocol
from zoneinfo import ZoneInfo
from backend.app.ports.research_data import (
    CalendarDay,
    FinancialMaterial,
    ResearchBar,
    ResearchFeeSchedule,
    ResearchQuote,
    UniverseSecurity,
)


class AkShareClient(Protocol):
    def tool_trade_date_hist_sina(self) -> RawFrame: ...

    def stock_info_a_code_name(self) -> RawFrame: ...

    def stock_individual_info_em(self, **kwargs: object) -> RawFrame: ...

    def stock_zh_a_spot_em(self) -> RawFrame: ...

    def stock_zh_a_hist(self, **kwargs: object) -> RawFrame: ...

    def stock_financial_report_sina(self, **kwargs: object) -> RawFrame: ...


class RawFrame(Protocol):
    def iterrows(self) -> Iterable[tuple[object, Mapping[str, object]]]: ...


class AkShareResearchProvider:
    """Expose AkShare's public A-share data without fabricating unavailable evidence."""

    provider_name = "akshare"

    def __init__(
        self,
        client: AkShareClient,
        lookback_days: int = 365,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._lookback_days = lookback_days
        self._now = now or _shanghai_now

    def trade_calendar(self, start: date, end: date) -> tuple[CalendarDay, ...]:
        retrieved_at = self._retrieved_at()
        rows = tuple(_rows(self._client.tool_trade_date_hist_sina()))
        source_hash = _response_hash(rows)
        return tuple(
            CalendarDay(
                trade_date=trade_date,
                is_open=True,
                available_at=retrieved_at,
                source_hash=source_hash,
            )
            for row in rows
            if (trade_date := _optional_date(row.get("trade_date"))) is not None
            and start <= trade_date <= end
        )

    def universe(self, as_of_time: datetime) -> tuple[UniverseSecurity, ...]:
        _require_aware(as_of_time)
        retrieved_at = self._retrieved_at()
        listing_rows = tuple(_rows(self._client.stock_info_a_code_name()))
        result: list[UniverseSecurity] = []
        for listing_row in listing_rows:
            security_id = _security_id_from_code(listing_row.get("code"))
            name = str(listing_row.get("name", "")).strip()
            if security_id is None or not name:
                continue
            metadata_rows = tuple(
                _rows(self._client.stock_individual_info_em(symbol=_code(security_id)))
            )
            metadata = _metadata(metadata_rows)
            listed_on = _optional_date(metadata.get("上市时间"))
            if listed_on is None:
                continue
            source_hash = _response_hash((*listing_rows, *metadata_rows))
            result.append(
                UniverseSecurity(
                    security_id=security_id,
                    name=name,
                    listed_on=listed_on,
                    is_st="ST" in name.upper(),
                    is_suspended=False,
                    industry_id=_string_or_none(metadata.get("行业")),
                    theme_ids=(),
                    available_at=retrieved_at,
                    source_hash=source_hash,
                )
            )
        return tuple(result)

    def quotes(
        self, security_ids: tuple[str, ...], as_of_time: datetime
    ) -> tuple[ResearchQuote, ...]:
        _require_aware(as_of_time)
        normalized_ids = tuple(_validate_security_id(item) for item in security_ids)
        retrieved_at = self._retrieved_at()
        rows = tuple(_rows(self._client.stock_zh_a_spot_em()))
        source_hash = _response_hash(rows)
        prices = {
            _security_id_from_code(row.get("代码")): _optional_decimal(row.get("最新价"))
            for row in rows
        }
        return tuple(
            ResearchQuote(
                security_id=security_id,
                price=price,
                observed_at=retrieved_at,
                source_hash=source_hash,
            )
            for security_id in normalized_ids
            if (price := prices.get(security_id)) is not None and price > 0
        )

    def daily_bars(self, security_id: str, as_of_time: datetime) -> tuple[ResearchBar, ...]:
        _require_aware(as_of_time)
        security_id = _validate_security_id(security_id)
        start = as_of_time.date() - timedelta(days=self._lookback_days)
        frame = self._client.stock_zh_a_hist(
            symbol=_code(security_id),
            period="daily",
            start_date=start.strftime("%Y%m%d"),
            end_date=as_of_time.strftime("%Y%m%d"),
            adjust="",
        )
        rows = tuple(_rows(frame))
        source_hash = _response_hash(rows)
        result: list[ResearchBar] = []
        for row in rows:
            bar = _bar_from_row(security_id, row, as_of_time, source_hash)
            if bar is not None:
                result.append(bar)
        return tuple(result)

    def financials(
        self, security_id: str, as_of_time: datetime
    ) -> tuple[FinancialMaterial, ...]:
        _require_aware(as_of_time)
        security_id = _validate_security_id(security_id)
        frame = self._client.stock_financial_report_sina(
            stock=_akshare_financial_symbol(security_id),
            symbol="利润表",
        )
        rows = tuple(_rows(frame))
        source_hash = _response_hash(rows)
        result: list[FinancialMaterial] = []
        for row in rows:
            material = _financial_from_row(security_id, row, as_of_time, source_hash)
            if material is not None:
                result.append(material)
        return tuple(result)

    def fee_schedules(self, as_of_time: datetime) -> tuple[ResearchFeeSchedule, ...]:
        del as_of_time
        return ()

    def _retrieved_at(self) -> datetime:
        value = self._now()
        _require_aware(value)
        return value


def _bar_from_row(
    security_id: str, row: dict[str, object], as_of_time: datetime, source_hash: str
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
        source_hash=source_hash,
    )


def _financial_from_row(
    security_id: str, row: dict[str, object], as_of_time: datetime, source_hash: str
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
        source_hash=source_hash,
    )


def _rows(frame: RawFrame) -> tuple[dict[str, object], ...]:
    return tuple(dict(row) for _, row in frame.iterrows())


def _code(security_id: str) -> str:
    return _validate_security_id(security_id).partition(".")[0]


def _akshare_financial_symbol(security_id: str) -> str:
    code, _, exchange = _validate_security_id(security_id).partition(".")
    return f"{exchange.lower()}{code}"


def _validate_security_id(security_id: str) -> str:
    code, separator, exchange = security_id.partition(".")
    if separator != "." or len(code) != 6 or not code.isdigit() or exchange not in {"SH", "SZ"}:
        raise ValueError(f"invalid security id: {security_id}")
    expected_exchange = "SH" if code.startswith(("5", "6", "9")) else "SZ"
    if exchange != expected_exchange:
        raise ValueError(f"invalid security id exchange: {security_id}")
    return f"{code}.{exchange}"


def _security_id_from_code(value: object) -> str | None:
    code = str(value).strip()
    if len(code) != 6 or not code.isdigit():
        return None
    exchange = "SH" if code.startswith(("5", "6", "9")) else "SZ"
    return f"{code}.{exchange}"


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


def _optional_decimal(value: object) -> Decimal | None:
    try:
        return _decimal(value)
    except (InvalidOperation, ValueError):
        return None


def _optional_date(value: object) -> date | None:
    try:
        return _parse_date(value)
    except (TypeError, ValueError):
        return None


def _metadata(rows: tuple[dict[str, object], ...]) -> dict[str, object]:
    return {
        str(row["item"]): row["value"]
        for row in rows
        if row.get("item") is not None and row.get("value") is not None
    }


def _string_or_none(value: object) -> str | None:
    normalized = str(value).strip() if value is not None else ""
    return normalized or None


def _response_hash(rows: tuple[dict[str, object], ...]) -> str:
    raw = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _shanghai_now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of_time must be timezone-aware")
