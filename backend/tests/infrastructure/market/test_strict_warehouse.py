from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.contracts.grades import DataGrade
from backend.app.core.market.pit_models import DataKind, SnapshotScope
from backend.app.infrastructure.market.build import build_strict_pit_warehouse
from backend.app.infrastructure.market.strict_backtest_data import CertifiedHistoricalDailyBars
from backend.app.infrastructure.market.strict_bundle import PitBundleManifest
from backend.app.infrastructure.market.strict_certificates import (
    SqlPitCertificateAuthority,
    bundle_set_hash_for,
)
from backend.app.infrastructure.market.strict_ingest import StrictPitIngestor
from backend.app.infrastructure.market.strict_reader import SqlStrictRecordReader
from backend.app.infrastructure.market.strict_warehouse import UnverifiedPitDataError
from backend.app.infrastructure.persistence.models import Base
from backend.app.infrastructure.persistence.strict_pit_rows import (
    DailyBarRawRow,
    PitAuditReportRow,
    PitCertificateRow,
    PolicyDocumentRow,
)


AS_OF = datetime(2020, 6, 1, 15, 30, tzinfo=UTC)
HASH = "a" * 64
SECRET = "test-pit-certificate-secret"
SUPPORTED_KINDS = (
    DataKind.SECURITY_MASTER,
    DataKind.SECURITY_STATUS,
    DataKind.TRADING_CALENDAR,
    DataKind.DAILY_BAR_RAW,
    DataKind.INDEX_DAILY_BAR,
    DataKind.CORPORATE_ACTION,
    DataKind.ADJUSTMENT_FACTOR,
    DataKind.INDUSTRY_MEMBERSHIP,
    DataKind.THEME_MEMBERSHIP,
    DataKind.FINANCIAL_DISCLOSURE,
    DataKind.FINANCIAL_FACT,
    DataKind.POLICY_DOCUMENT,
    DataKind.FEE_SCHEDULE,
)
STRICT_TABLES = (
    "pit_certificates, pit_audit_reports, pit_bundles, security_master_history, "
    "security_status_daily, trading_calendar, daily_bars_raw, index_daily_bars, "
    "market_breadth, "
    "corporate_actions, adjustment_factors, industry_membership_history, "
    "theme_membership_history, financial_disclosures, financial_facts, policy_documents, "
    "fee_schedules"
)


@pytest.fixture
def strict_session(postgres_engine: Engine) -> Session:
    Base.metadata.create_all(postgres_engine)
    with postgres_engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {STRICT_TABLES} CASCADE"))
    session = sessionmaker(bind=postgres_engine, expire_on_commit=False)()
    bundle = PitBundleManifest.load(Path(__file__).parents[2] / "fixtures" / "pit_bundle")
    StrictPitIngestor(session).ingest(bundle)
    session.commit()
    try:
        yield session
    finally:
        session.close()
        with postgres_engine.begin() as connection:
            connection.execute(text(f"TRUNCATE TABLE {STRICT_TABLES} CASCADE"))


def persist_audit_report(
    session: Session,
    *,
    report_id: str = "audit-1",
    passed: bool = True,
    bundle_hash: str | None = None,
    audit_hash: str = HASH,
) -> None:
    session.add(
        PitAuditReportRow(
            id=report_id,
            passed=passed,
            coverage_start=AS_OF.date(),
            coverage_end=AS_OF.date(),
            bundle_set_hash=bundle_hash or bundle_set_hash_for(session, AS_OF.date()),
            audit_hash=audit_hash,
            verified_at=AS_OF,
        )
    )
    session.commit()


@pytest.mark.postgres
def test_production_build_requires_approved_persisted_audit_report(
    strict_session: Session,
) -> None:
    warehouse = build_strict_pit_warehouse(session=strict_session, approval_secret=SECRET)

    with pytest.raises(UnverifiedPitDataError, match="approved certificate"):
        warehouse.snapshot(as_of_time=AS_OF, scope=SnapshotScope())

    persist_audit_report(strict_session)
    with pytest.raises(UnverifiedPitDataError, match="approved certificate"):
        warehouse.snapshot(as_of_time=AS_OF, scope=SnapshotScope())

    SqlPitCertificateAuthority(strict_session, SECRET).approve(
        "audit-1", as_of_time=AS_OF, scope=SnapshotScope()
    )
    snapshot = warehouse.snapshot(as_of_time=AS_OF, scope=SnapshotScope())

    assert snapshot.data_grade is DataGrade.PIT_VERIFIED


