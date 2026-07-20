from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from zoneinfo import ZoneInfo

from backend.app.contracts.grades import DataGrade
from backend.app.core.market.pit_models import (
    DataKind,
    PointInTimeSnapshot,
    SnapshotQuality,
    SnapshotScope,
    TemporalRecord,
)
from backend.app.bootstrap.backtest_composition import build_strict_backtest_engine
from backend.app.features.backtests.models import (
    BacktestRequest,
    OrderIntent,
    OrderSide,
    StrategyGroup,
)
from backend.app.features.backtests.execution import ExecutionSimulator, FilledAttempt
from backend.app.features.backtests.ports import (
    BacktestDecision,
    BacktestDecisionContext,
    BacktestSnapshotQualityError,
)
from backend.app.features.backtests.strict_execution import (
    CertifiedExecutionInputs,
    StrictExecutionSimulator,
)
from backend.app.infrastructure.market.strict_reader import SqlStrictRecordReader
from backend.app.infrastructure.persistence.strict_pit_rows import (
    DailyBarRawRow,
    FeeScheduleRow,
    SecurityStatusDailyRow,
)


OPEN = datetime(2020, 6, 2, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
HASH = "a" * 64


@pytest.fixture
def strict_execution_session(postgres_engine: Engine) -> Iterator[Session]:
    for table in (
        DailyBarRawRow.__table__,
        SecurityStatusDailyRow.__table__,
        FeeScheduleRow.__table__,
    ):
        table.create(postgres_engine, checkfirst=True)
    with postgres_engine.begin() as connection:
        connection.execute(
            text("TRUNCATE TABLE daily_bars_raw, security_status_daily, fee_schedules CASCADE")
        )
    session = sessionmaker(bind=postgres_engine, expire_on_commit=False)()
    try:
        session.add_all([status_row(), fee_row()])
        session.commit()
        yield session
    finally:
        session.rollback()
        session.close()
        with postgres_engine.begin() as connection:
            connection.execute(
                text("TRUNCATE TABLE daily_bars_raw, security_status_daily, fee_schedules CASCADE")
            )


@pytest.mark.postgres
def test_strict_engine_uses_pit_fee_status_and_limit_for_real_trade(
    strict_execution_session: Session,
) -> None:
    engine = build_strict_backtest_engine(Days(), Warehouse(), Decisions())

    result = engine.run(request(), StrategyGroup.A)

    assert len(result.trades) == 1
    assert result.trades[0]["fee_schedule_id"] == "fee-2020"
    assert result.trades[0]["fee_schedule_hash"] == HASH
    assert result.trades[0]["fee"] == "5.01"


@pytest.mark.postgres
def test_strict_engine_rejects_the_same_open_under_a_ten_percent_board(
    strict_execution_session: Session,
) -> None:
    engine = build_strict_backtest_engine(
        Days(), Warehouse(price_limit_pct=Decimal("0.10")), Decisions()
    )

    result = engine.run(request(), StrategyGroup.A)

    assert result.trades == []


@pytest.mark.postgres
def test_strict_engine_rejects_provider_fallback_before_pit_result(
    strict_execution_session: Session,
) -> None:
    engine = build_strict_backtest_engine(Days(), ResearchWarehouse(), Decisions())

    with pytest.raises(BacktestSnapshotQualityError, match="BACKTEST_SNAPSHOT_QUALITY_ERROR"):
        engine.run(request(), StrategyGroup.A)


@pytest.mark.postgres
def test_strict_engine_rejects_future_snapshot_record_before_decision_or_result(
    strict_execution_session: Session,
) -> None:
    decisions: list[BacktestDecisionContext] = []

    class FutureWarehouse(Warehouse):
        def snapshot(self, *, as_of_time: datetime, scope: object) -> PointInTimeSnapshot:
            snapshot = super().snapshot(as_of_time=as_of_time, scope=scope)
            future = TemporalRecord(
                "future-bar",
                DataKind.DAILY_BAR_RAW,
                "market",
                as_of_time,
                as_of_time,
                as_of_time.replace(hour=16),
                HASH,
                {},
            )
            return PointInTimeSnapshot(
                snapshot.as_of_time,
                snapshot.scope,
                snapshot.data_grade,
                snapshot.market_inputs + (future,),
                snapshot.security_observations,
                snapshot.quality,
                snapshot.lineage,
                snapshot.manifest_hash,
            )

    class RecordingDecisions:
        def decide(self, context: BacktestDecisionContext) -> BacktestDecision:
            decisions.append(context)
            return BacktestDecision((), {})

    engine = build_strict_backtest_engine(Days(), FutureWarehouse(), RecordingDecisions())

    with pytest.raises(BacktestSnapshotQualityError, match="BACKTEST_SNAPSHOT_QUALITY_ERROR"):
        engine.run(request(), StrategyGroup.A)

    assert decisions == []


@pytest.mark.postgres
def test_sql_reader_keeps_false_status_flags_false_for_a_fill(
    strict_execution_session: Session,
) -> None:
    close_time = OPEN.replace(hour=15)
    strict_execution_session.add_all(
        [
            daily_bar_row("bar-prior", date(2020, 6, 1), Decimal("10"), OPEN),
            daily_bar_row("bar-current", date(2020, 6, 2), Decimal("11"), close_time),
        ]
    )
    strict_execution_session.commit()

    class SqlReaderWarehouse:
        def snapshot(self, *, as_of_time: datetime, scope: object) -> PointInTimeSnapshot:
            assert isinstance(scope, SnapshotScope)
            records, lineage, issues = SqlStrictRecordReader(strict_execution_session).read(
                as_of_time=as_of_time,
                scope=scope,
            )
            return PointInTimeSnapshot(
                as_of_time,
                scope,
                DataGrade.PIT_VERIFIED,
                records,
                (),
                SnapshotQuality(issues),
                lineage,
                "sql-reader",
            )

    result = StrictExecutionSimulator(
        ExecutionSimulator(),
        CertifiedExecutionInputs(SqlReaderWarehouse()),
    ).attempt(
        order(),
        security_id="PAST_DELISTED.SZ",
        trade_date=date(2020, 6, 2),
        exchange="SZSE",
        asset_type="stock",
        as_of_time=close_time,
    )

    assert isinstance(result, FilledAttempt)


def daily_bar_row(
    row_id: str,
    trade_date: date,
    close: Decimal,
    available_at: datetime,
) -> DailyBarRawRow:
    return DailyBarRawRow(
        id=row_id,
        source_record_id=row_id,
        security_id="PAST_DELISTED.SZ",
        trade_date=trade_date,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=100_000,
        amount=Decimal("1000000"),
        available_at=available_at,
        source_artifact_hash=HASH,
    )


class Days:
    def between(self, start_date: date, end_date: date) -> tuple[date, ...]:
        return date(2020, 6, 1), date(2020, 6, 2)


class Warehouse:
    def __init__(self, price_limit_pct: Decimal = Decimal("0.20")) -> None:
        self._price_limit_pct = price_limit_pct

    def snapshot(self, *, as_of_time: datetime, scope: object) -> PointInTimeSnapshot:
        assert isinstance(scope, SnapshotScope)
        records = required_records(as_of_time)
        if set(scope.required_kinds) == {
            DataKind.DAILY_BAR_RAW,
            DataKind.SECURITY_STATUS,
            DataKind.FEE_SCHEDULE,
        }:
            records = execution_records(as_of_time, self._price_limit_pct)
        return PointInTimeSnapshot(
            as_of_time,
            scope,
            DataGrade.PIT_VERIFIED,
            records,
            (),
            SnapshotQuality(()),
            (),
            "manifest",
        )


class ResearchWarehouse(Warehouse):
    def snapshot(self, *, as_of_time: datetime, scope: object) -> PointInTimeSnapshot:
        snapshot = super().snapshot(as_of_time=as_of_time, scope=scope)
        return PointInTimeSnapshot(
            snapshot.as_of_time,
            snapshot.scope,
            DataGrade.RESEARCH,
            snapshot.market_inputs,
            snapshot.security_observations,
            snapshot.quality,
            snapshot.lineage,
            snapshot.manifest_hash,
        )


def required_records(as_of_time: datetime) -> tuple[TemporalRecord, ...]:
    return tuple(
        TemporalRecord(
            f"record-{kind.value}",
            kind,
            "market",
            as_of_time,
            as_of_time,
            as_of_time,
            HASH,
            {},
        )
        for kind in DataKind
    )


def execution_records(
    as_of_time: datetime,
    price_limit_pct: Decimal,
) -> tuple[TemporalRecord, ...]:
    def item(
        record_id: str, kind: DataKind, entity: str, payload: dict[str, object]
    ) -> TemporalRecord:
        return TemporalRecord(
            record_id, kind, entity, as_of_time, as_of_time, as_of_time, HASH, payload
        )

    return (
        item(
            "bar-previous",
            DataKind.DAILY_BAR_RAW,
            "PAST_DELISTED.SZ",
            {
                "trade_date": "2020-06-01",
                "open": "10",
                "high": "10",
                "low": "10",
                "close": "10",
                "volume": "100000",
            },
        ),
        item(
            "bar-current",
            DataKind.DAILY_BAR_RAW,
            "PAST_DELISTED.SZ",
            {
                "trade_date": "2020-06-02",
                "open": "11",
                "high": "11",
                "low": "10.5",
                "close": "10.8",
                "volume": "100000",
            },
        ),
        item(
            "status-2020",
            DataKind.SECURITY_STATUS,
            "PAST_DELISTED.SZ",
            {
                "trade_date": "2020-06-02",
                "is_st": False,
                "is_suspended": False,
                "board": "growth",
                "price_limit_pct": str(price_limit_pct),
            },
        ),
        item(
            "fee-2020",
            DataKind.FEE_SCHEDULE,
            "SZSE:stock",
            {
                "exchange": "SZSE",
                "asset_type": "stock",
                "effective_from": "2020-01-01",
                "commission_rate": "0.0003",
                "minimum_commission": "5",
                "stamp_tax_sell_rate": "0.001",
                "transfer_rate": "0.00001",
            },
        ),
    )


class Decisions:
    def decide(self, context: BacktestDecisionContext) -> BacktestDecision:
        return BacktestDecision((order(),), {})


def request() -> BacktestRequest:
    return BacktestRequest(
        strategy_version="v2.12",
        start_date=date(2020, 6, 1),
        end_date=date(2020, 6, 2),
        initial_cash=Decimal("10000"),
        groups=[StrategyGroup.A],
    )


def order() -> OrderIntent:
    return OrderIntent(
        order_id="order-1",
        security_id="PAST_DELISTED.SZ",
        side=OrderSide.BUY,
        quantity=100,
        signal_date=date(2020, 6, 1),
        earliest_trade_date=date(2020, 6, 2),
        strategy_book="core",
        priority=100,
        signal_close=Decimal("11"),
        max_participation_rate=Decimal("1"),
    )


def status_row() -> SecurityStatusDailyRow:
    return SecurityStatusDailyRow(
        id="status-2020",
        source_record_id="status-2020",
        security_id="PAST_DELISTED.SZ",
        trade_date=date(2020, 6, 2),
        is_st=False,
        is_suspended=False,
        board="growth",
        price_limit_pct=Decimal("0.20"),
        available_at=OPEN,
        source_artifact_hash=HASH,
    )


def fee_row() -> FeeScheduleRow:
    return FeeScheduleRow(
        id="fee-2020-row",
        source_record_id="fee-2020",
        effective_from=date(2020, 1, 1),
        effective_to=None,
        exchange="SZSE",
        asset_type="stock",
        commission_rate=Decimal("0.0003"),
        minimum_commission=Decimal("5"),
        stamp_tax_sell_rate=Decimal("0.001"),
        transfer_rate=Decimal("0.00001"),
        available_at=OPEN,
        source_artifact_hash=HASH,
    )
