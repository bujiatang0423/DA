from alembic import op
import sqlalchemy as sa

revision = "20260716_0002"
down_revision = "20260716_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pit_lineage_batches",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False, unique=True),
    )
    op.create_table(
        "pit_source_artifacts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "batch_id", sa.String(64), sa.ForeignKey("pit_lineage_batches.id"), nullable=False
        ),
        sa.Column("source_path", sa.Text, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("sha256", name="uq_source_artifacts_sha256"),
    )
    op.create_table(
        "legacy_import_batches",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source_root", sa.Text, nullable=False),
        sa.Column("source_git_state", sa.String(128), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("portfolio_id", sa.String(64), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("quality_report_json", sa.Text, nullable=False),
    )
    op.create_table(
        "legacy_raw_files",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "batch_id", sa.String(64), sa.ForeignKey("legacy_import_batches.id"), nullable=False
        ),
        sa.Column("relative_path", sa.Text, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("quality_tags_json", sa.Text, nullable=False),
        sa.UniqueConstraint("batch_id", "relative_path", name="uq_legacy_raw_batch_path"),
    )
    op.create_table(
        "legacy_position_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "batch_id", sa.String(64), sa.ForeignKey("legacy_import_batches.id"), nullable=False
        ),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("security_id", sa.String(32), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("inherited_unit_cost", sa.Numeric(20, 6), nullable=False),
        sa.Column("imported_buy_date", sa.String(10)),
        sa.Column("source_file_sha256", sa.String(64), nullable=False),
        sa.Column("raw_row_json", sa.Text, nullable=False),
    )
    op.create_table(
        "opening_positions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "batch_id", sa.String(64), sa.ForeignKey("legacy_import_batches.id"), nullable=False
        ),
        sa.Column("portfolio_id", sa.String(64), nullable=False),
        sa.Column("security_id", sa.String(32), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("inherited_unit_cost", sa.Numeric(20, 6), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("source_row_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("batch_id", "security_id", name="uq_opening_batch_security"),
    )
    op.create_table(
        "portfolio_versions",
        sa.Column("portfolio_id", sa.String(64), primary_key=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_table(
        "portfolio_snapshot_projections",
        sa.Column("portfolio_id", sa.String(64), primary_key=True),
        sa.Column("as_of_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cash", sa.Numeric(24, 6), nullable=False),
        sa.Column("equity", sa.Numeric(24, 6), nullable=False),
    )
    op.create_table(
        "portfolio_lot_projections",
        sa.Column("lot_id", sa.String(64), primary_key=True),
        sa.Column("portfolio_id", sa.String(64), nullable=False),
        sa.Column("security_id", sa.String(32), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("available_to_sell", sa.Integer, nullable=False),
        sa.Column("average_cost", sa.Numeric(20, 6), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("strategy_book", sa.String(16)),
        sa.Column("entry_score", sa.Numeric(8, 4)),
        sa.Column("initial_risk_per_share", sa.Numeric(20, 6)),
        sa.Column("effective_stop", sa.Numeric(20, 6)),
        sa.Column("highest_close", sa.Numeric(20, 6)),
        sa.Column("add_count", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_portfolio_lot_projections_portfolio_id",
        "portfolio_lot_projections",
        ["portfolio_id"],
    )
    op.create_table(
        "portfolio_audit_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("portfolio_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("expected_version", sa.Integer, nullable=False),
        sa.Column("resulting_version", sa.Integer, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.UniqueConstraint("portfolio_id", "resulting_version", name="uq_portfolio_event_version"),
    )


def downgrade() -> None:
    for table in (
        "portfolio_audit_events",
        "portfolio_lot_projections",
        "portfolio_snapshot_projections",
        "portfolio_versions",
        "opening_positions",
        "legacy_position_snapshots",
        "legacy_raw_files",
        "legacy_import_batches",
        "pit_source_artifacts",
        "pit_lineage_batches",
    ):
        op.drop_table(table)
