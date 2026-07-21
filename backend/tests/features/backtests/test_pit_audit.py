from __future__ import annotations

from dataclasses import replace
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
from backend.app.features.backtests.pit_audit import (
    COVERAGE_EVIDENCE_KINDS,
    DAILY_REQUIRED_KINDS,
    DatasetCoverageEvidence,
    PitAuditRunner,
    coverage_evidence_digest,
)


FIRST_DATE = date(2020, 6, 1)
SECOND_DATE = date(2020, 6, 2)


class DateUniverse:
    def __init__(self, values: dict[date, tuple[str, ...]]) -> None:
        self._values = values
        self.requested: list[datetime] = []

    def security_ids_for(self, as_of_time: datetime) -> tuple[str, ...]:
        self.requested.append(as_of_time)
        return self._values[as_of_time.date()]


class CandidateWarehouse:
    def __init__(
        self,
        records: tuple[TemporalRecord, ...] = (),
        *,
        zero_membership_kinds: frozenset[DataKind] = frozenset(),
    ) -> None:
        self._records = records
        self._zero_membership_kinds = zero_membership_kinds

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
        issues = () if selected else (_missing_issue("all"),)
        return assemble_snapshot(
            as_of_time=as_of_time,
            scope=scope,
            data_grade=DataGrade.RESEARCH,
            records=selected,
            lineage=(),
            quality_issues=issues,
        )

    def bundle_set_hash(self, coverage_start: date, coverage_end: date) -> str:
        return f"{coverage_start.isoformat()}:{coverage_end.isoformat()}".ljust(64, "a")

    def coverage_evidence(
        self,
        *,
        as_of_time: datetime,
        scope: SnapshotScope,
    ) -> tuple[DatasetCoverageEvidence, ...]:
        evidence: list[DatasetCoverageEvidence] = []
        for kind in COVERAGE_EVIDENCE_KINDS:
            item = DatasetCoverageEvidence(
                kind=kind,
                as_of_time=as_of_time,
                security_ids=scope.security_ids,
                covered_security_ids=(
                    () if kind in self._zero_membership_kinds else scope.security_ids
                ),
                known_empty_security_ids=(
                    scope.security_ids if kind in self._zero_membership_kinds else ()
                ),
                source_hash="a" * 64,
                evidence_digest="",
            )
            evidence.append(replace(item, evidence_digest=coverage_evidence_digest(item)))
        return tuple(evidence)


class UncoveredBundleWarehouse(CandidateWarehouse):
    def bundle_set_hash(self, coverage_start: date, coverage_end: date) -> str:
        raise ValueError("no persisted bundle covers this range")


def test_audit_fails_closed_when_canonical_bundle_coverage_is_unavailable() -> None:
    universe = DateUniverse({FIRST_DATE: ("000001.SZ",)})
    report = PitAuditRunner(
        UncoveredBundleWarehouse(complete_records(universe._values)),
        (FIRST_DATE,),
        universe,
        market_id="CN_A",
        universe_id="ALL_A",
    ).run(coverage_start=FIRST_DATE, coverage_end=FIRST_DATE)

    assert report.passed is False
    assert report.bundle_set_hash == ""
    assert report.failures == ("bundle_set:ValueError",)


def test_audit_binds_each_date_to_its_own_ipo_and_delisting_universe() -> None:
    universe = DateUniverse(
        {
            FIRST_DATE: ("OLD.SZ",),
            SECOND_DATE: ("IPO.SZ",),
        }
    )
    report = PitAuditRunner(
        CandidateWarehouse(complete_records(universe._values)),
        (FIRST_DATE, SECOND_DATE),
        universe,
        market_id="CN_A",
        universe_id="ALL_A",
    ).run(coverage_start=FIRST_DATE, coverage_end=SECOND_DATE)

    assert report.passed is True
    assert [item.date() for item in universe.requested] == [FIRST_DATE, SECOND_DATE]
    assert len(report.coverage_evidence_digests) == 2 * len(COVERAGE_EVIDENCE_KINDS)


def test_audit_binds_an_explicit_nondefault_market_and_universe() -> None:
    universe = DateUniverse({FIRST_DATE: ("SPY",)})
    report = PitAuditRunner(
        CandidateWarehouse(complete_records(universe._values)),
        (FIRST_DATE,),
        universe,
        market_id="US",
        universe_id="SP500",
    ).run(coverage_start=FIRST_DATE, coverage_end=FIRST_DATE)

    assert report.passed is True
    assert (report.market_id, report.universe_id) == ("US", "SP500")


