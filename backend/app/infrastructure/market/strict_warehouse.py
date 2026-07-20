from __future__ import annotations

from datetime import date, datetime
from typing import Protocol

from backend.app.contracts.grades import DataGrade
from backend.app.core.market.pit_models import (
    LineageRef,
    PointInTimeSnapshot,
    QualityIssue,
    QualitySeverity,
    SnapshotScope,
    TemporalRecord,
)
from backend.app.core.market.snapshot import assemble_snapshot
from backend.app.features.backtests.pit_certificate import (
    PitCertificate,
    lineage_set_hash,
    selected_snapshot_hash,
)


class StrictRecordReader(Protocol):
    def read(
        self,
        *,
        as_of_time: datetime,
        scope: SnapshotScope,
    ) -> tuple[tuple[TemporalRecord, ...], tuple[LineageRef, ...], tuple[QualityIssue, ...]]: ...


class PitCertificateAuthority(Protocol):
    def bundle_set_hash_for(self, as_of_date: date) -> str: ...

    def certificate_for(
        self,
        *,
        as_of_time: datetime,
        scope: SnapshotScope,
        bundle_set_hash: str,
        lineage_hash: str,
        selected_snapshot_hash: str,
    ) -> PitCertificate | None: ...


class UnverifiedPitDataError(RuntimeError):
    pass


class StrictPointInTimeWarehouse:
    def __init__(
        self,
        reader: StrictRecordReader,
        certificate_authority: PitCertificateAuthority,
    ) -> None:
        self._reader = reader
        self._certificate_authority = certificate_authority

    def snapshot(
        self,
        *,
        as_of_time: datetime,
        scope: SnapshotScope,
    ) -> PointInTimeSnapshot:
        records, lineage, issues = self._reader.read(as_of_time=as_of_time, scope=scope)
        if any(record.available_at > as_of_time for record in records):
            raise UnverifiedPitDataError("reader returned future record")
        if any(issue.severity is QualitySeverity.ERROR for issue in issues):
            raise UnverifiedPitDataError("required strict data is unavailable")
        try:
            bundle_set_hash = self._certificate_authority.bundle_set_hash_for(as_of_time.date())
        except ValueError as error:
            raise UnverifiedPitDataError("persisted PIT bundle coverage is unavailable") from error
        certificate = self._certificate_authority.certificate_for(
            as_of_time=as_of_time,
            scope=scope,
            bundle_set_hash=bundle_set_hash,
            lineage_hash=lineage_set_hash(lineage),
            selected_snapshot_hash=selected_snapshot_hash(records, lineage),
        )
        if certificate is None:
            raise UnverifiedPitDataError("approved certificate required")
        return assemble_snapshot(
            as_of_time=as_of_time,
            scope=scope,
            data_grade=DataGrade.PIT_VERIFIED,
            records=records,
            lineage=lineage,
            quality_issues=issues,
        )
