from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from backend.app.contracts.grades import DataGrade
from backend.app.core.market.pit_models import (
    DataKind,
    PointInTimeSnapshot,
    QualityIssue,
    QualitySeverity,
    SnapshotScope,
    TemporalRecord,
)
from backend.app.core.market.snapshot import assemble_snapshot
from backend.app.features.backtests.pit_audit import DAILY_REQUIRED_KINDS, PitAuditRunner


AS_OF_DATE = date(2020, 6, 1)


class CandidateWarehouse:
    def __init__(self, records: tuple[TemporalRecord, ...] = ()) -> None:
        self._records = records

    def candidate_snapshot(
        self,
        *,
        as_of_time: datetime,
        scope: SnapshotScope,
    ) -> PointInTimeSnapshot:
        selected = tuple(
            record
            for record in self._records
            if record.kind in scope.required_kinds and record.available_at <= as_of_time
        )
        issues = () if selected else (_missing_issue(scope.required_kinds[0]),)
        return assemble_snapshot(
            as_of_time=as_of_time,
            scope=scope,
            data_grade=DataGrade.RESEARCH,
            records=selected,
            lineage=(),
            quality_issues=issues,
        )

    def bundle_set_hash(self, coverage_start: date, coverage_end: date) -> str:
        assert (coverage_start, coverage_end) == (AS_OF_DATE, AS_OF_DATE)
        return "a" * 64


def test_audit_is_deterministic_and_accepts_complete_historical_candidate_data() -> None:
    warehouse = CandidateWarehouse(tuple(record(kind) for kind in DAILY_REQUIRED_KINDS))
    runner = PitAuditRunner(warehouse, (AS_OF_DATE,))

    first = runner.run(coverage_start=AS_OF_DATE, coverage_end=AS_OF_DATE)
    second = runner.run(coverage_start=AS_OF_DATE, coverage_end=AS_OF_DATE)

    assert first.passed is True
    assert first == second
    assert len(first.checked_manifests) == len(DAILY_REQUIRED_KINDS)


@pytest.mark.parametrize("kind", DAILY_REQUIRED_KINDS)
def test_future_poison_cannot_change_a_historical_audit(kind: DataKind) -> None:
    baseline_records = tuple(record(item) for item in DAILY_REQUIRED_KINDS)
    future_poison = record(kind, available_at=as_of_time() + timedelta(days=1))

    baseline = PitAuditRunner(CandidateWarehouse(baseline_records), (AS_OF_DATE,)).run(
        coverage_start=AS_OF_DATE,
        coverage_end=AS_OF_DATE,
    )
    replay = PitAuditRunner(
        CandidateWarehouse(baseline_records + (future_poison,)),
        (AS_OF_DATE,),
    ).run(coverage_start=AS_OF_DATE, coverage_end=AS_OF_DATE)

    assert replay.passed is True
    assert replay.audit_hash == baseline.audit_hash
    assert replay.checked_manifests == baseline.checked_manifests


def test_audit_fails_closed_for_missing_dataset_or_future_record() -> None:
    records = tuple(
        record(kind) for kind in DAILY_REQUIRED_KINDS if kind is not DataKind.DAILY_BAR_RAW
    )
    report = PitAuditRunner(CandidateWarehouse(records), (AS_OF_DATE,)).run(
        coverage_start=AS_OF_DATE,
        coverage_end=AS_OF_DATE,
    )

    assert report.passed is False
    assert report.failures == ("daily_bar_raw:2020-06-01",)


def test_audit_rejects_a_warehouse_that_returns_a_future_record() -> None:
    class UnsafeWarehouse(CandidateWarehouse):
        def candidate_snapshot(
            self,
            *,
            as_of_time: datetime,
            scope: SnapshotScope,
        ) -> PointInTimeSnapshot:
            snapshot = super().candidate_snapshot(as_of_time=as_of_time, scope=scope)
            future = record(scope.required_kinds[0], available_at=as_of_time + timedelta(seconds=1))
            return PointInTimeSnapshot(
                as_of_time=snapshot.as_of_time,
                scope=snapshot.scope,
                data_grade=snapshot.data_grade,
                market_inputs=snapshot.market_inputs + (future,),
                security_observations=snapshot.security_observations,
                quality=snapshot.quality,
                lineage=snapshot.lineage,
                manifest_hash=snapshot.manifest_hash,
            )

    report = PitAuditRunner(
        UnsafeWarehouse(tuple(record(kind) for kind in DAILY_REQUIRED_KINDS)),
        (AS_OF_DATE,),
    ).run(coverage_start=AS_OF_DATE, coverage_end=AS_OF_DATE)

    assert report.passed is False
    assert all(failure.endswith(":FUTURE_RECORD") for failure in report.failures)


def test_audit_rejects_invalid_coverage() -> None:
    runner = PitAuditRunner(CandidateWarehouse(), ())

    with pytest.raises(ValueError, match="coverage start"):
        runner.run(coverage_start=AS_OF_DATE, coverage_end=AS_OF_DATE - timedelta(days=1))


def record(kind: DataKind, *, available_at: datetime | None = None) -> TemporalRecord:
    current = as_of_time()
    return TemporalRecord(
        record_id=f"{kind.value}-record",
        kind=kind,
        entity_id="MARKET:TEST",
        event_time=current,
        observed_at=current,
        available_at=available_at or current,
        source_artifact_hash="a" * 64,
        payload={"kind": kind.value},
    )


def as_of_time() -> datetime:
    return datetime(2020, 6, 1, 7, 30, tzinfo=UTC)


def _missing_issue(kind: DataKind) -> QualityIssue:
    return QualityIssue(
        code="REQUIRED_DATASET_MISSING",
        severity=QualitySeverity.ERROR,
        dataset=kind.value,
        entity_id=None,
        detail="test fixture",
    )
