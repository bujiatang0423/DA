from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
import json

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.portfolio.models import (
    CorrectionSnapshot,
    FillSide,
    ManualFillCommand,
    PortfolioAuditEvent,
    PortfolioLot,
    PortfolioSnapshot,
    PositionOrigin,
)
from backend.app.ports.portfolio import ConcurrentPortfolioUpdate

from .portfolio_reader import read_portfolio_snapshot
from .portfolio_rows import (
    PortfolioAuditEventRow,
    PortfolioLotProjectionRow,
    PortfolioSnapshotProjectionRow,
    PortfolioSnapshotRevisionRow,
    PortfolioVersionRow,
)


class InsufficientCash(ValueError):
    pass


class InsufficientSellableQuantity(ValueError):
    pass


class BackdatedPortfolioMutation(ValueError):
    pass


class SqlPortfolioEventStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def append(
        self,
        *,
        event: PortfolioAuditEvent,
        payload: object,
        expected_version: int,
    ) -> PortfolioSnapshot:
        portfolio_id, as_of_time = _payload_identity(payload)
        if event.portfolio_id != portfolio_id:
            raise ValueError("portfolio event identity mismatch")

        with self._session_factory.begin() as session:
            version = session.scalar(
                select(PortfolioVersionRow)
                .where(PortfolioVersionRow.portfolio_id == portfolio_id)
                .with_for_update()
            )
            current_version = int(version.version) if version is not None else 0
            if current_version != expected_version:
                raise ConcurrentPortfolioUpdate(
                    f"expected version {expected_version}, current {current_version}"
                )
            if version is None:
                version = PortfolioVersionRow(portfolio_id=portfolio_id, version=0)
                session.add(version)
            current_as_of_time = _current_projection_time(session, portfolio_id, event.recorded_at)
            if _as_utc(as_of_time) < _as_utc(current_as_of_time):
                raise BackdatedPortfolioMutation(
                    "manual fills and corrections cannot predate the current portfolio projection"
                )
            current = read_portfolio_snapshot(session, portfolio_id, event.recorded_at)
            next_version = current_version + 1
            updated = _apply_payload(current, payload, next_version)
            version.version = next_version
            _write_revision(
                session,
                current,
                current_as_of_time,
                recorded_at=current_as_of_time,
            )
            _supersede_revisions(session, updated, event.recorded_at)
            _write_revision(session, updated, updated.as_of_time, recorded_at=event.recorded_at)
            _write_projection(session, updated)
            session.add(
                PortfolioAuditEventRow(
                    portfolio_id=portfolio_id,
                    event_type=event.event_type,
                    expected_version=expected_version,
                    resulting_version=next_version,
                    recorded_at=event.recorded_at,
                    reason=event.reason,
                    payload_hash=event.payload_hash,
                    payload_json=json.dumps(
                        asdict(payload),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    ),
                )
            )
            return replace(updated, version=next_version)


def _payload_identity(payload: object) -> tuple[str, datetime]:
    if isinstance(payload, CorrectionSnapshot):
        return payload.portfolio_id, payload.as_of_time
    if isinstance(payload, ManualFillCommand):
        return payload.portfolio_id, payload.filled_at
    raise TypeError(f"unsupported portfolio payload: {type(payload).__name__}")


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _apply_payload(
    current: PortfolioSnapshot,
    payload: object,
    next_version: int,
) -> PortfolioSnapshot:
    if isinstance(payload, CorrectionSnapshot):
        return PortfolioSnapshot(
            portfolio_id=payload.portfolio_id,
            as_of_time=payload.as_of_time,
            version=next_version,
            cash=payload.cash,
            equity=payload.equity,
            lots=payload.lots,
        )
    if isinstance(payload, ManualFillCommand):
        return _apply_manual_fill(current, payload, next_version)
    raise TypeError(f"unsupported portfolio payload: {type(payload).__name__}")


def _apply_manual_fill(
    current: PortfolioSnapshot,
    command: ManualFillCommand,
    next_version: int,
) -> PortfolioSnapshot:
    notional = command.price * command.quantity
    if command.side is FillSide.BUY:
        total_cost = notional + command.fee
        if current.cash < total_cost:
            raise InsufficientCash("manual buy exceeds available cash")
        new_lot = PortfolioLot(
            lot_id=f"manual:{next_version}:{command.security_id}",
            security_id=command.security_id,
            quantity=command.quantity,
            available_to_sell=0,
            average_cost=total_cost / command.quantity,
            effective_at=command.filled_at,
            origin=PositionOrigin.RECORDED_TRADE,
            strategy_book=command.strategy_book,
            entry_score=None,
            initial_risk_per_share=None,
            effective_stop=None,
            highest_close=command.price,
            add_count=0,
            batch_id=f"manual-{next_version}",
            buy_date=command.filled_at.date(),
        )
        lots = (*current.lots, new_lot)
        cash = current.cash - total_cost
    else:
        lots = _apply_manual_sell(current.lots, command)
        cash = current.cash + notional - command.fee
    return PortfolioSnapshot(
        portfolio_id=current.portfolio_id,
        as_of_time=command.filled_at,
        version=next_version,
        cash=cash,
        equity=current.equity - command.fee,
        lots=tuple(lots),
    )


