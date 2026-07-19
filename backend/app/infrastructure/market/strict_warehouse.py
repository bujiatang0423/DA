from __future__ import annotations

from datetime import datetime
from typing import Protocol

from backend.app.contracts.grades import DataGrade
from backend.app.core.market.pit_models import (
    LineageRef,
    PointInTimeSnapshot,
    QualityIssue,
    SnapshotScope,
    TemporalRecord,
)
from backend.app.core.market.snapshot import assemble_snapshot
from backend.app.features.backtests.pit_certificate import PitCertificate


class StrictRecordReader(Protocol):
    def read(
        self,
        *,
        as_of_time: datetime,
        scope: SnapshotScope,
    ) -> tuple[tuple[TemporalRecord, ...], tuple[LineageRef, ...], tuple[QualityIssue, ...]]: ...


class UnverifiedPitDataError(RuntimeError):
    pass


class StrictPointInTimeWarehouse:
    def __init__(self, reader: StrictRecordReader, certificate: PitCertificate | None) -> None:
        self._reader = reader
        self._certificate = certificate

    def snapshot(
        self,
        *,
        as_of_time: datetime,
        scope: SnapshotScope,
    ) -> PointInTimeSnapshot:
        certificate = self._certificate
        if certificate is None:
            raise UnverifiedPitDataError("certificate required")
        if not certificate.coverage_start <= as_of_time.date() <= certificate.coverage_end:
            raise UnverifiedPitDataError("outside certificate coverage")
        records, lineage, issues = self._reader.read(as_of_time=as_of_time, scope=scope)
        if any(record.available_at > as_of_time for record in records):
            raise UnverifiedPitDataError("reader returned future record")
        return assemble_snapshot(
            as_of_time=as_of_time,
            scope=scope,
            data_grade=DataGrade.PIT_VERIFIED,
            records=records,
            lineage=lineage,
            quality_issues=issues,
        )
