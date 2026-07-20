"""project holding analysis items in a queryable child table

Revision ID: 20260720_0011
Revises: 20260720_0010
"""

from alembic import op
import sqlalchemy as sa


revision = "20260720_0011"
down_revision = "20260720_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "holding_analysis_items",
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("holding_analysis_results.run_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("item_index", sa.Integer(), primary_key=True),
        sa.Column("security_id", sa.String(length=64), nullable=False),
        sa.Column("security_name", sa.String(length=256), nullable=False),
        sa.Column("origin", sa.String(length=64), nullable=False),
        sa.Column("strategy_book", sa.String(length=64), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("available_to_sell", sa.Integer(), nullable=False),
        sa.Column("average_cost", sa.String(length=64), nullable=False),
        sa.Column("close", sa.String(length=64), nullable=False),
        sa.Column("market_state", sa.String(length=64), nullable=False),
        sa.Column("factors", sa.JSON(), nullable=False),
        sa.Column("r_multiple", sa.String(length=64), nullable=True),
        sa.Column("effective_stop", sa.String(length=64), nullable=True),
        sa.Column("proposed_effective_stop", sa.String(length=64), nullable=True),
        sa.Column("advised_action", sa.String(length=64), nullable=False),
        sa.Column("planned_quantity", sa.Integer(), nullable=False),
        sa.Column("pending_target_action", sa.String(length=64), nullable=True),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("quality_codes", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_holding_analysis_items_security_id", "holding_analysis_items", ["security_id"]
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            INSERT INTO holding_analysis_items (
                run_id, item_index, security_id, security_name, origin, strategy_book,
                quantity, available_to_sell, average_cost, close, market_state, factors,
                r_multiple, effective_stop, proposed_effective_stop, advised_action,
                planned_quantity, pending_target_action, reason_codes, quality_codes, evidence_refs
            )
            SELECT
                result.run_id,
                item.ordinality - 1,
                item.value ->> 'security_id',
                item.value ->> 'security_name',
                item.value ->> 'origin',
                item.value ->> 'strategy_book',
                (item.value ->> 'quantity')::integer,
                (item.value ->> 'available_to_sell')::integer,
                item.value ->> 'average_cost',
                item.value ->> 'close',
                item.value ->> 'market_state',
                item.value -> 'factors',
                item.value ->> 'r_multiple',
                item.value ->> 'effective_stop',
                item.value ->> 'proposed_effective_stop',
                item.value ->> 'advised_action',
                (item.value ->> 'planned_quantity')::integer,
                item.value ->> 'pending_target_action',
                item.value -> 'reason_codes',
                item.value -> 'quality_codes',
                item.value -> 'evidence_refs'
            FROM holding_analysis_results AS result
            CROSS JOIN LATERAL jsonb_array_elements(result.payload::jsonb -> 'items')
                WITH ORDINALITY AS item(value, ordinality)
            ON CONFLICT (run_id, item_index) DO NOTHING
            """
        )


def downgrade() -> None:
    op.drop_index("ix_holding_analysis_items_security_id", table_name="holding_analysis_items")
    op.drop_table("holding_analysis_items")
