"""bind audit reports to the market and universe they certified

Revision ID: 20260720_0014
Revises: 20260720_0013
"""

from alembic import op
import sqlalchemy as sa


revision = "20260720_0014"
down_revision = "20260720_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("market_breadth", "market_id", existing_type=sa.String(32), nullable=True)
    op.alter_column("market_breadth", "universe_id", existing_type=sa.String(64), nullable=True)
    op.execute("UPDATE market_breadth SET market_id = NULL, universe_id = NULL")
    op.add_column("pit_audit_reports", sa.Column("market_id", sa.String(32), nullable=True))
    op.add_column("pit_audit_reports", sa.Column("universe_id", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("pit_audit_reports", "universe_id")
    op.drop_column("pit_audit_reports", "market_id")
    op.execute("DELETE FROM market_breadth WHERE market_id IS NULL OR universe_id IS NULL")
    op.alter_column("market_breadth", "universe_id", existing_type=sa.String(64), nullable=False)
    op.alter_column("market_breadth", "market_id", existing_type=sa.String(32), nullable=False)
