from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterator
from pathlib import Path
import csv

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.infrastructure.market.strict_bundle import PitBundleManifest
from backend.app.infrastructure.market.strict_ingest import StrictPitIngestor
from backend.app.infrastructure.persistence.strict_pit_rows import (
    AdjustmentFactorRow,
    CorporateActionRow,
    DailyBarRawRow,
    FeeScheduleRow,
    FinancialDisclosureRow,
    FinancialFactRow,
    IndexDailyBarRow,
    IndustryMembershipHistoryRow,
    PitBundleRow,
    PolicyDocumentRow,
    SecurityMasterHistoryRow,
    SecurityStatusDailyRow,
    ThemeMembershipHistoryRow,
    TradingCalendarRow,
)


STRICT_TABLES = (
    PitBundleRow.__table__,
    SecurityMasterHistoryRow.__table__,
    SecurityStatusDailyRow.__table__,
    TradingCalendarRow.__table__,
    DailyBarRawRow.__table__,
    IndexDailyBarRow.__table__,
    CorporateActionRow.__table__,
    AdjustmentFactorRow.__table__,
    IndustryMembershipHistoryRow.__table__,
    ThemeMembershipHistoryRow.__table__,
    FinancialDisclosureRow.__table__,
    FinancialFactRow.__table__,
    PolicyDocumentRow.__table__,
    FeeScheduleRow.__table__,
)


@pytest.fixture
def pit_bundle(tmp_path: Path) -> Path:
    source = Path(__file__).parents[1] / "fixtures" / "pit_bundle"
    destination = tmp_path / "pit_bundle"
    shutil.copytree(source, destination)
    return destination


@pytest.fixture
def strict_pit_session(postgres_engine: Engine) -> Iterator[Session]:
    inspector = inspect(postgres_engine)
    created_tables = [table for table in STRICT_TABLES if not inspector.has_table(table.name)]
    for table in STRICT_TABLES:
        table.create(postgres_engine, checkfirst=True)
    _truncate_strict_tables(postgres_engine)

    session = sessionmaker(bind=postgres_engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        _truncate_strict_tables(postgres_engine)
        for table in reversed(created_tables):
            table.drop(postgres_engine, checkfirst=True)


@pytest.mark.postgres
def test_ingest_is_idempotent_and_append_only(
    strict_pit_session: Session, pit_bundle: Path
) -> None:
    bundle = PitBundleManifest.load(pit_bundle)
    ingestor = StrictPitIngestor(strict_pit_session)

    assert ingestor.ingest(bundle) is True
    assert ingestor.ingest(bundle) is False
    strict_pit_session.commit()

    assert strict_pit_session.scalar(select(func.count()).select_from(PitBundleRow)) == 1
    assert (
        strict_pit_session.scalar(select(func.count()).select_from(DailyBarRawRow))
        == bundle.file("daily_bars_raw").row_count
    )


@pytest.mark.postgres
def test_invalid_decimal_rolls_back_entire_bundle(
    strict_pit_session: Session, pit_bundle: Path
) -> None:
    daily_bars = pit_bundle / "daily_bars_raw.csv"
    daily_bars.write_text(
        daily_bars.read_text(encoding="utf-8").replace(",10.5,", ",not-a-decimal,"),
        encoding="utf-8",
    )
    _update_checksum(pit_bundle, "daily_bars_raw")
    bundle = PitBundleManifest.load(pit_bundle)

    with pytest.raises(ValueError, match="daily_bars_raw.close"):
        StrictPitIngestor(strict_pit_session).ingest(bundle)
    strict_pit_session.rollback()

    assert strict_pit_session.scalar(select(func.count()).select_from(PitBundleRow)) == 0
    assert strict_pit_session.scalar(select(func.count()).select_from(DailyBarRawRow)) == 0


@pytest.mark.postgres
def test_new_source_versions_append_without_overwriting_history(
    strict_pit_session: Session, pit_bundle: Path
) -> None:
    first_bundle = PitBundleManifest.load(pit_bundle)
    versioned_bundle_path = _versioned_bundle(pit_bundle)
    second_bundle = PitBundleManifest.load(versioned_bundle_path)
    ingestor = StrictPitIngestor(strict_pit_session)

    assert ingestor.ingest(first_bundle) is True
    assert ingestor.ingest(second_bundle) is True
    strict_pit_session.commit()

    assert strict_pit_session.scalar(select(func.count()).select_from(PitBundleRow)) == 2
    assert (
        strict_pit_session.scalar(select(func.count()).select_from(DailyBarRawRow))
        == first_bundle.file("daily_bars_raw").row_count * 2
    )


def _update_checksum(bundle_root: Path, dataset: str) -> None:
    manifest_path = bundle_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        if entry["dataset"] == dataset:
            content = (bundle_root / entry["path"]).read_bytes()
            entry["sha256"] = hashlib.sha256(content).hexdigest()
            break
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def _truncate_strict_tables(engine: Engine) -> None:
    table_names = ", ".join(table.name for table in STRICT_TABLES)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {table_names} CASCADE"))


def _versioned_bundle(source: Path) -> Path:
    destination = source.parent / "pit_bundle_v2"
    shutil.copytree(source, destination)
    for csv_path in destination.glob("*.csv"):
        with csv_path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
            fields = tuple(rows[0])
        for row in rows:
            for field in ("record_id", "disclosure_id", "document_id"):
                if field in row:
                    row[field] = f"{row[field]}-v2"
            if "source_artifact_hash" in row:
                row["source_artifact_hash"] = f"{row['source_artifact_hash']}-v2"
        with csv_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        _update_checksum(destination, csv_path.stem)

    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["bundle_id"] = "strict-pit-fixture-v2"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return destination
