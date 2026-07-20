from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from hashlib import sha256
import json
from typing import Protocol
from zoneinfo import ZoneInfo

from backend.app.core.market.pit_models import (
    DataKind,
    PointInTimeSnapshot,
    SnapshotScope,
    TemporalRecord,
)


DAILY_REQUIRED_KINDS = (
    DataKind.SECURITY_MASTER,
    DataKind.SECURITY_STATUS,
    DataKind.TRADING_CALENDAR,
    DataKind.DAILY_BAR_RAW,
    DataKind.INDEX_DAILY_BAR,
    DataKind.ADJUSTMENT_FACTOR,
    DataKind.INDUSTRY_MEMBERSHIP,
    DataKind.THEME_MEMBERSHIP,
)

MARKET_WIDE_KINDS = frozenset(
    {
        DataKind.TRADING_CALENDAR,
        DataKind.INDEX_DAILY_BAR,
    }
)


class AuditablePointInTimeWarehouse(Protocol):
    """Read an unauthorised candidate snapshot for PIT audit only."""

    def candidate_snapshot(
        self,
        *,
        as_of_time: datetime,
        scope: SnapshotScope,
    ) -> PointInTimeSnapshot: ...

    def bundle_set_hash(self, coverage_start: date, coverage_end: date) -> str: ...


@dataclass(frozen=True)
class PitAuditReport:
    report_id: str
    coverage_start: date
    coverage_end: date
    bundle_set_hash: str
    checked_manifests: tuple[str, ...]
    failures: tuple[str, ...]
    audit_hash: str

    @property
    def passed(self) -> bool:
        return not self.failures


class PitAuditRunner:
    """Produce deterministic evidence that required point-in-time inputs are complete."""

    def __init__(
        self,
        warehouse: AuditablePointInTimeWarehouse,
        trading_dates: tuple[date, ...],
        security_ids: tuple[str, ...],
    ) -> None:
        self._warehouse = warehouse
        self._trading_dates = tuple(sorted(set(trading_dates)))
        if not security_ids:
            raise ValueError("PIT audit requires an explicit expected security universe")
        if len(security_ids) != len(set(security_ids)):
            raise ValueError("PIT audit security IDs must be unique")
        self._security_ids = tuple(sorted(security_ids))

    def run(self, *, coverage_start: date, coverage_end: date) -> PitAuditReport:
        if coverage_start > coverage_end:
            raise ValueError("PIT audit coverage start must not be after coverage end")

        failures: list[str] = []
        manifests: list[str] = []
        dates = tuple(
            item for item in self._trading_dates if coverage_start <= item <= coverage_end
        )
        if not dates:
            failures.append("TRADING_CALENDAR_COVERAGE_MISSING")

        for trading_date in dates:
            as_of_time = datetime.combine(
                trading_date,
                time(15, 30),
                ZoneInfo("Asia/Shanghai"),
            )
            for kind in DAILY_REQUIRED_KINDS:
                self._audit_snapshot(
                    as_of_time=as_of_time,
                    kind=kind,
                    failures=failures,
                    manifests=manifests,
                )

        bundle_set_hash = self._warehouse.bundle_set_hash(coverage_start, coverage_end)
        body = {
            "bundle_set_hash": bundle_set_hash,
            "coverage_end": coverage_end.isoformat(),
            "coverage_start": coverage_start.isoformat(),
            "failures": sorted(failures),
            "manifests": sorted(manifests),
        }
        audit_hash = sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return PitAuditReport(
            report_id=audit_hash[:24],
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            bundle_set_hash=bundle_set_hash,
            checked_manifests=tuple(sorted(manifests)),
            failures=tuple(sorted(failures)),
            audit_hash=audit_hash,
        )

    def _audit_snapshot(
        self,
        *,
        as_of_time: datetime,
        kind: DataKind,
        failures: list[str],
        manifests: list[str],
    ) -> None:
        failure_prefix = f"{kind.value}:{as_of_time.date().isoformat()}"
        try:
            snapshot = self._warehouse.candidate_snapshot(
                as_of_time=as_of_time,
                scope=SnapshotScope(self._security_ids, (kind,)),
            )
        except Exception as error:
            failures.append(f"{failure_prefix}:{type(error).__name__}")
            return
        if snapshot.as_of_time != as_of_time:
            failures.append(f"{failure_prefix}:AS_OF_MISMATCH")
            return
        expected_scope = SnapshotScope(self._security_ids, (kind,))
        if snapshot.scope != expected_scope:
            failures.append(f"{failure_prefix}:SCOPE_MISMATCH")
            return
        if snapshot.quality.has_errors:
            failures.append(failure_prefix)
            return
        records = snapshot.market_inputs + tuple(
            record
            for observation in snapshot.security_observations
            for record in observation.records
        )
        if any(record.kind is not kind for record in records):
            failures.append(f"{failure_prefix}:UNEXPECTED_KIND")
            return
        matching_records = tuple(record for record in records if record.kind is kind)
        if not matching_records:
            failures.append(f"{failure_prefix}:RECORDS_MISSING")
            return
        if not _records_are_as_of_safe(matching_records, as_of_time):
            failures.append(f"{failure_prefix}:FUTURE_RECORD")
            return
        if not _has_required_entities(kind, matching_records, self._security_ids):
            failures.append(f"{failure_prefix}:ENTITY_COVERAGE_MISSING")
            return
        manifests.append(snapshot.manifest_hash)


def _records_are_as_of_safe(
    records: tuple[TemporalRecord, ...],
    as_of_time: datetime,
) -> bool:
    for record in records:
        if (
            record.available_at.tzinfo is None
            or record.available_at.utcoffset() is None
            or record.event_time.tzinfo is None
            or record.event_time.utcoffset() is None
            or record.available_at > as_of_time
            or record.event_time > as_of_time
        ):
            return False
    return True


def _has_required_entities(
    kind: DataKind,
    records: tuple[TemporalRecord, ...],
    security_ids: tuple[str, ...],
) -> bool:
    entity_ids = {record.entity_id for record in records}
    if kind in MARKET_WIDE_KINDS:
        return any(entity_id.startswith("MARKET:") for entity_id in entity_ids)
    return set(security_ids).issubset(entity_ids)
