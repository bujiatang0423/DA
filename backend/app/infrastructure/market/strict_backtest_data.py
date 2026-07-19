from __future__ import annotations

from datetime import date, datetime
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.contracts.grades import DataGrade
from backend.app.core.market.pit_models import PointInTimeSnapshot
from backend.app.features.backtests.execution import DailyBar
from backend.app.features.backtests.ports import (
    BacktestSnapshotPort,
    BacktestSnapshotQualityError,
    BacktestTradingDayPort,
)
from backend.app.features.backtests.strict_execution import HistoricalDailyBarReader
from backend.app.infrastructure.market.strict_queries import StrictDataMissingError
from backend.app.infrastructure.persistence.strict_pit_rows import (
    DailyBarRawRow,
    TradingCalendarRow,
)


class SqlAlchemyTradingCalendar(BacktestTradingDayPort):
    """Read exchange sessions using only versions visible at the configured cutoff."""

    def __init__(self, session: Session, *, as_of_time: datetime, exchange: str) -> None:
        self._session = session
        self._as_of_time = as_of_time
        self._exchange = exchange

    def between(self, start_date: date, end_date: date) -> tuple[date, ...]:
        rows = self._session.scalars(
            select(TradingCalendarRow).where(
                TradingCalendarRow.exchange == self._exchange,
                TradingCalendarRow.trade_date >= start_date,
                TradingCalendarRow.trade_date <= end_date,
                TradingCalendarRow.available_at <= self._as_of_time,
            )
        ).all()
        latest = _latest_by_source(rows)
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
        required = getattr(snapshot.scope, "required_kinds", None)
        if required is None:
            raise BacktestSnapshotQualityError()
        present_kinds = {
            record.kind
            for observation in snapshot.security_observations
            for record in observation.records
        }
        present_kinds.update(record.kind for record in snapshot.market_inputs)
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
