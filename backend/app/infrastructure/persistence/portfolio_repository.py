from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime
import json

from sqlalchemy import delete, select
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
    PortfolioVersionRow,
)


class InsufficientCash(ValueError):
    pass


class InsufficientSellableQuantity(ValueError):
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
            current = read_portfolio_snapshot(session, portfolio_id, as_of_time)
            next_version = current_version + 1
            updated = _apply_payload(current, payload, next_version)
            version.version = next_version
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
