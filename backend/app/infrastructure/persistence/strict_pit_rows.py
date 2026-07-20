from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.infrastructure.persistence.models import Base


class PitBundleRow(Base):
    __tablename__ = "pit_bundles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    manifest_sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    coverage_start: Mapped[date] = mapped_column(Date, nullable=False)
    coverage_end: Mapped[date] = mapped_column(Date, nullable=False)


class PitCertificateRow(Base):
    __tablename__ = "pit_certificates"

    audit_report_id: Mapped[str] = mapped_column(
        ForeignKey("pit_audit_reports.id"),
        primary_key=True,
    )
    coverage_start: Mapped[date] = mapped_column(Date, nullable=False)
    coverage_end: Mapped[date] = mapped_column(Date, nullable=False)
    bundle_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_token: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    certified_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lineage_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    selected_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class PitAuditReportRow(Base):
    __tablename__ = "pit_audit_reports"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    coverage_start: Mapped[date] = mapped_column(Date, nullable=False)
    coverage_end: Mapped[date] = mapped_column(Date, nullable=False)
    market_id: Mapped[str | None] = mapped_column(String(32))
    universe_id: Mapped[str | None] = mapped_column(String(64))
    bundle_set_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    audit_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SecurityMasterHistoryRow(Base):
    __tablename__ = "security_master_history"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_record_id: Mapped[str] = mapped_column(String(128), index=True)
    security_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(128))
    listed_on: Mapped[date] = mapped_column(Date)
    delisted_on: Mapped[date | None] = mapped_column(Date)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_artifact_hash: Mapped[str] = mapped_column(String(64))


class SecurityStatusDailyRow(Base):
    __tablename__ = "security_status_daily"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_record_id: Mapped[str] = mapped_column(String(128), index=True)
    security_id: Mapped[str] = mapped_column(String(32), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    is_st: Mapped[bool] = mapped_column(Boolean)
    is_suspended: Mapped[bool] = mapped_column(Boolean)
    board: Mapped[str] = mapped_column(String(32))
    price_limit_pct: Mapped[Decimal] = mapped_column(Numeric(8, 4))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_artifact_hash: Mapped[str] = mapped_column(String(64))


class TradingCalendarRow(Base):
    __tablename__ = "trading_calendar"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_record_id: Mapped[str] = mapped_column(String(128), index=True)
    exchange: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    is_open: Mapped[bool] = mapped_column(Boolean)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_artifact_hash: Mapped[str] = mapped_column(String(64))


class DailyBarRawRow(Base):
    __tablename__ = "daily_bars_raw"
    __table_args__ = (
        UniqueConstraint(
            "security_id", "trade_date", "source_artifact_hash", name="uq_raw_bar_version"
        ),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_record_id: Mapped[str] = mapped_column(String(128), index=True)
    security_id: Mapped[str] = mapped_column(String(32), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    high: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    low: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    close: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    volume: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 2))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_artifact_hash: Mapped[str] = mapped_column(String(64))


class IndexDailyBarRow(Base):
    __tablename__ = "index_daily_bars"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_record_id: Mapped[str] = mapped_column(String(128), index=True)
    index_id: Mapped[str] = mapped_column(String(32), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    high: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    low: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    close: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    volume: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 2))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_artifact_hash: Mapped[str] = mapped_column(String(64))


class MarketBreadthRow(Base):
    __tablename__ = "market_breadth"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_record_id: Mapped[str] = mapped_column(String(128), index=True)
    market_id: Mapped[str | None] = mapped_column(String(32), index=True)
    universe_id: Mapped[str | None] = mapped_column(String(64), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    breadth: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    security_count: Mapped[int] = mapped_column(Integer)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_artifact_hash: Mapped[str] = mapped_column(String(64))


class TemporalJsonRow(Base):
    __abstract__ = True

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_record_id: Mapped[str] = mapped_column(String(128), index=True)
    security_id: Mapped[str] = mapped_column(String(32), index=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_artifact_hash: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)


class CorporateActionRow(TemporalJsonRow):
    __tablename__ = "corporate_actions"


class AdjustmentFactorRow(TemporalJsonRow):
    __tablename__ = "adjustment_factors"


class IndustryMembershipHistoryRow(TemporalJsonRow):
    __tablename__ = "industry_membership_history"


class ThemeMembershipHistoryRow(TemporalJsonRow):
    __tablename__ = "theme_membership_history"


class FinancialDisclosureRow(Base):
    __tablename__ = "financial_disclosures"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_record_id: Mapped[str] = mapped_column(String(128), index=True)
    security_id: Mapped[str] = mapped_column(String(32), index=True)
    report_period: Mapped[date] = mapped_column(Date)
    revision: Mapped[int] = mapped_column(Integer)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_artifact_hash: Mapped[str] = mapped_column(String(64))


class FinancialFactRow(Base):
    __tablename__ = "financial_facts"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_record_id: Mapped[str] = mapped_column(String(128), index=True)
    disclosure_id: Mapped[str] = mapped_column(ForeignKey("financial_disclosures.id"), index=True)
    disclosure_source_record_id: Mapped[str] = mapped_column(String(128), index=True)
    metric: Mapped[str] = mapped_column(String(64))
    value: Mapped[str] = mapped_column(String(128))
    unit: Mapped[str] = mapped_column(String(32))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_artifact_hash: Mapped[str] = mapped_column(String(64))


class PolicyDocumentRow(Base):
    __tablename__ = "policy_documents"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_record_id: Mapped[str] = mapped_column(String(128), index=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    evidence_grade: Mapped[str] = mapped_column(String(8))
    official_parent_id: Mapped[str | None] = mapped_column(String(128))
    content_hash: Mapped[str] = mapped_column(String(64))
    source_artifact_hash: Mapped[str] = mapped_column(String(64))


class FeeScheduleRow(Base):
    __tablename__ = "fee_schedules"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_record_id: Mapped[str] = mapped_column(String(128), index=True)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    exchange: Mapped[str] = mapped_column(String(16))
    asset_type: Mapped[str] = mapped_column(String(16))
    commission_rate: Mapped[Decimal] = mapped_column(Numeric(12, 8))
    minimum_commission: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    stamp_tax_sell_rate: Mapped[Decimal] = mapped_column(Numeric(12, 8))
    transfer_rate: Mapped[Decimal] = mapped_column(Numeric(12, 8))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_artifact_hash: Mapped[str] = mapped_column(String(64))