@pytest.mark.postgres
def test_strict_reader_selects_only_market_breadth_visible_at_the_snapshot(
    strict_session: Session,
) -> None:
    records, _, issues = SqlStrictRecordReader(strict_session).read(
        as_of_time=AS_OF,
        scope=SnapshotScope(required_kinds=(DataKind.MARKET_BREADTH,)),
    )

    assert issues == ()
    assert [(record.kind, record.payload["breadth"]) for record in records] == [
        (DataKind.MARKET_BREADTH, "0.620000")
    ]


@pytest.mark.postgres
def test_certificate_is_bound_to_the_approved_query_scope(
    strict_session: Session,
) -> None:
    persist_audit_report(strict_session)
    full_scope = SnapshotScope(("000001.SZ",), SUPPORTED_KINDS)
    SqlPitCertificateAuthority(strict_session, SECRET).approve(
        "audit-1", as_of_time=AS_OF, scope=full_scope
    )
    warehouse = build_strict_pit_warehouse(session=strict_session, approval_secret=SECRET)

    full = warehouse.snapshot(
        as_of_time=AS_OF,
        scope=full_scope,
    )
    assert full.data_grade is DataGrade.PIT_VERIFIED
    with pytest.raises(UnverifiedPitDataError, match="approved certificate"):
        warehouse.snapshot(
            as_of_time=AS_OF,
            scope=SnapshotScope(("000001.SZ",), (DataKind.DAILY_BAR_RAW,)),
        )


@pytest.mark.postgres
def test_certificate_cannot_be_replayed_outside_its_approved_date(
    strict_session: Session,
) -> None:
    persist_audit_report(strict_session)
    authority = SqlPitCertificateAuthority(strict_session, SECRET)
    authority.approve("audit-1", as_of_time=AS_OF, scope=SnapshotScope())
    later = AS_OF.replace(day=2).date()

    assert (
        authority.certificate_for(
            as_of_time=AS_OF.replace(day=2),
            scope=SnapshotScope(),
            bundle_set_hash=bundle_set_hash_for(strict_session, later),
            lineage_hash="a" * 64,
            selected_snapshot_hash="a" * 64,
        )
        is None
    )


@pytest.mark.postgres
def test_later_strict_row_invalidates_certified_snapshot_identity(
    strict_session: Session,
) -> None:
    persist_audit_report(strict_session)
    SqlPitCertificateAuthority(strict_session, SECRET).approve(
        "audit-1", as_of_time=AS_OF, scope=SnapshotScope()
    )
    strict_session.execute(
        update(DailyBarRawRow)
        .where(DailyBarRawRow.source_record_id == "dbr-1")
        .values(source_artifact_hash="b" * 64)
    )
    strict_session.commit()
    warehouse = build_strict_pit_warehouse(session=strict_session, approval_secret=SECRET)

    with pytest.raises(UnverifiedPitDataError, match="approved certificate"):
        warehouse.snapshot(as_of_time=AS_OF, scope=SnapshotScope())


@pytest.mark.postgres
def test_certified_execution_reader_rejects_a_bar_changed_after_its_snapshot_approval(
    strict_session: Session,
) -> None:
    execution_scope = SnapshotScope(("000001.SZ",), (DataKind.DAILY_BAR_RAW,))
    persist_audit_report(strict_session)
    authority = SqlPitCertificateAuthority(strict_session, SECRET)
    authority.approve("audit-1", as_of_time=AS_OF, scope=execution_scope)
    strict_session.execute(
        update(DailyBarRawRow)
        .where(DailyBarRawRow.source_record_id == "dbr-1")
        .values(source_artifact_hash="b" * 64)
    )
    strict_session.commit()
    warehouse = build_strict_pit_warehouse(session=strict_session, approval_secret=SECRET)

    with pytest.raises(UnverifiedPitDataError, match="approved certificate"):
        CertifiedHistoricalDailyBars(warehouse).bar_for(
            "000001.SZ",
            AS_OF.date(),
            as_of_time=AS_OF,
        )


@pytest.mark.postgres
def test_new_selected_record_with_existing_artifact_invalidates_certificate(
    strict_session: Session,
) -> None:
    persist_audit_report(strict_session)
    authority = SqlPitCertificateAuthority(strict_session, SECRET)
    authority.approve("audit-1", as_of_time=AS_OF, scope=SnapshotScope())
    existing = strict_session.scalar(
        select(PolicyDocumentRow).where(PolicyDocumentRow.source_record_id == "pd-1")
    )
    assert existing is not None
    strict_session.add(
        PolicyDocumentRow(
            id="pd-forged-same-artifact",
            source_record_id="pd-forged-same-artifact",
            published_at=AS_OF,
            first_observed_at=AS_OF,
            available_at=AS_OF,
            evidence_grade="A",
            official_parent_id="csrs",
            content_hash="f" * 64,
            source_artifact_hash=existing.source_artifact_hash,
        )
    )
    strict_session.commit()
    warehouse = build_strict_pit_warehouse(session=strict_session, approval_secret=SECRET)

    with pytest.raises(UnverifiedPitDataError, match="approved certificate"):
        warehouse.snapshot(as_of_time=AS_OF, scope=SnapshotScope())


