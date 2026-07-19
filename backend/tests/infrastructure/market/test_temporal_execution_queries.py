from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.infrastructure.market.strict_queries import (
    StrictDataMissingError,
    TemporalExecutionQueries,
)
from backend.app.infrastructure.persistence.strict_pit_rows import FeeScheduleRow


AS_OF = datetime(2020, 6, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def temporal_execution_session(postgres_engine: Engine) -> Iterator[Session]:
    FeeScheduleRow.__table__.create(postgres_engine, checkfirst=True)
    with postgres_engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE fee_schedules CASCADE"))
    session = sessionmaker(bind=postgres_engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        with postgres_engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE fee_schedules CASCADE"))


@pytest.mark.postgres
def test_fee_schedule_uses_trade_date_and_available_version(
    temporal_execution_session: Session,
) -> None:
    temporal_execution_session.add_all(
        [
            fee("fee-2020", date(2020, 1, 1), None, available_at=AS_OF),
            fee(
                "fee-future-observation",
                date(2020, 1, 1),
                None,
                available_at=datetime(2020, 6, 2, tzinfo=UTC),
            ),
        ]
    )
    temporal_execution_session.commit()

    result = TemporalExecutionQueries(temporal_execution_session).fee_schedule(
        trade_date=date(2020, 6, 1),
        exchange="SSE",
        asset_type="stock",
        as_of_time=AS_OF,
    )

    assert result.record_id == "fee-2020"
    assert result.stamp_tax_sell_rate == Decimal("0.001")
    assert result.minimum_commission == Decimal("5")


@pytest.mark.postgres
def test_fee_schedule_missing_at_historical_cutoff_fails_closed(
    temporal_execution_session: Session,
) -> None:
    temporal_execution_session.add(fee("fee-2020", date(2020, 1, 1), None, available_at=AS_OF))
    temporal_execution_session.commit()

    with pytest.raises(StrictDataMissingError, match="fee schedule missing"):
        TemporalExecutionQueries(temporal_execution_session).fee_schedule(
            trade_date=date(2000, 1, 1),
            exchange="SSE",
            asset_type="stock",
            as_of_time=datetime(2000, 1, 1, tzinfo=UTC),
        )


def fee(
    record_id: str,
    effective_from: date,
    effective_to: date | None,
    *,
    available_at: datetime,
) -> FeeScheduleRow:
    return FeeScheduleRow(
        id=f"row-{record_id}",
        source_record_id=record_id,
        effective_from=effective_from,
        effective_to=effective_to,
        exchange="SSE",
        asset_type="stock",
        commission_rate=Decimal("0.0003"),
        minimum_commission=Decimal("5"),
        stamp_tax_sell_rate=Decimal("0.001"),
        transfer_rate=Decimal("0.00001"),
        available_at=available_at,
        source_artifact_hash="a" * 64,
    )
