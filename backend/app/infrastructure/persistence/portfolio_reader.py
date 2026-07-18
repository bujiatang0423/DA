"""SQL-backed point-in-time portfolio reader."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.portfolio.models import (
    PortfolioLot,
    PortfolioSnapshot,
    PositionOrigin,
    StrategyBook,
)
from .legacy_rows import LegacyImportBatchRow, OpeningPositionRow
from .portfolio_rows import (
    PortfolioLotProjectionRow,
    PortfolioSnapshotRevisionRow,
    PortfolioSnapshotProjectionRow,
    PortfolioVersionRow,
)


class SqlPortfolioReader:
    """Read the latest committed portfolio state that is visible at ``as_of_time``.

    Opening positions are deliberately retained as ``legacy_opening_balance`` lots;
    they are never converted into synthetic trades.  Projection rows take precedence
    when present, while legacy rows provide the one-time imported opening state.
    """

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def snapshot(self, *, portfolio_id: str, as_of_time: datetime) -> PortfolioSnapshot:
        with self._session_factory() as session:
            return read_portfolio_snapshot(session, portfolio_id, as_of_time)


def read_portfolio_snapshot(
    session: Session,
    portfolio_id: str,
    as_of_time: datetime,
) -> PortfolioSnapshot:
    revision = session.scalar(
        select(PortfolioSnapshotRevisionRow)
        .where(
            PortfolioSnapshotRevisionRow.portfolio_id == portfolio_id,
            PortfolioSnapshotRevisionRow.as_of_time <= as_of_time,
            PortfolioSnapshotRevisionRow.recorded_at <= as_of_time,
        )
        .order_by(
            PortfolioSnapshotRevisionRow.as_of_time.desc(),
            PortfolioSnapshotRevisionRow.version.desc(),
        )
    )
    if revision is not None:
        return PortfolioSnapshot(
            portfolio_id=portfolio_id,
            as_of_time=as_of_time,
            version=revision.version,
            cash=_decimal(revision.cash),
            equity=_decimal(revision.equity),
            lots=tuple(_revision_lot(row, as_of_time) for row in revision.lots),
        )
    version = session.scalar(
        select(PortfolioVersionRow.version).where(PortfolioVersionRow.portfolio_id == portfolio_id)
    )
    projection = session.scalar(
        select(PortfolioSnapshotProjectionRow)
        .where(
            PortfolioSnapshotProjectionRow.portfolio_id == portfolio_id,
            PortfolioSnapshotProjectionRow.as_of_time <= as_of_time,
        )
        .order_by(PortfolioSnapshotProjectionRow.as_of_time.desc())
    )
    lot_rows = session.scalars(
        select(PortfolioLotProjectionRow)
        .where(
            PortfolioLotProjectionRow.portfolio_id == portfolio_id,
            PortfolioLotProjectionRow.effective_at <= as_of_time,
        )
        .order_by(PortfolioLotProjectionRow.effective_at, PortfolioLotProjectionRow.lot_id)
    ).all()

    lots = [_projection_lot(row, as_of_time) for row in lot_rows]
    if not lot_rows:
        lots.extend(_opening_lots(session, portfolio_id, as_of_time))

    cash = Decimal("0") if projection is None else _decimal(projection.cash)
    equity = Decimal("0") if projection is None else _decimal(projection.equity)
    return PortfolioSnapshot(
        portfolio_id=portfolio_id,
        as_of_time=as_of_time,
        version=int(version or 0),
        cash=cash,
        equity=equity,
        lots=tuple(lots),
    )


def _opening_lots(session: Session, portfolio_id: str, as_of_time: datetime) -> list[PortfolioLot]:
    rows = session.scalars(
        select(OpeningPositionRow)
        .join(LegacyImportBatchRow, OpeningPositionRow.batch_id == LegacyImportBatchRow.id)
        .where(
            OpeningPositionRow.portfolio_id == portfolio_id,
            OpeningPositionRow.effective_at <= as_of_time,
            LegacyImportBatchRow.effective_at <= as_of_time,
        )
        .order_by(OpeningPositionRow.effective_at, OpeningPositionRow.id)
    ).all()
    return [
        PortfolioLot(
            lot_id=f"legacy:{row.batch_id}:{row.id}",
            security_id=row.security_id,
            quantity=row.quantity,
            available_to_sell=row.quantity if as_of_time.date() > row.effective_at.date() else 0,
            average_cost=_decimal(row.inherited_unit_cost),
            effective_at=row.effective_at,
            origin=PositionOrigin.LEGACY_OPENING_BALANCE,
            strategy_book=None,
            entry_score=None,
            initial_risk_per_share=None,
            effective_stop=None,
            highest_close=None,
            add_count=0,
            batch_id="legacy",
            buy_date=None,
        )
        for row in rows
        if row.quantity > 0
    ]


def _projection_lot(row: PortfolioLotProjectionRow, as_of_time: datetime) -> PortfolioLot:
    available = int(row.available_to_sell)
    if as_of_time.date() <= row.effective_at.date():
        available = 0
    return PortfolioLot(
        lot_id=row.lot_id,
        security_id=row.security_id,
        quantity=int(row.quantity),
        available_to_sell=max(0, min(int(row.quantity), available)),
        average_cost=_decimal(row.average_cost),
        effective_at=row.effective_at,
        origin=PositionOrigin(row.origin),
        strategy_book=StrategyBook(row.strategy_book) if row.strategy_book else None,
        entry_score=_optional_decimal(row.entry_score),
        initial_risk_per_share=_optional_decimal(row.initial_risk_per_share),
        effective_stop=_optional_decimal(row.effective_stop),
        highest_close=_optional_decimal(row.highest_close),
        add_count=int(row.add_count or 0),
        batch_id=row.batch_id,
        buy_date=row.buy_date,
    )


def _revision_lot(row: dict[str, object], as_of_time: datetime) -> PortfolioLot:
    effective_at = datetime.fromisoformat(str(row["effective_at"]))
    available = int(row["available_to_sell"])
    if as_of_time.date() <= effective_at.date():
        available = 0
    buy_date = row.get("buy_date")
    return PortfolioLot(
        lot_id=str(row["lot_id"]),
        security_id=str(row["security_id"]),
        quantity=int(row["quantity"]),
        available_to_sell=max(0, min(int(row["quantity"]), available)),
        average_cost=_decimal(row["average_cost"]),
        effective_at=effective_at,
        origin=PositionOrigin(str(row["origin"])),
        strategy_book=StrategyBook(str(row["strategy_book"])) if row.get("strategy_book") else None,
        entry_score=_optional_decimal(row.get("entry_score")),
        initial_risk_per_share=_optional_decimal(row.get("initial_risk_per_share")),
        effective_stop=_optional_decimal(row.get("effective_stop")),
        highest_close=_optional_decimal(row.get("highest_close")),
        add_count=int(row.get("add_count") or 0),
        batch_id=str(row.get("batch_id") or "default"),
        buy_date=datetime.fromisoformat(str(buy_date)).date() if buy_date else None,
    )


def _decimal(value: Decimal | int | float | None) -> Decimal:
    return Decimal("0") if value is None else Decimal(str(value))


def _optional_decimal(value: Decimal | int | float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))
