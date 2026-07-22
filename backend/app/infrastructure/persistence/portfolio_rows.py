from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Date, DateTime, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .models import Base


class PortfolioVersionRow(Base):
    __tablename__ = "portfolio_versions"
    portfolio_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PortfolioSnapshotProjectionRow(Base):
    __tablename__ = "portfolio_snapshot_projections"
    portfolio_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    as_of_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cash: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    equity: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)


class PortfolioPositionQuoteRow(Base):
    __tablename__ = "portfolio_position_quotes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[str] = mapped_column(String(64), index=True)
    security_id: Mapped[str] = mapped_column(String(32), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)


class PortfolioLotProjectionRow(Base):
    __tablename__ = "portfolio_lot_projections"
    lot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    portfolio_id: Mapped[str] = mapped_column(String(64), index=True)
    security_id: Mapped[str] = mapped_column(String(32))
    security_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    buy_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer)
    available_to_sell: Mapped[int] = mapped_column(Integer)
    average_cost: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    origin: Mapped[str] = mapped_column(String(32))
    strategy_book: Mapped[str | None] = mapped_column(String(16))
    entry_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    initial_risk_per_share: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    effective_stop: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    highest_close: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    add_count: Mapped[int] = mapped_column(Integer, default=0)


class PortfolioSnapshotRevisionRow(Base):
    __tablename__ = "portfolio_snapshot_revisions"
    __table_args__ = (
        UniqueConstraint(
            "portfolio_id",
            "as_of_time",
            "version",
            name="uq_portfolio_snapshot_revision",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(String(64), index=True)
    as_of_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    cash: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    equity: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    lots: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)


class PortfolioAuditEventRow(Base):
    __tablename__ = "portfolio_audit_events"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "resulting_version", name="uq_portfolio_event_version"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(32))
    expected_version: Mapped[int] = mapped_column(Integer)
    resulting_version: Mapped[int] = mapped_column(Integer)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)
