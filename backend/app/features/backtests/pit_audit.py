from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from hashlib import sha256
import json
from typing import Protocol
from zoneinfo import ZoneInfo

from backend.app.core.market.pit_models import DataKind, PointInTimeSnapshot, SnapshotScope


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
    ) -> None:
        self._warehouse = warehouse
        self._trading_dates = tuple(sorted(set(trading_dates)))

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
                scope=SnapshotScope(required_kinds=(kind,)),
            )
        except Exception as error:
            failures.append(f"{failure_prefix}:{type(error).__name__}")
            return
        if snapshot.as_of_time != as_of_time:
            failures.append(f"{failure_prefix}:AS_OF_MISMATCH")
            return
        if snapshot.quality.has_errors:
            failures.append(failure_prefix)
            return
        records = snapshot.market_inputs + tuple(
            record
            for observation in snapshot.security_observations
            for record in observation.records
        )
        if any(
            record.available_at > as_of_time or record.event_time > as_of_time for record in records
        ):
            failures.append(f"{failure_prefix}:FUTURE_RECORD")
            return
        manifests.append(snapshot.manifest_hash)