@pytest.mark.postgres
def test_selected_snapshot_hash_is_hmac_bound_to_certificate(
    strict_session: Session,
) -> None:
    persist_audit_report(strict_session)
    authority = SqlPitCertificateAuthority(strict_session, SECRET)
    authority.approve("audit-1", as_of_time=AS_OF, scope=SnapshotScope())
    certificate = strict_session.get(PitCertificateRow, "audit-1")
    assert certificate is not None
    certificate.selected_snapshot_hash = "0" * 64
    strict_session.commit()

    assert (
        authority.certificate_for(
            as_of_time=AS_OF,
            scope=SnapshotScope(),
            bundle_set_hash=bundle_set_hash_for(strict_session, AS_OF.date()),
            lineage_hash=certificate.lineage_hash,
            selected_snapshot_hash=certificate.selected_snapshot_hash,
        )
        is None
    )


@pytest.mark.postgres
def test_rejects_forged_certificate_row_without_matching_verified_audit(
    strict_session: Session,
) -> None:
    persist_audit_report(strict_session)
    strict_session.add(
        PitCertificateRow(
            audit_report_id="audit-1",
            coverage_start=AS_OF.date(),
            coverage_end=AS_OF.date(),
            bundle_set_hash="b" * 64,
            audit_hash=HASH,
            approval_token="0" * 64,
            approved_at=AS_OF,
            certified_as_of=AS_OF,
            scope_hash="0" * 64,
            lineage_hash="0" * 64,
            selected_snapshot_hash="0" * 64,
        )
    )
    strict_session.commit()
    warehouse = build_strict_pit_warehouse(session=strict_session, approval_secret=SECRET)

    with pytest.raises(UnverifiedPitDataError, match="approved certificate"):
        warehouse.snapshot(as_of_time=AS_OF, scope=SnapshotScope())


@pytest.mark.postgres
def test_rejects_matching_certificate_row_inserted_outside_approval_flow(
    strict_session: Session,
) -> None:
    persist_audit_report(strict_session)
    strict_session.add(
        PitCertificateRow(
            audit_report_id="audit-1",
            coverage_start=AS_OF.date(),
            coverage_end=AS_OF.date(),
            bundle_set_hash=bundle_set_hash_for(strict_session, AS_OF.date()),
            audit_hash=HASH,
            approval_token="0" * 64,
            approved_at=AS_OF,
            certified_as_of=AS_OF,
            scope_hash="0" * 64,
            lineage_hash="0" * 64,
            selected_snapshot_hash="0" * 64,
        )
    )
    strict_session.commit()
    warehouse = build_strict_pit_warehouse(session=strict_session, approval_secret=SECRET)

    with pytest.raises(UnverifiedPitDataError, match="approved certificate"):
        warehouse.snapshot(as_of_time=AS_OF, scope=SnapshotScope())


@pytest.mark.postgres
def test_failed_or_bundle_mismatched_audit_cannot_be_approved(
    strict_session: Session,
) -> None:
    persist_audit_report(strict_session, passed=False)
    authority = SqlPitCertificateAuthority(strict_session, SECRET)

    with pytest.raises(ValueError, match="passed audit report"):
        authority.approve("audit-1", as_of_time=AS_OF, scope=SnapshotScope())

    strict_session.query(PitAuditReportRow).delete()
    strict_session.commit()
    persist_audit_report(strict_session, bundle_hash="b" * 64)

    with pytest.raises(ValueError, match="persisted bundle set"):
        authority.approve("audit-1", as_of_time=AS_OF, scope=SnapshotScope())


@pytest.mark.postgres
@pytest.mark.parametrize("unsupported", [DataKind.LLM_FACTOR, DataKind.REALTIME_QUOTE])
def test_production_build_fails_closed_for_unsupported_required_kind(
    strict_session: Session,
    unsupported: DataKind,
) -> None:
    persist_audit_report(strict_session)
    SqlPitCertificateAuthority(strict_session, SECRET).approve(
        "audit-1", as_of_time=AS_OF, scope=SnapshotScope()
    )
    warehouse = build_strict_pit_warehouse(session=strict_session, approval_secret=SECRET)

    with pytest.raises(UnverifiedPitDataError, match="required strict data"):
        warehouse.snapshot(
            as_of_time=AS_OF,
            scope=SnapshotScope(required_kinds=(DataKind.DAILY_BAR_RAW, unsupported)),
        )
