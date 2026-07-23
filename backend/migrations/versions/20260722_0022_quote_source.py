"""record quote source"""
from alembic import op
import sqlalchemy as sa

revision = "20260722_0022"
down_revision = "20260722_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("portfolio_position_quotes", sa.Column("source", sa.String(32), nullable=True))
    op.execute("update portfolio_position_quotes set source='legacy_fixture' where source is null")
    op.alter_column("portfolio_position_quotes", "source", nullable=False)


def downgrade() -> None:
    op.drop_column("portfolio_position_quotes", "source")
