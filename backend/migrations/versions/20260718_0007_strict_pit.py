"""append strict point-in-time history tables

Revision ID: 20260718_0007
Revises: 20260718_0006
"""

from alembic import op
import sqlalchemy as sa


revision = "20260718_0007"
down_revision = "20260718_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pit_bundles",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("manifest_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("coverage_start", sa.Date(), nullable=False),
        sa.Column("coverage_end", sa.Date(), nullable=False),
    )
    op.create_table(
        "security_master_history",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("source_record_id", sa.String(128), nullable=False),
        sa.Column("security_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("listed_on", sa.Date(), nullable=False),
        sa.Column("delisted_on", sa.Date(), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_artifact_hash", sa.String(64), nullable=False),
    )
    _create_security_indexes("security_master_history", "security_id")
    op.create_table(
        "security_status_daily",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("source_record_id", sa.String(128), nullable=False),
        sa.Column("security_id", sa.String(32), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("is_st", sa.Boolean(), nullable=False),
        sa.Column("is_suspended", sa.Boolean(), nullable=False),
        sa.Column("board", sa.String(32), nullable=False),
        sa.Column("price_limit_pct", sa.Numeric(8, 4), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_artifact_hash", sa.String(64), nullable=False),
    )
    _create_security_indexes("security_status_daily", "security_id", "trade_date")
    op.create_table(
        "trading_calendar",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("source_record_id", sa.String(128), nullable=False),
        sa.Column("exchange", sa.String(16), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("is_open", sa.Boolean(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_artifact_hash", sa.String(64), nullable=False),
    )
    _create_security_indexes("trading_calendar", "exchange", "trade_date")
    op.create_table(
        "daily_bars_raw",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("source_record_id", sa.String(128), nullable=False),
        sa.Column("security_id", sa.String(32), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(20, 6), nullable=False),
        sa.Column("high", sa.Numeric(20, 6), nullable=False),
        sa.Column("low", sa.Numeric(20, 6), nullable=False),
        sa.Column("close", sa.Numeric(20, 6), nullable=False),
        sa.Column("volume", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(24, 2), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_artifact_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint(
            "security_id", "trade_date", "source_artifact_hash", name="uq_raw_bar_version"
        ),
    )
    _create_security_indexes("daily_bars_raw", "security_id", "trade_date")
    op.create_table(
        "index_daily_bars",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("source_record_id", sa.String(128), nullable=False),
        sa.Column("index_id", sa.String(32), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(20, 6), nullable=False),
        sa.Column("high", sa.Numeric(20, 6), nullable=False),
        sa.Column("low", sa.Numeric(20, 6), nullable=False),
        sa.Column("close", sa.Numeric(20, 6), nullable=False),
        sa.Column("volume", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(24, 2), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_artifact_hash", sa.String(64), nullable=False),
    )
    _create_security_indexes("index_daily_bars", "index_id", "trade_date")
    for table in (
        "corporate_actions",
        "adjustment_factors",
        "industry_membership_history",
        "theme_membership_history",
    ):
        _create_temporal_json_table(table)
    op.create_table(
        "financial_disclosures",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("source_record_id", sa.String(128), nullable=False),
        sa.Column("security_id", sa.String(32), nullable=False),
        sa.Column("report_period", sa.Date(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_artifact_hash", sa.String(64), nullable=False),
    )
    _create_security_indexes("financial_disclosures", "security_id")
    op.create_table(
        "financial_facts",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("source_record_id", sa.String(128), nullable=False),
        sa.Column(
            "disclosure_id",
            sa.String(128),
            sa.ForeignKey("financial_disclosures.id"),
            nullable=False,
        ),
        sa.Column("disclosure_source_record_id", sa.String(128), nullable=False),
        sa.Column("metric", sa.String(64), nullable=False),
        sa.Column("value", sa.String(128), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_artifact_hash", sa.String(64), nullable=False),
    )
    op.create_index("ix_financial_facts_disclosure_id", "financial_facts", ["disclosure_id"])
    op.create_index(
        "ix_financial_facts_disclosure_source_record_id",
        "financial_facts",
        ["disclosure_source_record_id"],
    )
    op.create_index("ix_financial_facts_source_record_id", "financial_facts", ["source_record_id"])
    op.create_index("ix_financial_facts_available_at", "financial_facts", ["available_at"])
    op.create_table(
        "policy_documents",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("source_record_id", sa.String(128), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_grade", sa.String(8), nullable=False),
        sa.Column("official_parent_id", sa.String(128), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("source_artifact_hash", sa.String(64), nullable=False),
    )
    op.create_index("ix_policy_documents_available_at", "policy_documents", ["available_at"])
    op.create_index(
        "ix_policy_documents_source_record_id", "policy_documents", ["source_record_id"]
    )
    op.create_table(
        "fee_schedules",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("source_record_id", sa.String(128), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("exchange", sa.String(16), nullable=False),
        sa.Column("asset_type", sa.String(16), nullable=False),
        sa.Column("commission_rate", sa.Numeric(12, 8), nullable=False),
        sa.Column("minimum_commission", sa.Numeric(20, 6), nullable=False),
        sa.Column("stamp_tax_sell_rate", sa.Numeric(12, 8), nullable=False),
        sa.Column("transfer_rate", sa.Numeric(12, 8), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_artifact_hash", sa.String(64), nullable=False),
    )
    op.create_index("ix_fee_schedules_available_at", "fee_schedules", ["available_at"])
    op.create_index("ix_fee_schedules_source_record_id", "fee_schedules", ["source_record_id"])


def downgrade() -> None:
    op.drop_index("ix_fee_schedules_source_record_id", table_name="fee_schedules")
    op.drop_index("ix_fee_schedules_available_at", table_name="fee_schedules")
    op.drop_table("fee_schedules")
    op.drop_index("ix_policy_documents_source_record_id", table_name="policy_documents")
    op.drop_index("ix_policy_documents_available_at", table_name="policy_documents")
    op.drop_table("policy_documents")
    op.drop_index("ix_financial_facts_available_at", table_name="financial_facts")
    op.drop_index("ix_financial_facts_source_record_id", table_name="financial_facts")
    op.drop_index("ix_financial_facts_disclosure_source_record_id", table_name="financial_facts")
    op.drop_index("ix_financial_facts_disclosure_id", table_name="financial_facts")
    op.drop_table("financial_facts")
    _drop_security_indexes("financial_disclosures", "security_id")
    op.drop_table("financial_disclosures")
    for table in (
        "theme_membership_history",
        "industry_membership_history",
        "adjustment_factors",
        "corporate_actions",
    ):
        _drop_security_indexes(table, "security_id")
        op.drop_table(table)
    _drop_security_indexes("index_daily_bars", "index_id", "trade_date")
    op.drop_table("index_daily_bars")
    _drop_security_indexes("daily_bars_raw", "security_id", "trade_date")
    op.drop_table("daily_bars_raw")
    _drop_security_indexes("trading_calendar", "exchange", "trade_date")
    op.drop_table("trading_calendar")
    _drop_security_indexes("security_status_daily", "security_id", "trade_date")
    op.drop_table("security_status_daily")
    _drop_security_indexes("security_master_history", "security_id")
    op.drop_table("security_master_history")
    op.drop_table("pit_bundles")


def _create_temporal_json_table(table: str) -> None:
    op.create_table(
        table,
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("source_record_id", sa.String(128), nullable=False),
        sa.Column("security_id", sa.String(32), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_artifact_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
    )
    _create_security_indexes(table, "security_id")


def _create_security_indexes(table: str, *columns: str) -> None:
    for column in (*columns, "source_record_id", "available_at"):
        op.create_index(f"ix_{table}_{column}", table, [column])


def _drop_security_indexes(table: str, *columns: str) -> None:
    for column in reversed((*columns, "source_record_id", "available_at")):
        op.drop_index(f"ix_{table}_{column}", table_name=table)
