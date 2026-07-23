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

    def stock_zh_a_spot_em(self) -> RawFrame: ...

    def fund_etf_spot_em(self) -> RawFrame: ...

    def stock_zh_a_hist(self, **kwargs: object) -> RawFrame: ...

    def fund_etf_hist_em(self, **kwargs: object) -> RawFrame: ...

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
        if retrieved_at > as_of_time:
            return ()
        # AkShare's public spot endpoint supplies a last price, not a verified
        # suspension state. Do not infer an investable universe from it.
        return ()

    def quotes(
        self, security_ids: tuple[str, ...], as_of_time: datetime
    ) -> tuple[ResearchQuote, ...]:
        _require_aware(as_of_time)
        normalized_ids = tuple(_validate_security_id(item) for item in security_ids)
        retrieved_at = self._retrieved_at()
        if retrieved_at > as_of_time:
            return ()
        stock_ids = tuple(item for item in normalized_ids if not _is_etf(item))
        etf_ids = tuple(item for item in normalized_ids if _is_etf(item))
        prices: dict[str, tuple[Decimal, str]] = {}
        if stock_ids:
            prices.update(_quote_prices(tuple(_rows(self._client.stock_zh_a_spot_em()))))
        if etf_ids:
            prices.update(_quote_prices(tuple(_rows(self._client.fund_etf_spot_em()))))
        return tuple(
            ResearchQuote(
                security_id=security_id,
                price=price,
                observed_at=retrieved_at,
                source_hash=source_hash,
            )
            for security_id in normalized_ids
            if (quote := prices.get(security_id)) is not None
            for price, source_hash in (quote,)
        )

    def daily_bars(self, security_id: str, as_of_time: datetime) -> tuple[ResearchBar, ...]:
        _require_aware(as_of_time)
        security_id = _validate_security_id(security_id)
        start = as_of_time.date() - timedelta(days=self._lookback_days)
        request = {
            "symbol": _code(security_id),
            "period": "daily",
            "start_date": start.strftime("%Y%m%d"),
            "end_date": as_of_time.strftime("%Y%m%d"),
            "adjust": "",
        }
        frame = (
            self._client.fund_etf_hist_em(**request)
            if _is_etf(security_id)
            else self._client.stock_zh_a_hist(**request)
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
        if _is_etf(security_id):
            return ()
        statement_rows = tuple(
            tuple(
                _rows(
                    self._client.stock_financial_report_sina(
                        stock=_akshare_financial_symbol(security_id),
                        symbol=statement,
                    )
                )
            )
            for statement in ("利润表", "资产负债表", "现金流量表")
        )
        rows = tuple(row for items in statement_rows for row in items)
        source_hash = _response_hash(rows)
        grouped: dict[date, list[FinancialMaterial]] = {}
        for row in rows:
            material = _financial_from_row(security_id, row, as_of_time, source_hash)
            if material is not None:
                grouped.setdefault(material.report_period, []).append(material)
        return tuple(
            _merge_financials(security_id, period, items, source_hash)
            for period, items in grouped.items()
        )

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
        report_period = _parse_date(row["报告日"])
        published_at = _parse_datetime(row["公告日期"], as_of_time.tzinfo)
    except (KeyError, TypeError, ValueError):
        return None
    if published_at > as_of_time:
        return None
    facts = {
        key: _fact_value(value)
        for key, value in row.items()
        if key not in {"报告日", "公告日期"}
    }
    return FinancialMaterial(
        security_id=security_id,
        report_period=report_period,
        published_at=published_at,
        facts=facts,
        source_hash=source_hash,
    )


def _merge_financials(
    security_id: str,
    report_period: date,
    materials: list[FinancialMaterial],
    source_hash: str,
) -> FinancialMaterial:
    facts: dict[str, Decimal | str | None] = {}
    for material in materials:
        facts.update(material.facts)
    return FinancialMaterial(
        security_id=security_id,
        report_period=report_period,
        published_at=max(item.published_at for item in materials),
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
    exchange = exchange.upper()
    if separator != "." or len(code) != 6 or not code.isdigit() or exchange not in {"SH", "SZ"}:
        raise ValueError(f"invalid security id: {security_id}")
    if code.startswith(("4", "8")):
        raise ValueError(f"unsupported Beijing security id: {security_id}")
    expected_exchange = "SH" if code.startswith(("5", "6", "9")) else "SZ"
    if exchange != expected_exchange:
        raise ValueError(f"invalid security id exchange: {security_id}")
    return f"{code}.{exchange}"


def _security_id_from_code(value: object) -> str | None:
    code = str(value).strip()
    if len(code) != 6 or not code.isdigit():
        return None
    if code.startswith(("4", "8")):
        return None
    exchange = "SH" if code.startswith(("5", "6", "9")) else "SZ"
    return f"{code}.{exchange}"


def _is_etf(security_id: str) -> bool:
    code, _, exchange = _validate_security_id(security_id).partition(".")
    return (exchange == "SH" and code.startswith(("5",))) or (
        exchange == "SZ" and code.startswith(("15", "16", "18"))
    )


def _parse_date(value: object) -> date:
    return date.fromisoformat(str(value)[:10])


def _parse_datetime(value: object, timezone: tzinfo) -> datetime:
    raw = str(value).strip().replace("Z", "+00:00")
    if len(raw) == 8 and raw.isdigit():
        return datetime.combine(_parse_date(raw), time.max, timezone)
    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        return datetime.combine(_parse_date(raw), time.max, timezone)
    parsed = datetime.fromisoformat(raw)
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


def _quote_prices(rows: tuple[dict[str, object], ...]) -> dict[str, tuple[Decimal, str]]:
    source_hash = _response_hash(rows)
    prices: dict[str, tuple[Decimal, str]] = {}
    for row in rows:
        security_id = _security_id_from_code(row.get("代码"))
        price = _optional_decimal(row.get("最新价"))
        if security_id is not None and price is not None and price > 0:
            prices[security_id] = (price, source_hash)
    return prices


def _response_hash(rows: tuple[dict[str, object], ...]) -> str:
    raw = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _shanghai_now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of_time must be timezone-aware")
