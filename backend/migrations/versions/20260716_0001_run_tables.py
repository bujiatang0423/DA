from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260716_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("request_payload", postgresql.JSONB, nullable=False),
        sa.Column("idempotency_key", sa.String(128)),
        sa.Column("stage", sa.String(64)),
        sa.Column("progress", sa.Integer, nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("retry_count", sa.Integer, nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text),
    )
    op.create_unique_constraint("uq_runs_kind_idempotency", "runs", ["kind", "idempotency_key"])
    op.create_index("ix_runs_claim", "runs", ["status", "submitted_at"])
    op.create_table(
        "run_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("runs.id", ondelete="CASCADE")
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
    )
    op.create_index("ix_run_events_run_id", "run_events", ["run_id"])
    op.create_table(
        "run_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("runs.id", ondelete="CASCADE")
        ),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("relative_path", sa.Text, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_run_artifacts_run_id", "run_artifacts", ["run_id"])


def downgrade() -> None:
    op.drop_table("run_artifacts")
    op.drop_table("run_events")
    op.drop_table("runs")
