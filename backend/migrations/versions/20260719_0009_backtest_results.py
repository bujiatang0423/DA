"""persist auditable backtest result projections

Revision ID: 20260719_0009
Revises: 20260719_0008
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260719_0009"
down_revision = "20260719_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backtest_results",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("strategy_version", sa.String(128), nullable=False),
        sa.Column("input_manifest_hash", sa.String(64), nullable=False),
        sa.Column("request_payload", postgresql.JSONB(), nullable=False),
        sa.Column("warnings", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
    )
    op.create_index("ix_backtest_results_created_at", "backtest_results", ["created_at"])
    op.create_index(
        "ix_backtest_results_input_manifest_hash", "backtest_results", ["input_manifest_hash"]
    )
    op.create_table(
        "backtest_group_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("backtest_results.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("group", sa.String(1), nullable=False),
        sa.Column("data_grade", sa.String(32), nullable=False),
        sa.Column("llm_grade", sa.String(32), nullable=False),
        sa.Column("input_manifest_hash", sa.String(64), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("metric_details", postgresql.JSONB(), nullable=False),
        sa.Column("comparison_inputs", postgresql.JSONB(), nullable=False),
        sa.Column("out_of_sample_start", sa.String(10), nullable=True),
        sa.Column("warnings", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("run_id", "group", name="uq_backtest_group_result"),
    )
    op.create_index("ix_backtest_group_results_run_id", "backtest_group_results", ["run_id"])
    for table in ("backtest_curve_points", "backtest_trades", "backtest_rejected_attempts"):
        op.create_table(
            table,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "run_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("backtest_results.run_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("group", sa.String(1), nullable=False),
            sa.Column("ordinal", sa.Integer(), nullable=False),
            sa.Column("cursor", sa.String(128), nullable=False),
            sa.Column("payload", postgresql.JSONB(), nullable=False),
            sa.UniqueConstraint("run_id", "group", "ordinal", name=f"uq_{table[:-1]}"),
        )
        op.create_index(f"ix_{table}_run_id", table, ["run_id"])


def downgrade() -> None:
    for table in ("backtest_rejected_attempts", "backtest_trades", "backtest_curve_points"):
        op.drop_index(f"ix_{table}_run_id", table_name=table)
        op.drop_table(table)
    op.drop_index("ix_backtest_group_results_run_id", table_name="backtest_group_results")
    op.drop_table("backtest_group_results")
    op.drop_index("ix_backtest_results_input_manifest_hash", table_name="backtest_results")
    op.drop_index("ix_backtest_results_created_at", table_name="backtest_results")
    op.drop_table("backtest_results")
