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
            {
                "batch_id": item.batch_id,
                "provider": item.provider,
                "source_artifact_hash": item.source_artifact_hash,
            }
            for item in sorted(
                lineage,
                key=lambda item: (item.provider, item.batch_id, item.source_artifact_hash),
            )
        ],
        "records": [
            {
                "available_at": item.available_at.isoformat(),
                "entity_id": item.entity_id,
                "event_time": item.event_time.isoformat(),
                "kind": item.kind.value,
                "observed_at": item.observed_at.isoformat(),
                "payload": item.payload,
                "record_id": item.record_id,
                "source_artifact_hash": item.source_artifact_hash,
            }
            for item in sorted(records, key=lambda item: (item.kind.value, item.record_id))
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(canonical.encode("utf-8")).hexdigest()
