from datetime import datetime
from typing import Protocol
from backend.app.core.portfolio.models import (
    PortfolioSnapshot,
    OpeningPosition,
    PortfolioAuditEvent,
    ManualFillCommand,
    CorrectionSnapshot,
)


class ConcurrentPortfolioUpdate(RuntimeError):
    pass


class PortfolioReader(Protocol):
    def snapshot(self, *, portfolio_id: str, as_of_time: datetime) -> PortfolioSnapshot: ...


class PortfolioEventStore(Protocol):
    def append(
        self, *, event: PortfolioAuditEvent, payload: object, expected_version: int
    ) -> PortfolioSnapshot: ...


class PortfolioWriter(Protocol):
    def record_manual_fill(
        self, command: ManualFillCommand, expected_version: int
    ) -> PortfolioSnapshot: ...
    def replace_positions_for_correction(
        self, snapshot: CorrectionSnapshot, expected_version: int, reason: str
    ) -> PortfolioSnapshot: ...


class OpeningBalanceWriter(Protocol):
    def apply(
        self,
        *,
        batch_id: str,
        portfolio_id: str,
        effective_at: datetime,
        positions: tuple[OpeningPosition, ...],
    ) -> None: ...
