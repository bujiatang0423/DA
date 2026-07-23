"""persist reviewed official evidence for holding analysis"""

from alembic import op
import sqlalchemy as sa


revision = "20260723_0023"
down_revision = "20260722_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "official_research_evidence",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("security_id", sa.String(length=16), nullable=True),
        sa.Column("report_period", sa.Date(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_host", sa.String(length=255), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_sha256", name="uq_official_research_evidence_hash"),
    )
    op.create_index(
        "ix_official_evidence_holding_lookup",
        "official_research_evidence",
        ["kind", "security_id", "published_at"],
        unique=False,
    )
    op.create_index(
        "ix_official_evidence_policy_lookup",
        "official_research_evidence",
        ["kind", "published_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_official_evidence_policy_lookup", table_name="official_research_evidence")
    op.drop_index("ix_official_evidence_holding_lookup", table_name="official_research_evidence")
    op.drop_table("official_research_evidence")
