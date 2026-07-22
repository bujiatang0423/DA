from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .models import Base


class LegacyImportBatchRow(Base):
    __tablename__ = "legacy_import_batches"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_root: Mapped[str] = mapped_column(Text)
    source_git_state: Mapped[str] = mapped_column(String(128))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    portfolio_id: Mapped[str] = mapped_column(String(64))
    manifest_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    quality_report_json: Mapped[str] = mapped_column(Text)


class LegacyRawFileRow(Base):
    __tablename__ = "legacy_raw_files"
    __table_args__ = (
        UniqueConstraint("batch_id", "relative_path", name="uq_legacy_raw_batch_path"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("legacy_import_batches.id"))
    relative_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    quality_tags_json: Mapped[str] = mapped_column(Text)


class LegacyPositionSnapshotRow(Base):
    __tablename__ = "legacy_position_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("legacy_import_batches.id"))
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    security_id: Mapped[str] = mapped_column(String(32))
    quantity: Mapped[int] = mapped_column(Integer)
    inherited_unit_cost: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    imported_buy_date: Mapped[str | None] = mapped_column(String(10))
    source_file_sha256: Mapped[str] = mapped_column(String(64))
    raw_row_json: Mapped[str] = mapped_column(Text)


class OpeningPositionRow(Base):
    __tablename__ = "opening_positions"
    __table_args__ = (
        UniqueConstraint("batch_id", "security_id", name="uq_opening_batch_security"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("legacy_import_batches.id"))
    portfolio_id: Mapped[str] = mapped_column(String(64))
    security_id: Mapped[str] = mapped_column(String(32))
    security_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer)
    inherited_unit_cost: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    buy_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    origin: Mapped[str] = mapped_column(String(32))
    source_row_hash: Mapped[str] = mapped_column(String(64))
