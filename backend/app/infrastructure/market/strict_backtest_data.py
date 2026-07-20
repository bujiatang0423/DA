from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo

from backend.app.contracts.grades import DataGrade
from backend.app.core.market.pit_models import (
    DataKind,
    PointInTimeSnapshot,
    SnapshotScope,
    TemporalRecord,
)
from backend.app.features.backtests.execution import DailyBar
from backend.app.features.backtests.ports import (
    BacktestSnapshotPort,
    BacktestSnapshotQualityError,
    BacktestTradingDayPort,
)
from backend.app.features.backtests.strict_execution import (
    HistoricalDailyBarReader,
    _validate_snapshot,
)
from backend.app.infrastructure.market.strict_queries import StrictDataMissingError
from backend.app.infrastructure.persistence.strict_pit_rows import (
    DailyBarRawRow,
    TradingCalendarRow,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")


class SqlAlchemyTradingCalendar(BacktestTradingDayPort):
    """Read each exchange session from versions visible by that session's close."""

    def __init__(self, session: Session, *, exchange: str) -> None:
        self._session = session
        self._exchange = exchange

    def between(self, start_date: date, end_date: date) -> tuple[date, ...]:
        rows = self._session.scalars(
            select(TradingCalendarRow).where(
                TradingCalendarRow.exchange == self._exchange,
                TradingCalendarRow.trade_date >= start_date,
                TradingCalendarRow.trade_date <= end_date,
            )
        ).all()
        visible = [row for row in rows if row.available_at <= _calendar_close(row.trade_date)]
        latest = _latest_by_source(visible)
        return tuple(sorted(row.trade_date for row in latest.values() if row.is_open))


class SqlAlchemyHistoricalDailyBars(HistoricalDailyBarReader):
    """Read a visible OHLCV version plus its visible prior close for strict execution."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def bar_for(
        self,
        security_id: str,
        trade_date: date,
        *,
        as_of_time: datetime,
    ) -> DailyBar:
        current = self._visible_row(security_id, trade_date, as_of_time)
        if current is None:
            raise StrictDataMissingError(f"daily bar missing: {security_id}")
        previous = self._visible_previous_row(security_id, trade_date, as_of_time)
        if previous is None:
            raise StrictDataMissingError(f"previous close missing: {security_id}")
        return DailyBar(
            trade_date=current.trade_date,
            open=current.open,
            high=current.high,
            low=current.low,
            close=current.close,
            volume=current.volume,
            previous_close=previous.close,
        )

    def _visible_row(
        self,
        security_id: str,
        trade_date: date,
        as_of_time: datetime,
    ) -> DailyBarRawRow | None:
        rows = self._session.scalars(
            select(DailyBarRawRow).where(
                DailyBarRawRow.security_id == security_id,
                DailyBarRawRow.trade_date == trade_date,
                DailyBarRawRow.available_at <= as_of_time,
            )
        ).all()
        if not rows:
            return None
        return max(rows, key=_row_order)

    def _visible_previous_row(
        self,
        security_id: str,
        trade_date: date,
        as_of_time: datetime,
    ) -> DailyBarRawRow | None:
        rows = self._session.scalars(
            select(DailyBarRawRow).where(
                DailyBarRawRow.security_id == security_id,
                DailyBarRawRow.trade_date < trade_date,
                DailyBarRawRow.available_at <= as_of_time,
            )
        ).all()
        if not rows:
            return None
        latest_by_source = _latest_by_source(rows)
        latest_date = max(row.trade_date for row in latest_by_source.values())
        candidates = [row for row in latest_by_source.values() if row.trade_date == latest_date]
        return max(candidates, key=_row_order)


class CertifiedHistoricalDailyBars(HistoricalDailyBarReader):
    """Read execution bars exclusively from the certificate-attested PIT snapshot."""

    def __init__(self, warehouse: BacktestSnapshotPort) -> None:
        self._warehouse = warehouse

    def bar_for(
        self,
        security_id: str,
        trade_date: date,
        *,
        as_of_time: datetime,
    ) -> DailyBar:
        scope = SnapshotScope((security_id,), (DataKind.DAILY_BAR_RAW,))
        snapshot = self._warehouse.snapshot(as_of_time=as_of_time, scope=scope)
        _validate_snapshot(snapshot, as_of_time, scope)
        bars = tuple(
            record
            for record in _snapshot_records(snapshot)
            if record.kind is DataKind.DAILY_BAR_RAW and record.entity_id == security_id
        )
        current = next((bar for bar in bars if bar.event_time.date() == trade_date), None)
        if current is None:
            raise StrictDataMissingError(f"certified daily bar missing: {security_id}")
        previous = _previous_certified_bar(bars, trade_date)
        if previous is None:
            raise StrictDataMissingError(f"certified previous close missing: {security_id}")
        return DailyBar(
            trade_date=trade_date,
            open=_bar_decimal(current, "open"),
            high=_bar_decimal(current, "high"),
            low=_bar_decimal(current, "low"),
            close=_bar_decimal(current, "close"),
            volume=_bar_volume(current),
            previous_close=_bar_decimal(previous, "close"),
        )


class StrictBacktestSnapshotAdapter(BacktestSnapshotPort):
    """Reject quality-degraded snapshots before strict backtest decisions can use them."""

    def __init__(self, warehouse: BacktestSnapshotPort) -> None:
        self._warehouse = warehouse

    def snapshot(self, *, as_of_time: datetime, scope: object) -> PointInTimeSnapshot:
        snapshot = self._warehouse.snapshot(as_of_time=as_of_time, scope=scope)
        if snapshot.data_grade is not DataGrade.PIT_VERIFIED:
            raise BacktestSnapshotQualityError()
        if snapshot.as_of_time != as_of_time or snapshot.scope != scope:
            raise BacktestSnapshotQualityError()
        if snapshot.quality.has_errors:
            raise BacktestSnapshotQualityError()
        records = tuple(_snapshot_records(snapshot))
        if any(record.available_at > as_of_time for record in records):
            raise BacktestSnapshotQualityError()
        required = getattr(snapshot.scope, "required_kinds", None)
        if required is None:
            raise BacktestSnapshotQualityError()
        present_kinds = {record.kind for record in records}
        if set(required) - present_kinds:
            raise BacktestSnapshotQualityError()
        return snapshot


T = TypeVar("T", TradingCalendarRow, DailyBarRawRow)


def _latest_by_source(rows: list[T]) -> dict[str, T]:
    result: dict[str, T] = {}
    for row in rows:
        current = result.get(row.source_record_id)
        if current is None or _row_order(row) > _row_order(current):
            result[row.source_record_id] = row
    return result


def _row_order(row: TradingCalendarRow | DailyBarRawRow) -> tuple[datetime, str]:
    return row.available_at, row.id


def _calendar_close(trade_date: date) -> datetime:
    return datetime.combine(trade_date, time.max, SHANGHAI)


def _snapshot_records(snapshot: PointInTimeSnapshot) -> Iterator[TemporalRecord]:
    yield from snapshot.market_inputs
    for observation in snapshot.security_observations:
        yield from observation.records


def _previous_certified_bar(
    bars: tuple[TemporalRecord, ...],
    trade_date: date,
) -> TemporalRecord | None:
    previous = [bar for bar in bars if bar.event_time.date() < trade_date]
    return max(previous, key=lambda bar: (bar.event_time, bar.record_id), default=None)


def _bar_decimal(record: TemporalRecord, field: str) -> Decimal:
    try:
        return Decimal(str(record.payload[field]))
    except (InvalidOperation, KeyError) as error:
        raise StrictDataMissingError(f"certified daily bar field missing: {field}") from error


def _bar_volume(record: TemporalRecord) -> int:
    try:
        return int(str(record.payload["volume"]))
    except (TypeError, ValueError, KeyError) as error:
        raise StrictDataMissingError("certified daily bar field missing: volume") from error
