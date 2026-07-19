from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.portfolio.models import OpeningPosition
from backend.app.features.legacy_import.repository import SqlLegacyRepository
from backend.app.features.legacy_import.service import (
    ImportedBatch,
    ImportedHistoricalPosition,
    ImportedRawFile,
)
from backend.app.infrastructure.persistence.legacy_rows import (
    LegacyImportBatchRow,
    LegacyPositionSnapshotRow,
    LegacyRawFileRow,
    OpeningPositionRow,
)


LEGACY_TABLES = (
    OpeningPositionRow.__table__,
    LegacyPositionSnapshotRow.__table__,
    LegacyRawFileRow.__table__,
    LegacyImportBatchRow.__table__,
)


@pytest.mark.postgres
def test_result_query_returns_persisted_import_counts(postgres_engine: Engine) -> None:
    for table in reversed(LEGACY_TABLES):
        table.create(postgres_engine, checkfirst=True)
    with postgres_engine.begin() as connection:
        for table in LEGACY_TABLES:
            connection.execute(delete(table))
    session = sessionmaker(bind=postgres_engine, expire_on_commit=False)()
    now = datetime(2026, 7, 19, 9, 0, tzinfo=UTC)
    try:
        repository = SqlLegacyRepository(session)
        saved = repository.save(
            ImportedBatch(
                "batch", "source", "not-a-git-worktree", now, now, "main", "a" * 64, "{}"
            ),
            (ImportedRawFile("raw/current.csv", "b" * 64, "[]"),),
            (OpeningPosition("AAA", 10, Decimal("12.5"), now, "c" * 64),),
            (
                ImportedHistoricalPosition(
                    now,
                    "AAA",
                    8,
                    Decimal("11"),
                    None,
                    "b" * 64,
                    "{}",
                ),
            ),
        )
        session.commit()

        summary = repository.get_summary("batch")

        assert saved is True
        assert summary is not None
        assert summary.raw_file_count == 1
        assert summary.opening_position_count == 1
        assert summary.historical_snapshot_count == 1
    finally:
        session.close()
        with postgres_engine.begin() as connection:
            for table in LEGACY_TABLES:
                connection.execute(delete(table))