def _apply_manual_sell(
    lots: tuple[PortfolioLot, ...],
    command: ManualFillCommand,
) -> tuple[PortfolioLot, ...]:
    sellable = sum(lot.available_to_sell for lot in lots if lot.security_id == command.security_id)
    if sellable < command.quantity:
        raise InsufficientSellableQuantity("manual sell exceeds available quantity")

    remaining = command.quantity
    updated: list[PortfolioLot] = []
    for lot in sorted(lots, key=lambda value: (value.effective_at, value.lot_id)):
        if lot.security_id != command.security_id or remaining == 0:
            updated.append(lot)
            continue
        consumed = min(lot.available_to_sell, remaining)
        remaining -= consumed
        next_quantity = lot.quantity - consumed
        if next_quantity > 0:
            updated.append(
                replace(
                    lot,
                    quantity=next_quantity,
                    available_to_sell=lot.available_to_sell - consumed,
                )
            )
    return tuple(updated)


def _write_projection(session: Session, snapshot: PortfolioSnapshot) -> None:
    session.execute(
        delete(PortfolioLotProjectionRow).where(
            PortfolioLotProjectionRow.portfolio_id == snapshot.portfolio_id
        )
    )
    session.merge(
        PortfolioSnapshotProjectionRow(
            portfolio_id=snapshot.portfolio_id,
            as_of_time=snapshot.as_of_time,
            cash=snapshot.cash,
            equity=snapshot.equity,
        )
    )
    for lot in snapshot.lots:
        session.add(
            PortfolioLotProjectionRow(
                lot_id=lot.lot_id,
                batch_id=lot.batch_id,
                portfolio_id=snapshot.portfolio_id,
                security_id=lot.security_id,
                buy_date=lot.buy_date,
                quantity=lot.quantity,
                available_to_sell=lot.available_to_sell,
                average_cost=lot.average_cost,
                effective_at=lot.effective_at,
                origin=lot.origin.value,
                strategy_book=lot.strategy_book.value if lot.strategy_book else None,
                entry_score=lot.entry_score,
                initial_risk_per_share=lot.initial_risk_per_share,
                effective_stop=lot.effective_stop,
                highest_close=lot.highest_close,
                add_count=lot.add_count,
            )
        )


def _current_projection_time(
    session: Session,
    portfolio_id: str,
    as_of_time: datetime,
) -> datetime:
    revision = session.scalar(
        select(PortfolioSnapshotRevisionRow.as_of_time)
        .where(
            PortfolioSnapshotRevisionRow.portfolio_id == portfolio_id,
            PortfolioSnapshotRevisionRow.as_of_time <= as_of_time,
        )
        .order_by(
            PortfolioSnapshotRevisionRow.as_of_time.desc(),
            PortfolioSnapshotRevisionRow.version.desc(),
        )
    )
    if revision is not None:
        return revision
    projection = session.scalar(
        select(PortfolioSnapshotProjectionRow.as_of_time)
        .where(
            PortfolioSnapshotProjectionRow.portfolio_id == portfolio_id,
            PortfolioSnapshotProjectionRow.as_of_time <= as_of_time,
        )
        .order_by(PortfolioSnapshotProjectionRow.as_of_time.desc())
    )
    return projection or as_of_time


def _write_revision(
    session: Session,
    snapshot: PortfolioSnapshot,
    as_of_time: datetime,
    *,
    recorded_at: datetime,
) -> None:
    existing = session.scalar(
        select(PortfolioSnapshotRevisionRow).where(
            PortfolioSnapshotRevisionRow.portfolio_id == snapshot.portfolio_id,
            PortfolioSnapshotRevisionRow.as_of_time == as_of_time,
            PortfolioSnapshotRevisionRow.version == snapshot.version,
        )
    )
    if existing is not None:
        return
    session.add(
        PortfolioSnapshotRevisionRow(
            portfolio_id=snapshot.portfolio_id,
            as_of_time=as_of_time,
            recorded_at=recorded_at,
            superseded_at=None,
            version=snapshot.version,
            cash=snapshot.cash,
            equity=snapshot.equity,
            lots=[_lot_payload(lot) for lot in snapshot.lots],
        )
    )


def _supersede_revisions(
    session: Session,
    snapshot: PortfolioSnapshot,
    recorded_at: datetime,
) -> None:
    session.execute(
        update(PortfolioSnapshotRevisionRow)
        .where(
            PortfolioSnapshotRevisionRow.portfolio_id == snapshot.portfolio_id,
            PortfolioSnapshotRevisionRow.as_of_time >= snapshot.as_of_time,
            PortfolioSnapshotRevisionRow.recorded_at < recorded_at,
            PortfolioSnapshotRevisionRow.superseded_at.is_(None),
        )
        .values(superseded_at=recorded_at)
    )


def _lot_payload(lot: PortfolioLot) -> dict[str, object]:
    return {
        "lot_id": lot.lot_id,
        "batch_id": lot.batch_id,
        "security_id": lot.security_id,
        "buy_date": lot.buy_date.isoformat() if lot.buy_date else None,
        "quantity": lot.quantity,
        "available_to_sell": lot.available_to_sell,
        "average_cost": str(lot.average_cost),
        "effective_at": lot.effective_at.isoformat(),
        "origin": lot.origin.value,
        "strategy_book": lot.strategy_book.value if lot.strategy_book else None,
        "entry_score": str(lot.entry_score) if lot.entry_score is not None else None,
        "initial_risk_per_share": (
            str(lot.initial_risk_per_share) if lot.initial_risk_per_share is not None else None
        ),
        "effective_stop": str(lot.effective_stop) if lot.effective_stop is not None else None,
        "highest_close": str(lot.highest_close) if lot.highest_close is not None else None,
        "add_count": lot.add_count,
    }
