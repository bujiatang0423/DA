"""preserve buy dates on imported opening positions"""

from alembic import op
import sqlalchemy as sa


revision = "20260722_0015"
down_revision = "20260720_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("opening_positions", sa.Column("buy_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("opening_positions", "buy_date")
