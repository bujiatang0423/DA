from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.contracts.grades import DataGrade
from backend.app.core.market.pit_models import (
    DataKind,
    PointInTimeSnapshot,
    QualityIssue,
    QualitySeverity,
    SnapshotQuality,
    SnapshotScope,
    TemporalRecord,
)
from backend.app.features.backtests.execution import DailyBar
from backend.app.features.backtests.ports import BacktestSnapshotQualityError
from backend.app.infrastructure.market.strict_backtest_data import (
    CertifiedHistoricalDailyBars,
    SqlAlchemyHistoricalDailyBars,
    SqlAlchemyTradingCalendar,
    StrictBacktestSnapshotAdapter,
)
from backend.app.infrastructure.market.strict_queries import StrictDataMissingError
from backend.app.infrastructure.persistence.strict_pit_rows import (
    DailyBarRawRow,
    TradingCalendarRow,
)


AS_OF = datetime(2024, 1, 5, 9, 0, tzinfo=UTC)
HASH = "a" * 64


@pytest.fixture
def strict_data_session(postgres_engine: Engine) -> Iterator[Session]:
    for table in (TradingCalendarRow.__table__, DailyBarRawRow.__table__):
        table.create(postgres_engine, checkfirst=True)
    with postgres_engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE trading_calendar, daily_bars_raw CASCADE"))
    session = sessionmaker(bind=postgres_engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        with postgres_engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE trading_calendar, daily_bars_raw CASCADE"))


@pytest.mark.postgres
def test_calendar_uses_versions_visible_by_each_trade_date_and_only_open_days(
    strict_data_session: Session,
) -> None:
    strict_data_session.add_all(
        [
            calendar_row("open-old", date(2024, 1, 2), True, "calendar-2"),
            calendar_row("closed-new", date(2024, 1, 2), False, "calendar-2", AS_OF),
            calendar_row("open", date(2024, 1, 3), True, "calendar-3"),
            calendar_row(
                "future", date(2024, 1, 4), True, "calendar-4", datetime(2024, 1, 6, tzinfo=UTC)
            ),
        ]
    )
    strict_data_session.commit()

    calendar = SqlAlchemyTradingCalendar(strict_data_session, exchange="SSE")

    assert calendar.between(date(2024, 1, 2), date(2024, 1, 4)) == (
        date(2024, 1, 2),
        date(2024, 1, 3),
    )


@pytest.mark.postgres
def test_calendar_does_not_use_a_later_revision_for_a_historical_trade_date(
    strict_data_session: Session,
) -> None:
    trade_date = date(2024, 1, 2)
    strict_data_session.add_all(
        [
            calendar_row("open-original", trade_date, True, "calendar-2"),
            calendar_row(
                "closed-later",
                trade_date,
                False,
                "calendar-2",
                datetime(2024, 1, 3, tzinfo=UTC),
            ),
        ]
    )
    strict_data_session.commit()

    calendar = SqlAlchemyTradingCalendar(strict_data_session, exchange="SSE")

    assert calendar.between(trade_date, trade_date) == (trade_date,)


@pytest.mark.postgres
def test_daily_bar_reader_uses_visible_version_and_requires_visible_prior_close(
    strict_data_session: Session,
) -> None:
    strict_data_session.add_all(
        [
            bar_row("prior", date(2024, 1, 3), Decimal("10"), "bar-prior"),
            bar_row("old", date(2024, 1, 4), Decimal("11"), "bar-current"),
            bar_row("new", date(2024, 1, 4), Decimal("12"), "bar-current", AS_OF),
        ]
    )
    strict_data_session.commit()

    bar = SqlAlchemyHistoricalDailyBars(strict_data_session).bar_for(
        "000001.SZ", date(2024, 1, 4), as_of_time=AS_OF
    )

    assert bar == DailyBar(
        trade_date=date(2024, 1, 4),
        open=Decimal("12"),
        high=Decimal("13"),
        low=Decimal("11"),
        close=Decimal("12"),
        volume=100_000,
        previous_close=Decimal("10"),
    )


@pytest.mark.postgres
def test_daily_bar_reader_fails_closed_when_prior_close_is_not_visible(
    strict_data_session: Session,
) -> None:
    strict_data_session.add(bar_row("current", date(2024, 1, 4), Decimal("12"), "bar-current"))
    strict_data_session.commit()

    with pytest.raises(StrictDataMissingError, match="previous close missing: 000001.SZ"):
        SqlAlchemyHistoricalDailyBars(strict_data_session).bar_for(
            "000001.SZ", date(2024, 1, 4), as_of_time=AS_OF
        )


@pytest.mark.postgres
def test_daily_bar_reader_only_exposes_completed_bar_after_completion_time(
    strict_data_session: Session,
) -> None:
    trade_date = date(2024, 1, 4)
    strict_data_session.add_all(
        [
            bar_row("prior", date(2024, 1, 3), Decimal("10"), "bar-prior"),
            bar_row(
                "completed",
                trade_date,
                Decimal("12"),
                "bar-current",
                datetime.combine(trade_date, time(15), UTC),
            ),
        ]
    )
    strict_data_session.commit()
    reader = SqlAlchemyHistoricalDailyBars(strict_data_session)

    with pytest.raises(StrictDataMissingError, match="daily bar missing: 000001.SZ"):
        reader.bar_for(
            "000001.SZ",
            trade_date,
            as_of_time=datetime.combine(trade_date, time(9), UTC),
        )

    assert reader.bar_for(
        "000001.SZ",
        trade_date,
        as_of_time=datetime.combine(trade_date, time(15), UTC),
    ).close == Decimal("12")


def test_certified_daily_bar_reader_does_not_fall_back_to_an_uncertified_sql_bar() -> None:
    """Execution must use the exact bar selected by an approved PIT snapshot."""
    trade_date = date(2024, 1, 4)
    previous_date = date(2024, 1, 3)
    requested_scope = SnapshotScope(("000001.SZ",), (DataKind.DAILY_BAR_RAW,))
    previous = TemporalRecord(
        "prior",
        DataKind.DAILY_BAR_RAW,
        "000001.SZ",
        datetime.combine(previous_date, time(15), UTC),
        AS_OF,
        AS_OF,
        HASH,
        {"open": "10", "high": "11", "low": "9", "close": "10", "volume": "100000"},
    )

    class CertifiedWarehouse:
        def snapshot(self, *, as_of_time: datetime, scope: object) -> PointInTimeSnapshot:
            assert scope == requested_scope
            return PointInTimeSnapshot(
                as_of_time,
                requested_scope,
                DataGrade.PIT_VERIFIED,
                (previous,),
                (),
                SnapshotQuality(()),
                (),
                "approved-snapshot",
            )

    with pytest.raises(StrictDataMissingError, match="certified daily bar missing: 000001.SZ"):
        CertifiedHistoricalDailyBars(CertifiedWarehouse()).bar_for(
            "000001.SZ", trade_date, as_of_time=AS_OF
        )


def test_snapshot_adapter_rejects_quality_errors_without_leaking_detail() -> None:
    class Warehouse:
        def snapshot(self, *, as_of_time: datetime, scope: object) -> PointInTimeSnapshot:
            return PointInTimeSnapshot(
                as_of_time,
                scope,
                DataGrade.PIT_VERIFIED,
                (),
                (),
                SnapshotQuality(
                    (
                        QualityIssue(
                            "REQUIRED_DATASET_MISSING",
                            QualitySeverity.ERROR,
                            "daily_bar_raw",
                            None,
                            "internal provider message",
                        ),
                    )
                ),
                (),
                "manifest",
            )

    with pytest.raises(BacktestSnapshotQualityError) as raised:
        StrictBacktestSnapshotAdapter(Warehouse()).snapshot(as_of_time=AS_OF, scope=object())

    assert str(raised.value) == "BACKTEST_SNAPSHOT_QUALITY_ERROR"


def test_snapshot_adapter_rejects_missing_required_data_without_quality_issue() -> None:
    class Warehouse:
        def snapshot(self, *, as_of_time: datetime, scope: object) -> PointInTimeSnapshot:
            return PointInTimeSnapshot(
                as_of_time,
                SnapshotScope(required_kinds=(DataKind.DAILY_BAR_RAW,)),
                DataGrade.PIT_VERIFIED,
                (),
                (),
                SnapshotQuality(()),
                (),
                "manifest",
            )

    with pytest.raises(BacktestSnapshotQualityError, match="BACKTEST_SNAPSHOT_QUALITY_ERROR"):
        StrictBacktestSnapshotAdapter(Warehouse()).snapshot(
            as_of_time=AS_OF,
            scope=SnapshotScope(required_kinds=(DataKind.DAILY_BAR_RAW,)),
        )


def test_snapshot_adapter_rejects_research_snapshot_before_decision_can_use_it() -> None:
    requested_scope = SnapshotScope(required_kinds=(DataKind.DAILY_BAR_RAW,))
    daily_bar = TemporalRecord(
        "bar",
        DataKind.DAILY_BAR_RAW,
        "000001.SZ",
        AS_OF,
        AS_OF,
        AS_OF,
        HASH,
        {},
    )

    class Warehouse:
        def snapshot(self, *, as_of_time: datetime, scope: object) -> PointInTimeSnapshot:
            return PointInTimeSnapshot(
                as_of_time,
                requested_scope,
                DataGrade.RESEARCH,
                (daily_bar,),
                (),
                SnapshotQuality(()),
                (),
                "provider-fallback",
            )

    with pytest.raises(BacktestSnapshotQualityError, match="BACKTEST_SNAPSHOT_QUALITY_ERROR"):
        StrictBacktestSnapshotAdapter(Warehouse()).snapshot(
            as_of_time=AS_OF,
            scope=requested_scope,
        )


def test_snapshot_adapter_rejects_future_records_despite_pit_grade() -> None:
    requested_scope = SnapshotScope(required_kinds=(DataKind.DAILY_BAR_RAW,))
    future_bar = TemporalRecord(
        "future-bar",
        DataKind.DAILY_BAR_RAW,
        "000001.SZ",
        AS_OF,
        AS_OF,
        AS_OF.replace(hour=10),
        HASH,
        {},
    )

    class Warehouse:
        def snapshot(self, *, as_of_time: datetime, scope: object) -> PointInTimeSnapshot:
            return PointInTimeSnapshot(
                as_of_time,
                requested_scope,
                DataGrade.PIT_VERIFIED,
                (future_bar,),
                (),
                SnapshotQuality(()),
                (),
                "future-input",
            )

    with pytest.raises(BacktestSnapshotQualityError, match="BACKTEST_SNAPSHOT_QUALITY_ERROR"):
        StrictBacktestSnapshotAdapter(Warehouse()).snapshot(
            as_of_time=AS_OF,
            scope=requested_scope,
        )


def test_snapshot_adapter_rejects_returned_as_of_time_mismatch() -> None:
    requested_scope = SnapshotScope()

    class Warehouse:
        def snapshot(self, *, as_of_time: datetime, scope: object) -> PointInTimeSnapshot:
            return PointInTimeSnapshot(
                as_of_time.replace(hour=10),
                requested_scope,
                DataGrade.PIT_VERIFIED,
                (),
                (),
                SnapshotQuality(()),
                (),
                "manifest",
            )

    with pytest.raises(BacktestSnapshotQualityError, match="BACKTEST_SNAPSHOT_QUALITY_ERROR"):
        StrictBacktestSnapshotAdapter(Warehouse()).snapshot(
            as_of_time=AS_OF,
            scope=requested_scope,
        )


def test_snapshot_adapter_rejects_returned_scope_mismatch() -> None:
    requested_scope = SnapshotScope(required_kinds=(DataKind.DAILY_BAR_RAW,))

    class Warehouse:
        def snapshot(self, *, as_of_time: datetime, scope: object) -> PointInTimeSnapshot:
            return PointInTimeSnapshot(
                as_of_time,
                SnapshotScope(),
                DataGrade.PIT_VERIFIED,
                (),
                (),
                SnapshotQuality(()),
                (),
                "manifest",
            )

    with pytest.raises(BacktestSnapshotQualityError, match="BACKTEST_SNAPSHOT_QUALITY_ERROR"):
        StrictBacktestSnapshotAdapter(Warehouse()).snapshot(
            as_of_time=AS_OF,
            scope=requested_scope,
        )


def calendar_row(
    row_id: str,
    trade_date: date,
    is_open: bool,
    source_record_id: str,
    available_at: datetime = datetime(2024, 1, 1, tzinfo=UTC),
) -> TradingCalendarRow:
    return TradingCalendarRow(
        id=row_id,
        source_record_id=source_record_id,
        exchange="SSE",
        trade_date=trade_date,
        is_open=is_open,
        available_at=available_at,
        source_artifact_hash=row_id[0] * 64,
    )


def bar_row(
    row_id: str,
    trade_date: date,
    close: Decimal,
    source_record_id: str,
    available_at: datetime = datetime(2024, 1, 1, tzinfo=UTC),
) -> DailyBarRawRow:
    return DailyBarRawRow(
        id=row_id,
        source_record_id=source_record_id,
        security_id="000001.SZ",
        trade_date=trade_date,
        open=close,
        high=close + Decimal("1"),
        low=close - Decimal("1"),
        close=close,
        volume=100_000,
        amount=Decimal("1000000"),
        available_at=available_at,
        source_artifact_hash=row_id[0] * 64,
    )
