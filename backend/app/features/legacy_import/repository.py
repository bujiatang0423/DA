from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.core.portfolio.models import OpeningPosition
from backend.app.infrastructure.persistence.legacy_rows import (
    LegacyImportBatchRow,
    LegacyRawFileRow,
    LegacyPositionSnapshotRow,
    OpeningPositionRow,
)
from .service import ImportedBatch, ImportedHistoricalPosition, ImportedRawFile


class SqlLegacyRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(
        self,
        batch: ImportedBatch,
        raw_files: tuple[ImportedRawFile, ...],
        positions: tuple[OpeningPosition, ...],
        historical_snapshots: tuple[ImportedHistoricalPosition, ...],
    ) -> bool:
        if self.session.scalar(
            select(LegacyImportBatchRow).where(
                LegacyImportBatchRow.manifest_sha256 == batch.manifest_sha256
            )
        ):
            return False
        self.session.add(
            LegacyImportBatchRow(
                id=batch.batch_id,
                source_root=batch.source_root,
                source_git_state=batch.source_git_state,
                imported_at=batch.imported_at,
                effective_at=batch.effective_at,
                portfolio_id=batch.portfolio_id,
                manifest_sha256=batch.manifest_sha256,
                quality_report_json=batch.quality_report_json,
            )
        )
        self.session.add_all(
            LegacyRawFileRow(
                batch_id=batch.batch_id,
                relative_path=x.relative_path,
                sha256=x.sha256,
                quality_tags_json=x.quality_tags_json,
            )
            for x in raw_files
        )
        self.session.add_all(
            OpeningPositionRow(
                batch_id=batch.batch_id,
                portfolio_id=batch.portfolio_id,
                security_id=x.security_id,
                quantity=x.quantity,
                inherited_unit_cost=x.inherited_unit_cost,
                effective_at=x.effective_at,
                origin=x.origin.value,
                source_row_hash=x.source_row_hash,
            )
            for x in positions
        )
        self.session.add_all(
            LegacyPositionSnapshotRow(
                batch_id=batch.batch_id,
                snapshot_at=x.snapshot_at,
                security_id=x.security_id,
                quantity=x.quantity,
                inherited_unit_cost=x.inherited_unit_cost,
                imported_buy_date=x.imported_buy_date,
                source_file_sha256=x.source_file_sha256,
                raw_row_json=x.raw_row_json,
            )
            for x in historical_snapshots
        )
        self.session.flush()
        return True
