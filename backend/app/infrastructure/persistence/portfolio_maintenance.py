from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from hashlib import sha256
import json
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.contracts.portfolio import (
    PortfolioMaintenanceRequest,
    PortfolioMaintenanceResponse,
    PortfolioPositionInput,
)
from backend.app.core.portfolio.models import PositionOrigin
from backend.app.infrastructure.persistence.portfolio_rows import (
    PortfolioAuditEventRow,
    PortfolioLotProjectionRow,
    PortfolioSnapshotProjectionRow,
    PortfolioVersionRow,
)
from backend.app.ports.portfolio import ConcurrentPortfolioUpdate


class SqlPortfolioMaintenanceService:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def get(self, portfolio_id: str, as_of_time: datetime) -> PortfolioMaintenanceResponse:
        with self._session_factory() as session:
            projection = session.scalar(
                select(PortfolioSnapshotProjectionRow).where(
                    PortfolioSnapshotProjectionRow.portfolio_id == portfolio_id,
                    PortfolioSnapshotProjectionRow.as_of_time <= as_of_time,
                )
            )
            version = session.scalar(
                select(PortfolioVersionRow.version).where(
                    PortfolioVersionRow.portfolio_id == portfolio_id
                )
            )
            rows = session.scalars(
                select(PortfolioLotProjectionRow)
                .where(
                    PortfolioLotProjectionRow.portfolio_id == portfolio_id,
                    PortfolioLotProjectionRow.effective_at <= as_of_time,
                )
                .order_by(PortfolioLotProjectionRow.security_id)
            ).all()
            return PortfolioMaintenanceResponse(
                portfolio_id=portfolio_id,
                as_of_time=as_of_time,
                version=int(version or 0),
                cash=Decimal(str(projection.cash)) if projection else Decimal("0"),
                equity=Decimal(str(projection.equity)) if projection else Decimal("0"),
                positions=[
                    _position(
                        row.batch_id,
                        row.security_id,
                        row.buy_date,
                        row.quantity,
                        row.average_cost,
                        row.available_to_sell,
                        row.effective_stop,
                        row.highest_close,
                        row.strategy_book,
                    )
                    for row in rows
                ],
            )

    def replace(self, request: PortfolioMaintenanceRequest) -> PortfolioMaintenanceResponse:
        with self._session_factory.begin() as session:
            current = session.scalar(
                select(PortfolioVersionRow)
                .where(PortfolioVersionRow.portfolio_id == request.portfolio_id)
                .with_for_update()
            )
            current_version = int(current.version) if current else 0
            if current_version != request.expected_version:
                raise ConcurrentPortfolioUpdate(
                    f"expected version {request.expected_version}, current {current_version}"
                )
            if current is None:
                current = PortfolioVersionRow(portfolio_id=request.portfolio_id, version=0)
                session.add(current)
                session.flush()
            next_version = current_version + 1
            current.version = next_version
            session.execute(
                delete(PortfolioLotProjectionRow).where(
                    PortfolioLotProjectionRow.portfolio_id == request.portfolio_id
                )
            )
            session.merge(
                PortfolioSnapshotProjectionRow(
                    portfolio_id=request.portfolio_id,
                    as_of_time=request.as_of_time,
                    cash=request.cash,
                    equity=request.equity,
                )
            )
            for position in request.positions:
                session.add(
                    PortfolioLotProjectionRow(
                        lot_id=f"manual:{request.portfolio_id}:{position.batch_id}:{position.security_id}",
                        batch_id=position.batch_id,
                        portfolio_id=request.portfolio_id,
                        security_id=position.security_id,
                        buy_date=position.buy_date,
                        quantity=position.quantity,
                        available_to_sell=position.available_to_sell or 0,
                        average_cost=position.average_cost,
                        effective_at=request.as_of_time,
                        origin=PositionOrigin.RECORDED_TRADE.value,
                        strategy_book=position.strategy_book,
                        entry_score=None,
                        initial_risk_per_share=None,
                        effective_stop=position.effective_stop,
                        highest_close=position.highest_close,
                        add_count=0,
                    )
                )
            payload = request.model_dump(mode="json")
            session.add(
                PortfolioAuditEventRow(
                    portfolio_id=request.portfolio_id,
                    event_type="position_correction",
                    expected_version=current_version,
                    resulting_version=next_version,
                    recorded_at=datetime.now(UTC),
                    reason=request.reason,
                    payload_hash=sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
                    payload_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
                )
            )
            return PortfolioMaintenanceResponse(
                portfolio_id=request.portfolio_id,
                as_of_time=request.as_of_time,
                version=next_version,
                cash=request.cash,
                equity=request.equity,
                positions=list(request.positions),
            )


def _position(
    batch_id: str,
    security_id: str,
    buy_date: date | None,
    quantity: int,
    average_cost: Decimal,
    available_to_sell: int,
    effective_stop: Decimal | None,
    highest_close: Decimal | None,
    strategy_book: str | None,
) -> PortfolioPositionInput:
    return PortfolioPositionInput(
        batch_id=batch_id,
        security_id=security_id,
        buy_date=buy_date,
        quantity=quantity,
        average_cost=average_cost,
        available_to_sell=available_to_sell,
        effective_stop=effective_stop,
        highest_close=highest_close,
        strategy_book=strategy_book,
    )
