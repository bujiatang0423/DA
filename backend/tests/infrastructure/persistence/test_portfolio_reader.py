from datetime import datetime, UTC
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.infrastructure.persistence.legacy_rows import (
    LegacyImportBatchRow,
    OpeningPositionRow,
)
from backend.app.infrastructure.persistence.models import Base
from backend.app.infrastructure.persistence.portfolio_reader import SqlPortfolioReader
from backend.app.infrastructure.persistence.portfolio_rows import (
    PortfolioLotProjectionRow,
    PortfolioSnapshotRevisionRow,
    PortfolioSnapshotProjectionRow,
    PortfolioVersionRow,
)


def _factory() -> sessionmaker:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[
            LegacyImportBatchRow.__table__,
            OpeningPositionRow.__table__,
            PortfolioVersionRow.__table__,
            PortfolioSnapshotProjectionRow.__table__,
            PortfolioLotProjectionRow.__table__,
            PortfolioSnapshotRevisionRow.__table__,
        ],
    )
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_reader_filters_legacy_rows_and_applies_t_plus_one() -> None:
    sessions = _factory()
    effective = datetime(2026, 7, 16, 15, 0, tzinfo=UTC)
    with sessions.begin() as session:
        session.add(
            LegacyImportBatchRow(
                id="batch-1",
                source_root="legacy",
                source_git_state="clean",
                imported_at=effective,
                effective_at=effective,
                portfolio_id="p",
                manifest_sha256="a" * 64,
                quality_report_json="{}",
            )
        )
        session.add(
            OpeningPositionRow(
                batch_id="batch-1",
                portfolio_id="p",
                security_id="600000",
                quantity=100,
                inherited_unit_cost=Decimal("10.5"),
                effective_at=effective,
                origin="legacy_opening_balance",
                source_row_hash="b" * 64,
            )
        )

    same_day = SqlPortfolioReader(sessions).snapshot(portfolio_id="p", as_of_time=effective)
    assert same_day.lots[0].origin.value == "legacy_opening_balance"
    assert same_day.lots[0].batch_id == "batch-1"
    assert same_day.lots[0].available_to_sell == 0
    next_day = SqlPortfolioReader(sessions).snapshot(
        portfolio_id="p", as_of_time=datetime(2026, 7, 17, 9, 30, tzinfo=UTC)
    )
    assert next_day.lots[0].available_to_sell == 100


def test_projection_is_point_in_time_and_has_version_and_cash() -> None:
    sessions = _factory()
    t0 = datetime(2026, 7, 15, 9, 30, tzinfo=UTC)
    with sessions.begin() as session:
        session.add(PortfolioVersionRow(portfolio_id="p", version=4))
        session.add(
            PortfolioSnapshotProjectionRow(
                portfolio_id="p", as_of_time=t0, cash=Decimal("100"), equity=Decimal("1100")
            )
        )
        session.add(
            PortfolioLotProjectionRow(
                lot_id="lot-1",
                portfolio_id="p",
                security_id="000001",
                quantity=10,
                available_to_sell=10,
                average_cost=Decimal("100"),
                effective_at=t0,
                origin="recorded_trade",
                strategy_book="core",
                entry_score=None,
                initial_risk_per_share=None,
                effective_stop=None,
                highest_close=None,
                add_count=0,
            )
        )
    snap = SqlPortfolioReader(sessions).snapshot(
        portfolio_id="p", as_of_time=datetime(2026, 7, 16, 9, 30, tzinfo=UTC)
    )
    assert snap.version == 4
    assert snap.cash == Decimal("100")
    assert snap.lots[0].available_to_sell == 10
    before = SqlPortfolioReader(sessions).snapshot(portfolio_id="p", as_of_time=t0.replace(day=14))
    assert before.lots == () and before.cash == Decimal("0")
