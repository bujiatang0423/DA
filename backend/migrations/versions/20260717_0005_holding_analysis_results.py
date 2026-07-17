"""persist holding analysis results

Revision ID: 20260717_0005
Revises: 20260717_0004
"""

from alembic import op
import sqlalchemy as sa

revision = "20260717_0005"
down_revision = "20260717_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "holding_analysis_results",
        sa.Column("run_id", sa.String(length=64), primary_key=True),
        sa.Column("as_of_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_holding_analysis_results_as_of_time", "holding_analysis_results", ["as_of_time"]
    )


def downgrade() -> None:
    op.drop_index("ix_holding_analysis_results_as_of_time", table_name="holding_analysis_results")
    op.drop_table("holding_analysis_results")
