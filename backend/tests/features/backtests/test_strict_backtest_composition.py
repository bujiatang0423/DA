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
from backend.app.features.backtests.execution import DailyBar
from backend.app.features.backtests.models import (
    BacktestRequest,
    OrderIntent,
    OrderSide,
    StrategyGroup,
)
from backend.app.features.backtests.ports import (
    BacktestDecision,
    BacktestDecisionContext,
    BacktestSnapshotQualityError,
)
from backend.app.infrastructure.persistence.strict_pit_rows import (
    FeeScheduleRow,
    SecurityStatusDailyRow,
)


OPEN = datetime(2020, 6, 2, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
HASH = "a" * 64


@pytest.fixture
def strict_execution_session(postgres_engine: Engine) -> Iterator[Session]:
    for table in (SecurityStatusDailyRow.__table__, FeeScheduleRow.__table__):
        table.create(postgres_engine, checkfirst=True)
    with postgres_engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE security_status_daily, fee_schedules CASCADE"))
    session = sessionmaker(bind=postgres_engine, expire_on_commit=False)()
    try:
        session.add_all([status_row(), fee_row()])
        session.commit()
        yield session
    finally:
        session.rollback()
        session.close()
        with postgres_engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE security_status_daily, fee_schedules CASCADE"))


@pytest.mark.postgres
def test_strict_engine_uses_pit_fee_status_and_limit_for_real_trade(
    strict_execution_session: Session,
) -> None:
    engine = build_strict_backtest_engine(
        Days(), Warehouse(), Decisions(), Bars(), strict_execution_session
    )

    result = engine.run(request(), StrategyGroup.A)

    assert len(result.trades) == 1
    assert result.trades[0]["fee_schedule_id"] == "fee-2020"
    assert result.trades[0]["fee_schedule_hash"] == HASH
    assert result.trades[0]["fee"] == "5.01"


@pytest.mark.postgres
def test_strict_engine_rejects_the_same_open_under_a_ten_percent_board(
    strict_execution_session: Session,
) -> None:
    status = strict_execution_session.get(SecurityStatusDailyRow, "status-2020")
    assert status is not None
    status.price_limit_pct = Decimal("0.10")
    strict_execution_session.commit()
    engine = build_strict_backtest_engine(
        Days(), Warehouse(), Decisions(), Bars(), strict_execution_session
    )

    result = engine.run(request(), StrategyGroup.A)

    assert result.trades == []


@pytest.mark.postgres
def test_strict_engine_rejects_provider_fallback_before_pit_result(
    strict_execution_session: Session,
) -> None:
    engine = build_strict_backtest_engine(
        Days(), ResearchWarehouse(), Decisions(), Bars(), strict_execution_session
    )

    with pytest.raises(BacktestSnapshotQualityError, match="BACKTEST_SNAPSHOT_QUALITY_ERROR"):
        engine.run(request(), StrategyGroup.A)


class Days:
    def between(self, start_date: date, end_date: date) -> tuple[date, ...]:
        return date(2020, 6, 1), date(2020, 6, 2)


class Warehouse:
    def snapshot(self, *, as_of_time: datetime, scope: object) -> PointInTimeSnapshot:
        assert isinstance(scope, SnapshotScope)
        return PointInTimeSnapshot(
            as_of_time,
            scope,
            DataGrade.PIT_VERIFIED,
            required_records(as_of_time),
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


class Decisions:
    def decide(self, context: BacktestDecisionContext) -> BacktestDecision:
        return BacktestDecision((order(),), {})


class Bars:
    def bar_for(
        self,
        security_id: str,
        trade_date: date,
        *,
        as_of_time: datetime,
    ) -> DailyBar:
        assert (security_id, trade_date) == ("PAST_DELISTED.SZ", date(2020, 6, 2))
        assert as_of_time == datetime(2020, 6, 2, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        return DailyBar(
            trade_date=trade_date,
            open=Decimal("11"),
            high=Decimal("11"),
            low=Decimal("10.5"),
            close=Decimal("10.8"),
            volume=100_000,
            previous_close=Decimal("10"),
        )


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
