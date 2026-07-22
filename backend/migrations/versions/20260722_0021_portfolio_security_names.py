"""persist user-maintained portfolio security names"""

from alembic import op
import sqlalchemy as sa


revision = "20260722_0021"
down_revision = "20260722_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("opening_positions", sa.Column("security_name", sa.String(length=256), nullable=True))
    op.add_column("portfolio_lot_projections", sa.Column("security_name", sa.String(length=256), nullable=True))


def downgrade() -> None:
    op.drop_column("portfolio_lot_projections", "security_name")
    op.drop_column("opening_positions", "security_name")
