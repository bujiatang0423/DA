from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


class PositionOrigin(StrEnum):
    LEGACY_OPENING_BALANCE = "legacy_opening_balance"
    RECORDED_TRADE = "recorded_trade"
    SIMULATED_FILL = "simulated_fill"


class StrategyBook(StrEnum):
    CORE = "core"
    SWING = "swing"


class FillSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class OpeningPosition:
    security_id: str
    quantity: int
    inherited_unit_cost: Decimal
    effective_at: datetime
    source_row_hash: str
    origin: PositionOrigin = PositionOrigin.LEGACY_OPENING_BALANCE
    strategy_book: StrategyBook | None = None
    entry_score: Decimal | None = None
    initial_risk_per_share: Decimal | None = None


@dataclass(frozen=True)
class PortfolioLot:
    lot_id: str
    security_id: str
    quantity: int
    available_to_sell: int
    average_cost: Decimal
    effective_at: datetime
    origin: PositionOrigin
    strategy_book: StrategyBook | None
    entry_score: Decimal | None
    initial_risk_per_share: Decimal | None
    effective_stop: Decimal | None
    highest_close: Decimal | None
    add_count: int
    batch_id: str = "default"
    buy_date: date | None = None
    import_manifest_sha256: str | None = None


@dataclass(frozen=True)
class PortfolioPosition:
    security_id: str
    strategy_book: StrategyBook | None
    origin: PositionOrigin
    quantity: int
    available_to_sell: int
    average_cost: Decimal
    effective_stop: Decimal | None
    highest_close: Decimal | None
    entry_score: Decimal | None
    initial_risk_per_share: Decimal | None
    add_count: int


@dataclass(frozen=True)
class PortfolioSnapshot:
    portfolio_id: str
    as_of_time: datetime
    version: int
    cash: Decimal
    equity: Decimal
    lots: tuple[PortfolioLot, ...]

    @property
    def positions(self) -> tuple[PortfolioPosition, ...]:
        groups: dict[tuple[str, StrategyBook | None, PositionOrigin], list[PortfolioLot]] = {}
        for lot in self.lots:
            groups.setdefault((lot.security_id, lot.strategy_book, lot.origin), []).append(lot)
        out = []
        for (sid, book, origin), lots in sorted(groups.items(), key=lambda x: str(x[0])):
            q = sum(x.quantity for x in lots)
            if q <= 0:
                continue
            first = min(lots, key=lambda x: x.effective_at)
            out.append(
                PortfolioPosition(
                    sid,
                    book,
                    origin,
                    q,
                    sum(x.available_to_sell for x in lots),
                    sum(x.average_cost * x.quantity for x in lots) / q,
                    max(
                        (x.effective_stop for x in lots if x.effective_stop is not None),
                        default=None,
                    ),
                    max(
                        (x.highest_close for x in lots if x.highest_close is not None), default=None
                    ),
                    first.entry_score,
                    first.initial_risk_per_share,
                    max(x.add_count for x in lots),
                )
            )
        return tuple(out)


@dataclass(frozen=True)
class ManualFillCommand:
    portfolio_id: str
    security_id: str
    side: FillSide
    quantity: int
    price: Decimal
    fee: Decimal
    filled_at: datetime
    strategy_book: StrategyBook | None


@dataclass(frozen=True)
class CorrectionSnapshot:
    portfolio_id: str
    as_of_time: datetime
    cash: Decimal
    equity: Decimal
    lots: tuple[PortfolioLot, ...]


@dataclass(frozen=True)
class PortfolioAuditEvent:
    portfolio_id: str
    event_type: str
    recorded_at: datetime
    expected_version: int
    reason: str
    payload_hash: str
