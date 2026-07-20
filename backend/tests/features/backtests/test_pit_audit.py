from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from backend.app.contracts.grades import DataGrade
from backend.app.core.market.pit_models import (
    DataKind,
    PointInTimeSnapshot,
    QualityIssue,
    QualitySeverity,
    SnapshotQuality,
    SnapshotScope,
    TemporalRecord,
)
from backend.app.core.market.snapshot import assemble_snapshot
from backend.app.features.backtests.pit_audit import DAILY_REQUIRED_KINDS, PitAuditRunner


AS_OF_DATE = date(2020, 6, 1)
AUDITED_SECURITY_IDS = ("000001.SZ",)


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
    warehouse = CandidateWarehouse(complete_records())
    runner = PitAuditRunner(warehouse, (AS_OF_DATE,), AUDITED_SECURITY_IDS)

    first = runner.run(coverage_start=AS_OF_DATE, coverage_end=AS_OF_DATE)
    second = runner.run(coverage_start=AS_OF_DATE, coverage_end=AS_OF_DATE)

    assert first.passed is True
    assert first == second
    assert len(first.checked_manifests) == len(DAILY_REQUIRED_KINDS)


@pytest.mark.parametrize("kind", DAILY_REQUIRED_KINDS)
def test_future_poison_cannot_change_a_historical_audit(kind: DataKind) -> None:
    baseline_records = complete_records()
    future_poison = record(kind, available_at=as_of_time() + timedelta(days=1))

    baseline = PitAuditRunner(
        CandidateWarehouse(baseline_records),
        (AS_OF_DATE,),
        AUDITED_SECURITY_IDS,
    ).run(
        coverage_start=AS_OF_DATE,
        coverage_end=AS_OF_DATE,
    )
    replay = PitAuditRunner(
        CandidateWarehouse(baseline_records + (future_poison,)),
        (AS_OF_DATE,),
        AUDITED_SECURITY_IDS,
    ).run(coverage_start=AS_OF_DATE, coverage_end=AS_OF_DATE)

    assert replay.passed is True
    assert replay.audit_hash == baseline.audit_hash
    assert replay.checked_manifests == baseline.checked_manifests


def test_audit_fails_closed_for_missing_dataset_or_future_record() -> None:
    records = tuple(item for item in complete_records() if item.kind is not DataKind.DAILY_BAR_RAW)
    report = PitAuditRunner(CandidateWarehouse(records), (AS_OF_DATE,), AUDITED_SECURITY_IDS).run(
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
        AUDITED_SECURITY_IDS,
    ).run(coverage_start=AS_OF_DATE, coverage_end=AS_OF_DATE)

    assert report.passed is False
    assert all(failure.endswith(":FUTURE_RECORD") for failure in report.failures)


@pytest.mark.parametrize(
    "returned_scope",
    (
        SnapshotScope(required_kinds=(DataKind.POLICY_DOCUMENT,)),
        SnapshotScope(("unexpected.SZ",), (DataKind.SECURITY_MASTER,)),
    ),
)
def test_audit_rejects_a_warehouse_that_does_not_honor_the_exact_request(
    returned_scope: SnapshotScope,
) -> None:
    class WrongScopeWarehouse(CandidateWarehouse):
        def candidate_snapshot(
            self,
            *,
            as_of_time: datetime,
            scope: SnapshotScope,
        ) -> PointInTimeSnapshot:
            snapshot = super().candidate_snapshot(as_of_time=as_of_time, scope=scope)
            return PointInTimeSnapshot(
                as_of_time=snapshot.as_of_time,
                scope=returned_scope,
                data_grade=snapshot.data_grade,
                market_inputs=snapshot.market_inputs,
                security_observations=snapshot.security_observations,
                quality=snapshot.quality,
                lineage=snapshot.lineage,
                manifest_hash=snapshot.manifest_hash,
            )

    report = PitAuditRunner(
        WrongScopeWarehouse(complete_records()),
        (AS_OF_DATE,),
        AUDITED_SECURITY_IDS,
    ).run(coverage_start=AS_OF_DATE, coverage_end=AS_OF_DATE)

    assert report.passed is False
    assert all(failure.endswith(":SCOPE_MISMATCH") for failure in report.failures)


def test_audit_rejects_an_empty_successful_snapshot() -> None:
    class EmptyWarehouse(CandidateWarehouse):
        def candidate_snapshot(
            self,
            *,
            as_of_time: datetime,
            scope: SnapshotScope,
        ) -> PointInTimeSnapshot:
            return PointInTimeSnapshot(
                as_of_time=as_of_time,
                scope=scope,
                data_grade=DataGrade.RESEARCH,
                market_inputs=(),
                security_observations=(),
                quality=SnapshotQuality(()),
                lineage=(),
                manifest_hash="empty-success",
            )

    report = PitAuditRunner(EmptyWarehouse(), (AS_OF_DATE,), AUDITED_SECURITY_IDS).run(
        coverage_start=AS_OF_DATE,
        coverage_end=AS_OF_DATE,
    )

    assert report.passed is False
    assert all(failure.endswith(":RECORDS_MISSING") for failure in report.failures)