def test_required_kinds_are_a_minimum_and_valid_auxiliary_records_are_allowed() -> None:
    universe = DateUniverse({FIRST_DATE: ("000001.SZ",)})
    auxiliary = record(DataKind.CORPORATE_ACTION, "MARKET:ACTION", FIRST_DATE)

    class AuxiliaryWarehouse(CandidateWarehouse):
        def candidate_snapshot(
            self,
            *,
            as_of_time: datetime,
            scope: SnapshotScope,
        ) -> PointInTimeSnapshot:
            snapshot = super().candidate_snapshot(as_of_time=as_of_time, scope=scope)
            return PointInTimeSnapshot(
                as_of_time=snapshot.as_of_time,
                scope=SnapshotScope(
                    scope.security_ids, (*scope.required_kinds, DataKind.CORPORATE_ACTION)
                ),
                data_grade=snapshot.data_grade,
                market_inputs=snapshot.market_inputs + (auxiliary,),
                security_observations=snapshot.security_observations,
                quality=snapshot.quality,
                lineage=snapshot.lineage,
                manifest_hash=snapshot.manifest_hash,
            )

    report = PitAuditRunner(
        AuxiliaryWarehouse(complete_records(universe._values)),
        (FIRST_DATE,),
        universe,
        market_id="CN_A",
        universe_id="ALL_A",
    ).run(coverage_start=FIRST_DATE, coverage_end=FIRST_DATE)

    assert report.passed is True


def test_optional_memberships_can_have_zero_members_with_explicit_coverage_evidence() -> None:
    universe = DateUniverse({FIRST_DATE: ("000001.SZ",)})
    optional_kinds = {
        DataKind.INDUSTRY_MEMBERSHIP,
        DataKind.THEME_MEMBERSHIP,
    }
    records = tuple(
        item for item in complete_records(universe._values) if item.kind not in optional_kinds
    )
    report = PitAuditRunner(
        CandidateWarehouse(records, zero_membership_kinds=frozenset(optional_kinds)),
        (FIRST_DATE,),
        universe,
        market_id="CN_A",
        universe_id="ALL_A",
    ).run(
        coverage_start=FIRST_DATE,
        coverage_end=FIRST_DATE,
    )

    assert report.passed is True


@pytest.mark.parametrize(
    "missing_kind",
    (DataKind.ADJUSTMENT_FACTOR, DataKind.INDUSTRY_MEMBERSHIP, DataKind.THEME_MEMBERSHIP),
)
def test_clean_quality_without_required_sparse_coverage_evidence_fails(
    missing_kind: DataKind,
) -> None:
    universe = DateUniverse({FIRST_DATE: ("000001.SZ",)})

    class MissingEvidenceWarehouse(CandidateWarehouse):
        def coverage_evidence(
            self,
            *,
            as_of_time: datetime,
            scope: SnapshotScope,
        ) -> tuple[DatasetCoverageEvidence, ...]:
            return tuple(
                item
                for item in super().coverage_evidence(as_of_time=as_of_time, scope=scope)
                if item.kind is not missing_kind
            )

    report = PitAuditRunner(
        MissingEvidenceWarehouse(
            tuple(
                item for item in complete_records(universe._values) if item.kind is not missing_kind
            )
        ),
        (FIRST_DATE,),
        universe,
        market_id="CN_A",
        universe_id="ALL_A",
    ).run(coverage_start=FIRST_DATE, coverage_end=FIRST_DATE)

    assert report.passed is False
    assert report.failures == ("snapshot:2020-06-01:COVERAGE_EVIDENCE_MISSING",)


def test_forged_coverage_content_cannot_reuse_the_original_digest() -> None:
    universe = DateUniverse({FIRST_DATE: ("000001.SZ",)})

    class ForgedEvidenceWarehouse(CandidateWarehouse):
        def coverage_evidence(
            self,
            *,
            as_of_time: datetime,
            scope: SnapshotScope,
        ) -> tuple[DatasetCoverageEvidence, ...]:
            evidence = super().coverage_evidence(as_of_time=as_of_time, scope=scope)
            adjustment = next(item for item in evidence if item.kind is DataKind.ADJUSTMENT_FACTOR)
            forged = replace(adjustment, covered_security_ids=())
            return tuple(forged if item is adjustment else item for item in evidence)

    report = PitAuditRunner(
        ForgedEvidenceWarehouse(complete_records(universe._values)),
        (FIRST_DATE,),
        universe,
        market_id="CN_A",
        universe_id="ALL_A",
    ).run(coverage_start=FIRST_DATE, coverage_end=FIRST_DATE)

    assert report.passed is False
    assert report.failures == ("snapshot:2020-06-01:COVERAGE_EVIDENCE_MISSING",)


def test_adjustment_factor_cannot_claim_the_entire_universe_is_known_empty() -> None:
    universe = DateUniverse({FIRST_DATE: ("000001.SZ",)})
    report = PitAuditRunner(
        CandidateWarehouse(
            complete_records(universe._values),
            zero_membership_kinds=frozenset({DataKind.ADJUSTMENT_FACTOR}),
        ),
        (FIRST_DATE,),
        universe,
        market_id="CN_A",
        universe_id="ALL_A",
    ).run(coverage_start=FIRST_DATE, coverage_end=FIRST_DATE)

    assert report.passed is False
    assert report.failures == ("snapshot:2020-06-01:COVERAGE_EVIDENCE_MISSING",)


