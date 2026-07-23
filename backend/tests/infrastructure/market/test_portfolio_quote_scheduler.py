from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from _pytest.monkeypatch import MonkeyPatch

from backend.app.infrastructure.market import portfolio_quote_scheduler as scheduler
from backend.app.infrastructure.persistence.models import Base
from backend.app.infrastructure.persistence.portfolio_rows import (
    PortfolioLotProjectionRow,
    PortfolioPositionQuoteRow,
    PortfolioSnapshotProjectionRow,
)


class _Response:
    def __init__(self, text: str) -> None:
        self.text = text


def test_sina_quote_uses_price_field_not_change_percent(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        scheduler.requests,
        "get",
        lambda *args, **kwargs: _Response(
            'var hq_str_s_sz000568="泸州老窖,86.80,1.58,1.85,178874,152262";'
        ),
    )

    prices = scheduler.realtime_prices(("000568.SZ",))

    assert prices == {"000568.SZ": (Decimal("86.80"), "sina_quote")}


def _sessions() -> sessionmaker:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[
            PortfolioSnapshotProjectionRow.__table__,
            PortfolioLotProjectionRow.__table__,
            PortfolioPositionQuoteRow.__table__,
        ],
    )
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions.begin() as session:
        session.add(
            PortfolioSnapshotProjectionRow(
                portfolio_id="default",
                as_of_time=datetime(2026, 7, 23, tzinfo=UTC),
                cash=Decimal("100"),
                equity=Decimal("100"),
            )
        )
        session.add(
            PortfolioLotProjectionRow(
                lot_id="lot-000568",
                batch_id="batch-1",
                portfolio_id="default",
                security_id="000568.SZ",
                security_name="泸州老窖",
                buy_date=None,
                quantity=10,
                available_to_sell=10,
                average_cost=Decimal("80"),
                effective_at=datetime(2026, 7, 23, tzinfo=UTC),
                origin="recorded_trade",
                strategy_book=None,
                entry_score=None,
                initial_risk_per_share=None,
                effective_stop=None,
                highest_close=None,
                add_count=0,
            )
        )
    return sessions


def test_normal_refresh_uses_external_price_without_fixture(monkeypatch: MonkeyPatch) -> None:
    sessions = _sessions()
    monkeypatch.setattr(
        scheduler,
        "realtime_prices",
        lambda symbols: {"000568.SZ": (Decimal("86.80"), "sina_realtime")},
    )

    scheduler.refresh_portfolio_quotes(sessions)

    with sessions() as session:
        quote = session.scalar(select(PortfolioPositionQuoteRow))
        projection = session.get(PortfolioSnapshotProjectionRow, "default")
    assert quote is not None
    assert quote.price == Decimal("86.80")
    assert quote.source == "sina_realtime"
    assert projection is not None
    assert projection.equity == Decimal("968.00")


def test_normal_refresh_preserves_last_external_quote_when_provider_fails(
    monkeypatch: MonkeyPatch,
) -> None:
    sessions = _sessions()
    with sessions.begin() as session:
        session.add(
            PortfolioPositionQuoteRow(
                portfolio_id="default",
                security_id="000568.SZ",
                observed_at=datetime(2026, 7, 22, tzinfo=UTC),
                price=Decimal("85.00"),
                source="sina_realtime",
            )
        )
    monkeypatch.setattr(scheduler, "realtime_prices", lambda symbols: {})

    scheduler.refresh_portfolio_quotes(sessions)

    with sessions() as session:
        quotes = session.scalars(select(PortfolioPositionQuoteRow)).all()
        projection = session.get(PortfolioSnapshotProjectionRow, "default")
    assert len(quotes) == 1
    assert projection is not None
    assert projection.equity == Decimal("950.00")


def test_normal_refresh_rejects_zero_external_price(monkeypatch: MonkeyPatch) -> None:
    sessions = _sessions()
    with sessions.begin() as session:
        session.add(
            PortfolioPositionQuoteRow(
                portfolio_id="default",
                security_id="000568.SZ",
                observed_at=datetime(2026, 7, 22, tzinfo=UTC),
                price=Decimal("85.00"),
                source="sina_quote",
            )
        )
    monkeypatch.setattr(
        scheduler,
        "realtime_prices",
        lambda symbols: {"000568.SZ": (Decimal("0"), "sina_quote")},
    )

    scheduler.refresh_portfolio_quotes(sessions)

    with sessions() as session:
        quotes = session.scalars(select(PortfolioPositionQuoteRow)).all()
        projection = session.get(PortfolioSnapshotProjectionRow, "default")
    assert len(quotes) == 1
    assert projection is not None
    assert projection.equity == Decimal("950.00")
