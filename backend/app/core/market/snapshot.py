from __future__ import annotations

import hashlib
import json
from datetime import datetime, UTC

from backend.app.contracts.grades import DataGrade
from backend.app.core.market.pit_models import (
    LineageRef,
    PointInTimeSnapshot,
    QualityIssue,
    SecurityObservation,
    SnapshotQuality,
    SnapshotScope,
    TemporalRecord,
)


class FutureDataError(ValueError):
    pass


def assemble_snapshot(
    *,
    as_of_time: datetime,
    scope: SnapshotScope,
    data_grade: DataGrade,
    records: tuple[TemporalRecord, ...],
    lineage: tuple[LineageRef, ...],
    quality_issues: tuple[QualityIssue, ...],
) -> PointInTimeSnapshot:
    if as_of_time.tzinfo is None or as_of_time.utcoffset() is None:
        raise ValueError("as_of_time must be timezone-aware")
    as_of_utc = as_of_time.astimezone(UTC)
    selected: list[TemporalRecord] = []
    allowed = set(scope.security_ids)
    for record in records:
        if record.available_at.tzinfo is None or record.available_at.utcoffset() is None:
            raise ValueError(f"available_at must be timezone-aware: {record.record_id}")
        event = record.event_time
        if event.tzinfo is None or event.utcoffset() is None:
            raise ValueError(f"event_time must be timezone-aware: {record.record_id}")
        if record.available_at.astimezone(UTC) > as_of_utc or event.astimezone(UTC) > as_of_utc:
            raise FutureDataError(f"future record: {record.record_id}")
        if (
            not record.entity_id.startswith("MARKET:")
            and allowed
            and record.entity_id not in allowed
        ):
            continue
        if scope.history_start is not None and event.astimezone(
            UTC
        ) < scope.history_start.astimezone(UTC):
            continue
        selected.append(record)
    ordered = tuple(sorted(selected, key=lambda r: (r.entity_id, r.kind.value, r.record_id)))
    market = tuple(r for r in ordered if r.entity_id.startswith("MARKET:"))
    ids = sorted({r.entity_id for r in ordered if not r.entity_id.startswith("MARKET:")})
    securities = tuple(
        SecurityObservation(i, tuple(r for r in ordered if r.entity_id == i)) for i in ids
    )
    payload = {
        "as_of_time": as_of_time.isoformat(),
        "scope": scope.__dict__,
        "data_grade": data_grade.value,
        "records": [r.__dict__ for r in ordered],
        "lineage": [r.__dict__ for r in sorted(lineage, key=lambda x: x.source_artifact_hash)],
    }
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return PointInTimeSnapshot(
        as_of_time,
        scope,
        data_grade,
        market,
        securities,
        SnapshotQuality(quality_issues),
        lineage,
        hashlib.sha256(canonical.encode()).hexdigest(),
    )
