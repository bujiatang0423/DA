from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from hashlib import sha256
import hmac
import json
from string import hexdigits
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
    DataKind.MARKET_BREADTH,
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
        DataKind.MARKET_BREADTH,
    }
)

COVERAGE_EVIDENCE_KINDS = frozenset(
    {
        DataKind.ADJUSTMENT_FACTOR,
        DataKind.INDUSTRY_MEMBERSHIP,
        DataKind.THEME_MEMBERSHIP,
    }
)

OPTIONAL_ZERO_MEMBERSHIP_KINDS = frozenset(
    {
        DataKind.INDUSTRY_MEMBERSHIP,
        DataKind.THEME_MEMBERSHIP,
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

    def coverage_evidence(
        self,
        *,
        as_of_time: datetime,
        scope: SnapshotScope,
    ) -> tuple[DatasetCoverageEvidence, ...]: ...


class AuditUniverseResolver(Protocol):
    """Resolve the auditable security universe visible at one exact point in time."""

    def security_ids_for(self, as_of_time: datetime) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class DatasetCoverageEvidence:
    """Evidence that a sparse PIT dataset was checked for a dated universe."""

    kind: DataKind
    as_of_time: datetime
    security_ids: tuple[str, ...]
    covered_security_ids: tuple[str, ...]
    known_empty_security_ids: tuple[str, ...]
    source_hash: str
    evidence_digest: str


@dataclass(frozen=True)
class PitAuditReport:
    report_id: str
    coverage_start: date
    coverage_end: date
    market_id: str
    universe_id: str
    bundle_set_hash: str
    checked_manifests: tuple[str, ...]
    coverage_evidence_digests: tuple[str, ...]
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
        *,
        market_id: str,
        universe_id: str,
    ) -> None:
        self._warehouse = warehouse
        self._trading_dates = tuple(sorted(set(trading_dates)))
        self._universe = universe
        if not market_id or not universe_id:
            raise ValueError("PIT audit market and universe identities are required")
        self._market_id = market_id
        self._universe_id = universe_id

    def run(self, *, coverage_start: date, coverage_end: date) -> PitAuditReport:
        if coverage_start > coverage_end:
            raise ValueError("PIT audit coverage start must not be after coverage end")

        failures: list[str] = []
        manifests: list[str] = []
        coverage_evidence_digests: list[str] = []
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
                coverage_evidence_digests=coverage_evidence_digests,
            )

        bundle_set_hash = self._warehouse.bundle_set_hash(coverage_start, coverage_end)
        body = {
            "bundle_set_hash": bundle_set_hash,
            "coverage_end": coverage_end.isoformat(),
            "coverage_evidence_digests": sorted(coverage_evidence_digests),
            "coverage_start": coverage_start.isoformat(),
            "failures": sorted(failures),
            "manifests": sorted(manifests),
            "market_id": self._market_id,
            "universe_id": self._universe_id,
        }
        audit_hash = sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return PitAuditReport(
            report_id=audit_hash[:24],
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            market_id=self._market_id,
            universe_id=self._universe_id,
            bundle_set_hash=bundle_set_hash,
            checked_manifests=tuple(sorted(manifests)),
            coverage_evidence_digests=tuple(sorted(coverage_evidence_digests)),
            failures=tuple(sorted(failures)),
            audit_hash=audit_hash,
        )

    def _audit_snapshot(
        self,
        *,
        as_of_time: datetime,
        failures: list[str],
        manifests: list[str],
        coverage_evidence_digests: list[str],
    ) -> None:
        failure_date = as_of_time.date().isoformat()
        try:
            security_ids = self._security_ids_for(as_of_time)
        except Exception as error:
            failures.append(f"security_master:{failure_date}:{type(error).__name__}")
            return
        expected_scope = SnapshotScope(
            security_ids,
            DAILY_REQUIRED_KINDS,
            market_id=self._market_id,
            universe_id=self._universe_id,
        )
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
        try:
            coverage_evidence = self._warehouse.coverage_evidence(
                as_of_time=as_of_time,
                scope=expected_scope,
            )
        except Exception:
            failures.append(f"snapshot:{failure_date}:COVERAGE_EVIDENCE_UNAVAILABLE")
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
        evidence_digests = _verified_sparse_coverage_digests(
            coverage_evidence,
            as_of_time,
            security_ids,
        )
        if evidence_digests is None:
            failures.append(f"snapshot:{failure_date}:COVERAGE_EVIDENCE_MISSING")
            return
        manifests.append(snapshot.manifest_hash)
        coverage_evidence_digests.extend(evidence_digests)

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


def _verified_sparse_coverage_digests(
    evidence: tuple[DatasetCoverageEvidence, ...],
    as_of_time: datetime,
    security_ids: tuple[str, ...],
) -> tuple[str, ...] | None:
    expected_ids = set(security_ids)
    by_kind: dict[DataKind, DatasetCoverageEvidence] = {}
    for item in evidence:
        if item.kind not in COVERAGE_EVIDENCE_KINDS or item.kind in by_kind:
            return None
        by_kind[item.kind] = item
    for kind in COVERAGE_EVIDENCE_KINDS:
        item = by_kind.get(kind)
        if item is None or item.as_of_time != as_of_time:
            return None
        if (
            set(item.security_ids) != expected_ids
            or not _is_sha256(item.source_hash)
            or not _is_sha256(item.evidence_digest)
            or not hmac.compare_digest(item.evidence_digest, coverage_evidence_digest(item))
        ):
            return None
        covered = set(item.covered_security_ids)
        known_empty = set(item.known_empty_security_ids)
        if (
            not covered.issubset(expected_ids)
            or not known_empty.issubset(expected_ids)
            or covered.intersection(known_empty)
            or covered.union(known_empty) != expected_ids
        ):
            return None
        if item.kind not in OPTIONAL_ZERO_MEMBERSHIP_KINDS and known_empty:
            return None
    return tuple(sorted(item.evidence_digest for item in by_kind.values()))


def coverage_evidence_digest(evidence: DatasetCoverageEvidence) -> str:
    payload = {
        "as_of_time": evidence.as_of_time.isoformat(),
        "covered_security_ids": sorted(evidence.covered_security_ids),
        "kind": evidence.kind.value,
        "known_empty_security_ids": sorted(evidence.known_empty_security_ids),
        "security_ids": sorted(evidence.security_ids),
        "source_hash": evidence.source_hash,
        "version": 1,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in hexdigits for char in value)
