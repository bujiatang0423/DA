"""bind strict market breadth to an auditable market universe

Revision ID: 20260720_0013
Revises: 20260720_0012
"""

from alembic import op
import sqlalchemy as sa


revision = "20260720_0013"
down_revision = "20260720_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "market_breadth",
        sa.Column("market_id", sa.String(32), nullable=True),
    )
    op.add_column(
        "market_breadth",
        sa.Column("universe_id", sa.String(64), nullable=True),
    )
    op.create_index("ix_market_breadth_market_id", "market_breadth", ["market_id"])
    op.create_index("ix_market_breadth_universe_id", "market_breadth", ["universe_id"])


def downgrade() -> None:
    op.drop_index("ix_market_breadth_universe_id", table_name="market_breadth")
    op.drop_index("ix_market_breadth_market_id", table_name="market_breadth")
    op.drop_column("market_breadth", "universe_id")
    op.drop_column("market_breadth", "market_id")
