"""add point in time portfolio quotes

Revision ID: 20260722_0020
Revises: 20260722_0015
"""
from alembic import op
import sqlalchemy as sa

revision = "20260722_0020"
down_revision = "20260722_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portfolio_position_quotes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("portfolio_id", sa.String(length=64), nullable=False),
        sa.Column("security_id", sa.String(length=32), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price", sa.Numeric(20, 6), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_portfolio_position_quotes_portfolio_id", "portfolio_position_quotes", ["portfolio_id"])
    op.create_index("ix_portfolio_position_quotes_security_id", "portfolio_position_quotes", ["security_id"])
    op.create_index("ix_portfolio_position_quotes_observed_at", "portfolio_position_quotes", ["observed_at"])


def downgrade() -> None:
    op.drop_table("portfolio_position_quotes")
