"""persist certified market breadth snapshots

Revision ID: 20260720_0012
Revises: 20260720_0011
"""

from alembic import op
import sqlalchemy as sa


revision = "20260720_0012"
down_revision = "20260720_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_breadth",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("source_record_id", sa.String(128), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("breadth", sa.Numeric(8, 6), nullable=False),
        sa.Column("security_count", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_artifact_hash", sa.String(64), nullable=False),
    )
    op.create_index(
        "ix_market_breadth_source_record_id",
        "market_breadth",
        ["source_record_id"],
    )
    op.create_index("ix_market_breadth_trade_date", "market_breadth", ["trade_date"])
    op.create_index("ix_market_breadth_available_at", "market_breadth", ["available_at"])


def downgrade() -> None:
    op.drop_index("ix_market_breadth_available_at", table_name="market_breadth")
    op.drop_index("ix_market_breadth_trade_date", table_name="market_breadth")
    op.drop_index("ix_market_breadth_source_record_id", table_name="market_breadth")
    op.drop_table("market_breadth")