def test_missing_bar_or_status_for_one_visible_security_fails_closed() -> None:
    universe = DateUniverse({FIRST_DATE: ("000001.SZ", "000002.SZ")})
    records = tuple(
        item
        for item in complete_records(universe._values)
        if not (item.kind is DataKind.DAILY_BAR_RAW and item.entity_id == "000002.SZ")
    )
    report = PitAuditRunner(
        CandidateWarehouse(records),
        (FIRST_DATE,),
        universe,
        market_id="CN_A",
        universe_id="ALL_A",
    ).run(
        coverage_start=FIRST_DATE,
        coverage_end=FIRST_DATE,
    )

    assert report.passed is False
    assert report.failures == ("daily_bar_raw:2020-06-01:ENTITY_COVERAGE_MISSING",)


@pytest.mark.parametrize("change", ("scope", "market", "as_of", "future"))
def test_audit_rejects_adversarial_snapshot_contract_drift(change: str) -> None:
    universe = DateUniverse({FIRST_DATE: ("000001.SZ",)})

    class UnsafeWarehouse(CandidateWarehouse):
        def candidate_snapshot(
            self,
            *,
            as_of_time: datetime,
            scope: SnapshotScope,
        ) -> PointInTimeSnapshot:
            snapshot = super().candidate_snapshot(as_of_time=as_of_time, scope=scope)
            returned_scope = snapshot.scope
            returned_as_of = snapshot.as_of_time
            market_inputs = snapshot.market_inputs
            if change == "scope":
                returned_scope = SnapshotScope(scope.security_ids, (DataKind.DAILY_BAR_RAW,))
            if change == "market":
                returned_scope = SnapshotScope(
                    scope.security_ids,
                    scope.required_kinds,
                    scope.history_start,
                    market_id="US",
                    universe_id="SP500",
                )
            if change == "as_of":
                returned_as_of = as_of_time - timedelta(seconds=1)
            if change == "future":
                market_inputs += (
                    record(
                        DataKind.CORPORATE_ACTION,
                        "MARKET:FUTURE",
                        FIRST_DATE,
                        available_at=as_of_time + timedelta(seconds=1),
                    ),
                )
            return PointInTimeSnapshot(
                as_of_time=returned_as_of,
                scope=returned_scope,
                data_grade=snapshot.data_grade,
                market_inputs=market_inputs,
                security_observations=snapshot.security_observations,
                quality=snapshot.quality,
                lineage=snapshot.lineage,
                manifest_hash=snapshot.manifest_hash,
            )

    report = PitAuditRunner(
        UnsafeWarehouse(complete_records(universe._values)),
        (FIRST_DATE,),
        universe,
        market_id="CN_A",
        universe_id="ALL_A",
    ).run(coverage_start=FIRST_DATE, coverage_end=FIRST_DATE)

    assert report.passed is False
    assert (
        report.failures == (
            f"snapshot:2020-06-01:{'SCOPE' if change == 'market' else change.upper()}_MISMATCH",
        )
        if change in {"scope", "market", "as_of"}
        else ("snapshot:2020-06-01:FUTURE_RECORD",)
    )


def test_empty_date_universe_fails_closed() -> None:
    universe = DateUniverse({FIRST_DATE: ()})
    report = PitAuditRunner(
        CandidateWarehouse(),
        (FIRST_DATE,),
        universe,
        market_id="CN_A",
        universe_id="ALL_A",
    ).run(
        coverage_start=FIRST_DATE,
        coverage_end=FIRST_DATE,
    )

    assert report.passed is False
    assert report.failures == ("security_master:2020-06-01:ValueError",)


def complete_records(
    universes: dict[date, tuple[str, ...]],
) -> tuple[TemporalRecord, ...]:
    records: list[TemporalRecord] = []
    for trading_date, security_ids in universes.items():
        for kind in DAILY_REQUIRED_KINDS:
            if kind in {
                DataKind.TRADING_CALENDAR,
                DataKind.INDEX_DAILY_BAR,
                DataKind.MARKET_BREADTH,
            }:
                records.append(record(kind, f"MARKET:{kind.value}", trading_date))
            else:
                records.extend(
                    record(kind, security_id, trading_date) for security_id in security_ids
                )
    return tuple(records)


def record(
    kind: DataKind,
    entity_id: str,
    trading_date: date,
    *,
    available_at: datetime | None = None,
) -> TemporalRecord:
    current = datetime.combine(trading_date, datetime.min.time(), UTC)
    return TemporalRecord(
        record_id=f"{kind.value}:{entity_id}:{trading_date.isoformat()}",
        kind=kind,
        entity_id=entity_id,
        event_time=current,
        observed_at=current,
        available_at=available_at or current,
        source_artifact_hash="a" * 64,
        payload={"kind": kind.value},
    )


def _missing_issue(dataset: str) -> QualityIssue:
    return QualityIssue(
        code="REQUIRED_DATASET_MISSING",
        severity=QualitySeverity.ERROR,
        dataset=dataset,
        entity_id=None,
        detail="test fixture",
    )
