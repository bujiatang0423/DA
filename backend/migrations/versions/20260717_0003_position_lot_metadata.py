from alembic import op
import sqlalchemy as sa


revision = "20260717_0003"
down_revision = "20260716_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "portfolio_lot_projections",
        sa.Column("batch_id", sa.String(64), nullable=False, server_default="default"),
    )
    op.add_column(
        "portfolio_lot_projections",
        sa.Column("buy_date", sa.Date(), nullable=True),
    )
    op.alter_column("portfolio_lot_projections", "batch_id", server_default=None)


def downgrade() -> None:
    op.drop_column("portfolio_lot_projections", "buy_date")
    op.drop_column("portfolio_lot_projections", "batch_id")
