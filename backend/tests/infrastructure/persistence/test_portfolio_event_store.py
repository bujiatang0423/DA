from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.portfolio.models import (
    CorrectionSnapshot,
    FillSide,
    ManualFillCommand,
    StrategyBook,
)
from backend.app.core.portfolio.writer import AuditedPortfolioWriter
from backend.app.infrastructure.persistence.portfolio_repository import (
    InsufficientSellableQuantity,
    SqlPortfolioEventStore,
)
from backend.app.infrastructure.persistence.portfolio_rows import (
    PortfolioAuditEventRow,
    PortfolioLotProjectionRow,
    PortfolioSnapshotProjectionRow,
    PortfolioVersionRow,
)
from backend.app.ports.portfolio import ConcurrentPortfolioUpdate
from backend.tests.features.holdings.factories import portfolio_snapshot


@pytest.fixture
def portfolio_sessions() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (
        PortfolioVersionRow.__table__,
        PortfolioSnapshotProjectionRow.__table__,
        PortfolioLotProjectionRow.__table__,
        PortfolioAuditEventRow.__table__,
    ):
        table.create(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions.begin() as session:
        session.add(PortfolioVersionRow(portfolio_id="default", version=7))
        session.add(
            PortfolioSnapshotProjectionRow(
                portfolio_id="default",
                as_of_time=datetime(2026, 7, 17, 7, 0, tzinfo=UTC),
                cash=Decimal("350000"),
                equity=Decimal("1000000"),
            )
        )
        session.add(
            PortfolioLotProjectionRow(
                lot_id="lot-1",
                batch_id="default",
                portfolio_id="default",
                security_id="000001.SZ",
                buy_date=date(2026, 7, 16),
                quantity=500,
                available_to_sell=400,
                average_cost=Decimal("10.20"),
                effective_at=datetime(2026, 7, 16, 7, 0, tzinfo=UTC),
                origin="recorded_trade",
                strategy_book="core",
                entry_score=Decimal("60"),
                initial_risk_per_share=Decimal("1"),
                effective_stop=Decimal("9.50"),
                highest_close=Decimal("11"),
                add_count=0,
            )
        )
    return sessions


def test_manual_sell_uses_actual_price_fee_and_sellable_quantity(
    portfolio_sessions: sessionmaker[Session],
) -> None:
    writer = AuditedPortfolioWriter(SqlPortfolioEventStore(portfolio_sessions))
    command = ManualFillCommand(
        portfolio_id="default",
        security_id="000001.SZ",
        side=FillSide.SELL,
        quantity=100,
        price=Decimal("10.35"),
        fee=Decimal("5.00"),
        filled_at=datetime(2026, 7, 17, 7, 1, tzinfo=UTC),
        strategy_book=StrategyBook.CORE,
    )

    result = writer.record_manual_fill(command, expected_version=7)

    assert result.version == 8
    assert result.cash == Decimal("351030.00")
    assert result.equity == Decimal("999995.00")
    assert result.lots[0].quantity == 400
    assert result.lots[0].available_to_sell == 300
    with portfolio_sessions() as session:
        event = session.scalar(select(PortfolioAuditEventRow))
        assert event is not None
        assert event.event_type == "manual_fill"
        assert event.expected_version == 7
        assert event.resulting_version == 8


def test_manual_buy_is_t_plus_one_locked(
    portfolio_sessions: sessionmaker[Session],
) -> None:
    writer = AuditedPortfolioWriter(SqlPortfolioEventStore(portfolio_sessions))
    command = ManualFillCommand(
        portfolio_id="default",
        security_id="600000.SH",
        side=FillSide.BUY,
        quantity=100,
        price=Decimal("10.00"),
        fee=Decimal("5.00"),
        filled_at=datetime(2026, 7, 17, 7, 1, tzinfo=UTC),
        strategy_book=StrategyBook.CORE,
    )

    result = writer.record_manual_fill(command, expected_version=7)

    bought = next(lot for lot in result.lots if lot.security_id == "600000.SH")
    assert bought.quantity == 100
    assert bought.available_to_sell == 0
    assert bought.average_cost == Decimal("10.05")
    assert result.cash == Decimal("348995.00")


def test_portfolio_event_store_rejects_stale_versions(
    portfolio_sessions: sessionmaker[Session],
) -> None:
    writer = AuditedPortfolioWriter(SqlPortfolioEventStore(portfolio_sessions))
    command = ManualFillCommand(
        portfolio_id="default",
        security_id="000001.SZ",
        side=FillSide.SELL,
        quantity=1,
        price=Decimal("10"),
        fee=Decimal("0"),
        filled_at=datetime(2026, 7, 17, 7, 1, tzinfo=UTC),
        strategy_book=StrategyBook.CORE,
    )

    with pytest.raises(ConcurrentPortfolioUpdate, match="expected version 6"):
        writer.record_manual_fill(command, expected_version=6)


def test_position_correction_replaces_projection_with_an_audit_event(
    portfolio_sessions: sessionmaker[Session],
) -> None:
    writer = AuditedPortfolioWriter(SqlPortfolioEventStore(portfolio_sessions))
    fixture = portfolio_snapshot()
    correction = CorrectionSnapshot(
        portfolio_id="default",
        as_of_time=fixture.as_of_time,
        cash=fixture.cash,
        equity=fixture.equity,
        lots=fixture.lots,
    )

    result = writer.replace_positions_for_correction(
        correction,
        expected_version=7,
        reason="核对券商对账单后修正数量",
    )

    assert result.version == 8
    assert result.lots == fixture.lots
    with portfolio_sessions() as session:
        event = session.scalar(select(PortfolioAuditEventRow))
        assert event is not None
        assert event.event_type == "position_correction"
        assert event.reason == "核对券商对账单后修正数量"


def test_manual_sell_rejects_quantity_that_is_not_sellable(
    portfolio_sessions: sessionmaker[Session],
) -> None:
    writer = AuditedPortfolioWriter(SqlPortfolioEventStore(portfolio_sessions))
    command = ManualFillCommand(
        portfolio_id="default",
        security_id="000001.SZ",
        side=FillSide.SELL,
        quantity=401,
        price=Decimal("10"),
        fee=Decimal("0"),
        filled_at=datetime(2026, 7, 17, 7, 1, tzinfo=UTC),
        strategy_book=StrategyBook.CORE,
    )

    with pytest.raises(InsufficientSellableQuantity, match="available"):
        writer.record_manual_fill(command, expected_version=7)

    with portfolio_sessions() as session:
        version = session.get(PortfolioVersionRow, "default")
        assert version is not None
        assert version.version == 7


@pytest.mark.postgres
def test_portfolio_event_store_round_trips_on_postgresql(postgres_engine: Engine) -> None:
    sessions = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    portfolio_id = "portfolio-event-store-postgres"
    with sessions.begin() as session:
        session.add(PortfolioVersionRow(portfolio_id=portfolio_id, version=7))
        session.add(
            PortfolioSnapshotProjectionRow(
                portfolio_id=portfolio_id,
                as_of_time=datetime(2026, 7, 17, 7, 0, tzinfo=UTC),
                cash=Decimal("350000"),
                equity=Decimal("1000000"),
            )
        )
        session.add(
            PortfolioLotProjectionRow(
                lot_id="lot-postgres",
                batch_id="default",
                portfolio_id=portfolio_id,
                security_id="000001.SZ",
                buy_date=date(2026, 7, 16),
                quantity=500,
                available_to_sell=400,
                average_cost=Decimal("10.20"),
                effective_at=datetime(2026, 7, 16, 7, 0, tzinfo=UTC),
                origin="recorded_trade",
                strategy_book="core",
                entry_score=Decimal("60"),
                initial_risk_per_share=Decimal("1"),
                effective_stop=Decimal("9.50"),
                highest_close=Decimal("11"),
                add_count=0,
            )
        )
    writer = AuditedPortfolioWriter(SqlPortfolioEventStore(sessions))
    command = ManualFillCommand(
        portfolio_id=portfolio_id,
        security_id="000001.SZ",
        side=FillSide.SELL,
        quantity=100,
        price=Decimal("10.35"),
        fee=Decimal("5.00"),
        filled_at=datetime(2026, 7, 17, 7, 1, tzinfo=UTC),
        strategy_book=StrategyBook.CORE,
    )

    result = writer.record_manual_fill(command, expected_version=7)

    assert result.version == 8
    assert result.lots[0].quantity == 400
    with sessions() as session:
        event = session.scalar(
            select(PortfolioAuditEventRow).where(
                PortfolioAuditEventRow.portfolio_id == portfolio_id
            )
        )
        assert event is not None
        assert event.event_type == "manual_fill"
