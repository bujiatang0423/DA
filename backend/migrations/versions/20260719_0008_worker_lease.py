"""persist worker lease ownership for durable run claims

Revision ID: 20260719_0008
Revises: 20260718_0007
"""

from alembic import op
import sqlalchemy as sa


revision = "20260719_0008"
down_revision = "20260718_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worker_leases",
        sa.Column("worker_id", sa.String(64), primary_key=True),
        sa.Column("lease_token", sa.String(64), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_worker_leases_heartbeat_at", "worker_leases", ["heartbeat_at"])
    op.add_column("runs", sa.Column("claim_owner", sa.String(64), nullable=True))
    op.add_column("runs", sa.Column("claim_token", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "claim_token")
    op.drop_column("runs", "claim_owner")
    op.drop_index("ix_worker_leases_heartbeat_at", table_name="worker_leases")
    op.drop_table("worker_leases")
