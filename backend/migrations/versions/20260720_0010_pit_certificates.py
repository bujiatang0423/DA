"""persist approved strict PIT certificates

Revision ID: 20260720_0010
Revises: 20260719_0009
"""

from alembic import op
import sqlalchemy as sa


revision = "20260720_0010"
down_revision = "20260719_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pit_audit_reports",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("coverage_start", sa.Date(), nullable=False),
        sa.Column("coverage_end", sa.Date(), nullable=False),
        sa.Column("bundle_set_hash", sa.String(64), nullable=False),
        sa.Column("audit_hash", sa.String(64), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_pit_audit_reports_bundle_set_hash", "pit_audit_reports", ["bundle_set_hash"]
    )
    op.create_table(
        "pit_certificates",
        sa.Column(
            "audit_report_id",
            sa.String(128),
            sa.ForeignKey("pit_audit_reports.id"),
            primary_key=True,
        ),
        sa.Column("coverage_start", sa.Date(), nullable=False),
        sa.Column("coverage_end", sa.Date(), nullable=False),
        sa.Column("bundle_set_hash", sa.String(64), nullable=False),
        sa.Column("audit_hash", sa.String(64), nullable=False),
        sa.Column("approval_token", sa.String(64), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("certified_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("lineage_hash", sa.String(64), nullable=False),
        sa.Column("selected_snapshot_hash", sa.String(64), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("pit_certificates")
    op.drop_index("ix_pit_audit_reports_bundle_set_hash", table_name="pit_audit_reports")
    op.drop_table("pit_audit_reports")
