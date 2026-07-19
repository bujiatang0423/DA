from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
from backend.app.core.market.pit_models import LineageRef, TemporalRecord


@dataclass(frozen=True)
class PitCertificate:
    audit_report_id: str
    coverage_start: date
    coverage_end: date
    bundle_set_hash: str
    audit_hash: str


def lineage_set_hash(lineage: tuple[LineageRef, ...]) -> str:
    """Return the stable digest of the exact source lineage selected for a snapshot."""
    payload = [
        {
            "batch_id": item.batch_id,
            "provider": item.provider,
            "source_artifact_hash": item.source_artifact_hash,
        }
        for item in sorted(
            lineage,
            key=lambda item: (item.provider, item.batch_id, item.source_artifact_hash),
        )
    ]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def selected_snapshot_hash(
    records: tuple[TemporalRecord, ...],
    lineage: tuple[LineageRef, ...],
) -> str:
    """Fingerprint exact selected rows, not merely their source artifact hashes."""
    payload = {
        "version": 1,
        "lineage": [
            (item.batch_id, item.provider, item.source_artifact_hash)
            for item in sorted(lineage, key=lambda item: item.batch_id)
        ],
        "records": [
            (
                item.record_id,
                item.kind.value,
                item.entity_id,
                item.event_time.isoformat(),
                item.observed_at.isoformat(),
                item.available_at.isoformat(),
                item.source_artifact_hash,
            )
            for item in sorted(records, key=lambda item: (item.kind.value, item.record_id))
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(canonical.encode("utf-8")).hexdigest()
