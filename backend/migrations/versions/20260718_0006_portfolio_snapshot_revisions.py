"""preserve point-in-time portfolio projections

Revision ID: 20260718_0006
Revises: 20260717_0005
"""

from alembic import op
import sqlalchemy as sa


revision = "20260718_0006"
down_revision = "20260717_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portfolio_snapshot_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("portfolio_id", sa.String(length=64), nullable=False),
        sa.Column("as_of_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("cash", sa.Numeric(24, 6), nullable=False),
        sa.Column("equity", sa.Numeric(24, 6), nullable=False),
        sa.Column("lots", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "portfolio_id",
            "as_of_time",
            "version",
            name="uq_portfolio_snapshot_revision",
        ),
    )
    op.create_index(
        "ix_portfolio_snapshot_revisions_portfolio_id",
        "portfolio_snapshot_revisions",
        ["portfolio_id"],
    )
    op.create_index(
        "ix_portfolio_snapshot_revisions_as_of_time",
        "portfolio_snapshot_revisions",
        ["as_of_time"],
    )


def downgrade() -> None:
    op.drop_index("ix_portfolio_snapshot_revisions_as_of_time", "portfolio_snapshot_revisions")
    op.drop_index("ix_portfolio_snapshot_revisions_portfolio_id", "portfolio_snapshot_revisions")
    op.drop_table("portfolio_snapshot_revisions")
