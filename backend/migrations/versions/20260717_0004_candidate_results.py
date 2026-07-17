"""persist candidate recommendation results

Revision ID: 20260717_0004
Revises: 20260717_0003
"""

from alembic import op
import sqlalchemy as sa

revision = "20260717_0004"
down_revision = "20260717_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "candidate_results",
        sa.Column("run_id", sa.String(length=64), primary_key=True),
        sa.Column("as_of_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_candidate_results_as_of_time", "candidate_results", ["as_of_time"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_candidate_results_as_of_time", table_name="candidate_results")
    op.drop_table("candidate_results")
