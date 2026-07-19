from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.contracts.grades import DataGrade
from backend.app.core.market.pit_models import DataKind, SnapshotScope
from backend.app.features.backtests.pit_certificate import PitCertificate
from backend.app.infrastructure.market.strict_bundle import PitBundleManifest
from backend.app.infrastructure.market.strict_ingest import StrictPitIngestor
from backend.app.infrastructure.market.strict_reader import SqlStrictRecordReader
from backend.app.infrastructure.market.strict_warehouse import (
    StrictPointInTimeWarehouse,
    UnverifiedPitDataError,
)
from backend.app.infrastructure.persistence.models import Base
from backend.app.infrastructure.persistence.strict_pit_rows import DailyBarRawRow


AS_OF = datetime(2020, 6, 1, 15, 30, tzinfo=UTC)
HASH = "a" * 64
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
    "pit_bundles, security_master_history, security_status_daily, trading_calendar, "
    "daily_bars_raw, index_daily_bars, corporate_actions, adjustment_factors, "
    "industry_membership_history, theme_membership_history, financial_disclosures, "
    "financial_facts, policy_documents, fee_schedules"
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


def certificate() -> PitCertificate:
    return PitCertificate("audit-1", AS_OF.date(), AS_OF.date(), HASH, HASH)


@pytest.mark.postgres
def test_sql_strict_warehouse_assembles_complete_verified_snapshot(
    strict_session: Session,
) -> None:
    scope = SnapshotScope(("000001.SZ",), SUPPORTED_KINDS)
    warehouse = StrictPointInTimeWarehouse(SqlStrictRecordReader(strict_session), certificate())

    snapshot = warehouse.snapshot(as_of_time=AS_OF, scope=scope)
    records = tuple(snapshot.market_inputs) + tuple(
        record for item in snapshot.security_observations for record in item.records
    )

    assert snapshot.data_grade is DataGrade.PIT_VERIFIED
    assert {record.kind for record in records} == set(SUPPORTED_KINDS)
    assert all(record.available_at <= AS_OF for record in records)
    assert (
        tuple(sorted(snapshot.lineage, key=lambda item: item.source_artifact_hash))
        == snapshot.lineage
    )
    assert snapshot.quality.issues == ()


@pytest.mark.postgres
def test_sql_strict_warehouse_excludes_future_versions_and_marks_missing_required_data(
    strict_session: Session,
) -> None:
    strict_session.add(
        DailyBarRawRow(
            id="future-bar",
            source_record_id="dbr-1",
            security_id="000001.SZ",
            trade_date=AS_OF.date(),
            open=99,
            high=99,
            low=99,
            close=99,
            volume=1,
            amount=99,
            available_at=datetime(2020, 6, 2, tzinfo=UTC),
            source_artifact_hash="b" * 64,
        )
    )
    strict_session.commit()
    scope = SnapshotScope(("000001.SZ",), (DataKind.DAILY_BAR_RAW, DataKind.LLM_FACTOR))
    warehouse = StrictPointInTimeWarehouse(SqlStrictRecordReader(strict_session), certificate())

    snapshot = warehouse.snapshot(as_of_time=AS_OF, scope=scope)

    assert all(
        record.record_id != "future-bar"
        for item in snapshot.security_observations
        for record in item.records
    )
    assert [(issue.code, issue.dataset) for issue in snapshot.quality.issues] == [
        ("REQUIRED_DATASET_MISSING", "llm_factor"),
    ]


def test_sql_strict_warehouse_requires_matching_certificate() -> None:
    warehouse = StrictPointInTimeWarehouse(reader=object(), certificate=None)  # type: ignore[arg-type]

    with pytest.raises(UnverifiedPitDataError, match="certificate required"):
        warehouse.snapshot(as_of_time=AS_OF, scope=SnapshotScope())
