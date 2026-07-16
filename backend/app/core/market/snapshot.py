from __future__ import annotations

import hashlib
import json
from datetime import datetime

from backend.app.contracts.grades import DataGrade
from backend.app.core.market.pit_models import (
    LineageRef, PointInTimeSnapshot, QualityIssue, SecurityObservation,
    SnapshotQuality, SnapshotScope, TemporalRecord,
)


class FutureDataError(ValueError):
    pass


def assemble_snapshot(*, as_of_time: datetime, scope: SnapshotScope,
                      data_grade: DataGrade, records: tuple[TemporalRecord, ...],
                      lineage: tuple[LineageRef, ...],
                      quality_issues: tuple[QualityIssue, ...]) -> PointInTimeSnapshot:
    if as_of_time.tzinfo is None:
        raise ValueError("as_of_time must be timezone-aware")
    ordered = tuple(sorted(records, key=lambda r: (r.entity_id, r.kind.value, r.record_id)))
    for record in ordered:
        if record.available_at.tzinfo is None:
            raise ValueError(f"available_at must be timezone-aware: {record.record_id}")
        if record.available_at > as_of_time:
            raise FutureDataError(f"future record: {record.record_id}")
    market = tuple(r for r in ordered if r.entity_id.startswith("MARKET:"))
    ids = sorted({r.entity_id for r in ordered if not r.entity_id.startswith("MARKET:")})
    securities = tuple(SecurityObservation(i, tuple(r for r in ordered if r.entity_id == i)) for i in ids)
    payload = {"as_of_time": as_of_time.isoformat(), "scope": scope.__dict__,
               "data_grade": data_grade.value,
               "records": [r.__dict__ for r in ordered],
               "lineage": [r.__dict__ for r in sorted(lineage, key=lambda x: x.source_artifact_hash)]}
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return PointInTimeSnapshot(as_of_time, scope, data_grade, market, securities,
                               SnapshotQuality(quality_issues), lineage,
                               hashlib.sha256(canonical.encode()).hexdigest())
