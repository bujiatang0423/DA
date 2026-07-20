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

REQUIRED_SECURITY_KINDS = frozenset(
    {
        DataKind.SECURITY_MASTER,
        DataKind.SECURITY_STATUS,
        DataKind.DAILY_BAR_RAW,
    }
)

REQUIRED_MARKET_KINDS = frozenset(
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


class AuditUniverseResolver(Protocol):
    """Resolve the auditable security universe visible at one exact point in time."""

    def security_ids_for(self, as_of_time: datetime) -> tuple[str, ...]: ...


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
        universe: AuditUniverseResolver,
    ) -> None:
        self._warehouse = warehouse
        self._trading_dates = tuple(sorted(set(trading_dates)))
        self._universe = universe

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
            self._audit_snapshot(
                as_of_time=as_of_time,
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
        failures: list[str],
        manifests: list[str],
    ) -> None:
        failure_date = as_of_time.date().isoformat()
        try:
            security_ids = self._security_ids_for(as_of_time)
        except Exception as error:
            failures.append(f"security_master:{failure_date}:{type(error).__name__}")
            return
        expected_scope = SnapshotScope(security_ids, DAILY_REQUIRED_KINDS)
        try:
            snapshot = self._warehouse.candidate_snapshot(
                as_of_time=as_of_time,
                scope=expected_scope,
            )
        except Exception as error:
            failures.append(f"snapshot:{failure_date}:{type(error).__name__}")
            return
        if snapshot.as_of_time != as_of_time:
            failures.append(f"snapshot:{failure_date}:AS_OF_MISMATCH")
            return
        if not _scope_covers(snapshot.scope, expected_scope):
            failures.append(f"snapshot:{failure_date}:SCOPE_MISMATCH")
            return
        if snapshot.quality.has_errors:
            failures.append(f"snapshot:{failure_date}:QUALITY_ERROR")
            return
        records = snapshot.market_inputs + tuple(
            record
            for observation in snapshot.security_observations
            for record in observation.records
        )
        if not _records_are_as_of_safe(records, as_of_time):
            failures.append(f"snapshot:{failure_date}:FUTURE_RECORD")
            return
        coverage_failed = False
        for kind in DAILY_REQUIRED_KINDS:
            matching_records = tuple(record for record in records if record.kind is kind)
            if kind in REQUIRED_SECURITY_KINDS and not set(security_ids).issubset(
                {record.entity_id for record in matching_records}
            ):
                failures.append(f"{kind.value}:{failure_date}:ENTITY_COVERAGE_MISSING")
                coverage_failed = True
            elif kind in REQUIRED_MARKET_KINDS and not any(
                record.entity_id.startswith("MARKET:") for record in matching_records
            ):
                failures.append(f"{kind.value}:{failure_date}:RECORDS_MISSING")
                coverage_failed = True
        if coverage_failed:
            return
        manifests.append(snapshot.manifest_hash)

    def _security_ids_for(self, as_of_time: datetime) -> tuple[str, ...]:
        security_ids = tuple(sorted(set(self._universe.security_ids_for(as_of_time))))
        if not security_ids:
            raise ValueError("PIT audit security universe is empty")
        return security_ids


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


def _scope_covers(actual: SnapshotScope, expected: SnapshotScope) -> bool:
    return (
        actual.security_ids == expected.security_ids
        and actual.history_start == expected.history_start
        and set(actual.required_kinds).issuperset(expected.required_kinds)
    )
