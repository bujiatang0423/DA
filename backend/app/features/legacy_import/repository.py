from sqlalchemy import func, select
from sqlalchemy.orm import Session
from backend.app.core.portfolio.models import OpeningPosition
from backend.app.infrastructure.persistence.legacy_rows import (
    LegacyImportBatchRow,
    LegacyRawFileRow,
    LegacyPositionSnapshotRow,
    OpeningPositionRow,
)
from .service import ImportedBatch, ImportedHistoricalPosition, ImportedRawFile
from .web_service import LegacyImportResult


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

    def get_summary(self, batch_id: str) -> LegacyImportResult | None:
        batch = self.session.get(LegacyImportBatchRow, batch_id)
        if batch is None:
            return None
        return LegacyImportResult(
            batch_id=batch.id,
            manifest_sha256=batch.manifest_sha256,
            portfolio_id=batch.portfolio_id,
            effective_at=batch.effective_at,
            raw_file_count=self._raw_file_count(batch_id),
            opening_position_count=self._opening_position_count(batch_id),
            historical_snapshot_count=self._historical_snapshot_count(batch_id),
            idempotent=False,
        )

    def _raw_file_count(self, batch_id: str) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(LegacyRawFileRow)
                .where(LegacyRawFileRow.batch_id == batch_id)
            )
            or 0
        )

    def _opening_position_count(self, batch_id: str) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(OpeningPositionRow)
                .where(OpeningPositionRow.batch_id == batch_id)
            )
            or 0
        )

    def _historical_snapshot_count(self, batch_id: str) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(LegacyPositionSnapshotRow)
                .where(LegacyPositionSnapshotRow.batch_id == batch_id)
            )
            or 0
        )