def test_audit_rejects_a_warehouse_that_changes_the_requested_as_of_time() -> None:
    class WrongAsOfWarehouse(CandidateWarehouse):
        def candidate_snapshot(
            self,
            *,
            as_of_time: datetime,
            scope: SnapshotScope,
        ) -> PointInTimeSnapshot:
            snapshot = super().candidate_snapshot(as_of_time=as_of_time, scope=scope)
            return PointInTimeSnapshot(
                as_of_time=as_of_time - timedelta(seconds=1),
                scope=snapshot.scope,
                data_grade=snapshot.data_grade,
                market_inputs=snapshot.market_inputs,
                security_observations=snapshot.security_observations,
                quality=snapshot.quality,
                lineage=snapshot.lineage,
                manifest_hash=snapshot.manifest_hash,
            )

    report = PitAuditRunner(
        WrongAsOfWarehouse(complete_records()),
        (AS_OF_DATE,),
        AUDITED_SECURITY_IDS,
    ).run(coverage_start=AS_OF_DATE, coverage_end=AS_OF_DATE)

    assert report.passed is False
    assert all(failure.endswith(":AS_OF_MISMATCH") for failure in report.failures)


def test_audit_rejects_an_unexpected_kind_in_an_otherwise_successful_snapshot() -> None:
    class MixedKindWarehouse(CandidateWarehouse):
        def candidate_snapshot(
            self,
            *,
            as_of_time: datetime,
            scope: SnapshotScope,
        ) -> PointInTimeSnapshot:
            snapshot = super().candidate_snapshot(as_of_time=as_of_time, scope=scope)
            other_kind = next(
                kind for kind in DAILY_REQUIRED_KINDS if kind is not scope.required_kinds[0]
            )
            return PointInTimeSnapshot(
                as_of_time=snapshot.as_of_time,
                scope=snapshot.scope,
                data_grade=snapshot.data_grade,
                market_inputs=snapshot.market_inputs + (record(other_kind),),
                security_observations=snapshot.security_observations,
                quality=snapshot.quality,
                lineage=snapshot.lineage,
                manifest_hash=snapshot.manifest_hash,
            )

    report = PitAuditRunner(
        MixedKindWarehouse(complete_records()),
        (AS_OF_DATE,),
        AUDITED_SECURITY_IDS,
    ).run(coverage_start=AS_OF_DATE, coverage_end=AS_OF_DATE)

    assert report.passed is False
    assert all(failure.endswith(":UNEXPECTED_KIND") for failure in report.failures)


def test_audit_requires_each_security_for_security_scoped_datasets() -> None:
    records = tuple(
        record(kind, entity_id="000001.SZ")
        for kind in DAILY_REQUIRED_KINDS
        if kind not in {DataKind.TRADING_CALENDAR, DataKind.INDEX_DAILY_BAR}
    ) + tuple(
        record(kind, entity_id="MARKET:TEST")
        for kind in (DataKind.TRADING_CALENDAR, DataKind.INDEX_DAILY_BAR)
    )
    report = PitAuditRunner(
        CandidateWarehouse(records),
        (AS_OF_DATE,),
        security_ids=("000001.SZ", "000002.SZ"),
    ).run(coverage_start=AS_OF_DATE, coverage_end=AS_OF_DATE)

    assert report.passed is False
    assert report.failures == (
        "adjustment_factor:2020-06-01:ENTITY_COVERAGE_MISSING",
        "daily_bar_raw:2020-06-01:ENTITY_COVERAGE_MISSING",
        "industry_membership:2020-06-01:ENTITY_COVERAGE_MISSING",
        "security_master:2020-06-01:ENTITY_COVERAGE_MISSING",
        "security_status:2020-06-01:ENTITY_COVERAGE_MISSING",
        "theme_membership:2020-06-01:ENTITY_COVERAGE_MISSING",
    )


def test_audit_rejects_invalid_coverage() -> None:
    runner = PitAuditRunner(CandidateWarehouse(), (), AUDITED_SECURITY_IDS)

    with pytest.raises(ValueError, match="coverage start"):
        runner.run(coverage_start=AS_OF_DATE, coverage_end=AS_OF_DATE - timedelta(days=1))


def test_audit_requires_an_explicit_security_universe() -> None:
    with pytest.raises(ValueError, match="expected security universe"):
        PitAuditRunner(CandidateWarehouse(), (), ())


def record(
    kind: DataKind,
    *,
    available_at: datetime | None = None,
    entity_id: str = "MARKET:TEST",
) -> TemporalRecord:
    current = as_of_time()
    return TemporalRecord(
        record_id=f"{kind.value}-record",
        kind=kind,
        entity_id=entity_id,
        event_time=current,
        observed_at=current,
        available_at=available_at or current,
        source_artifact_hash="a" * 64,
        payload={"kind": kind.value},
    )


def as_of_time() -> datetime:
    return datetime(2020, 6, 1, 7, 30, tzinfo=UTC)


def complete_records() -> tuple[TemporalRecord, ...]:
    return tuple(
        record(
            kind,
            entity_id=(
                "MARKET:TEST"
                if kind in {DataKind.TRADING_CALENDAR, DataKind.INDEX_DAILY_BAR}
                else AUDITED_SECURITY_IDS[0]
            ),
        )
        for kind in DAILY_REQUIRED_KINDS
    )


def _missing_issue(kind: DataKind) -> QualityIssue:
    return QualityIssue(
        code="REQUIRED_DATASET_MISSING",
        severity=QualitySeverity.ERROR,
        dataset=kind.value,
        entity_id=None,
        detail="test fixture",
    )
