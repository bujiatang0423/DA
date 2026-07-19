from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import delete
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from backend.app.contracts.runs import RunKind
from backend.app.core.market.strategy_inputs import StrategyInputBuilder
from backend.app.core.strategy.service import V212StrategyEngine
from backend.app.features.holdings.jobs import HoldingAnalysisJobHandler
from backend.app.features.holdings.repository import SqlHoldingAnalysisRepository
from backend.app.features.holdings.service import HoldingAnalysisService, HoldingMarketDataMissing
from backend.app.features.legacy_import.repository import SqlLegacyRepository
from backend.app.features.legacy_import.service import LegacyImportService
from backend.app.features.runs.service import RunsService
from backend.app.infrastructure.market.research_warehouse import ResearchPointInTimeWarehouse
from backend.app.infrastructure.persistence.legacy_rows import (
    LegacyImportBatchRow,
    LegacyPositionSnapshotRow,
    LegacyRawFileRow,
    OpeningPositionRow,
)
from backend.app.infrastructure.persistence.models import RunEventRow, RunRow
from backend.app.infrastructure.persistence.portfolio_reader import SqlPortfolioReader
from backend.app.infrastructure.persistence.portfolio_rows import (
    PortfolioLotProjectionRow,
    PortfolioSnapshotProjectionRow,
    PortfolioSnapshotRevisionRow,
    PortfolioVersionRow,
)
from backend.app.infrastructure.tasks.handlers import JobContext


TABLES = (
    LegacyImportBatchRow.__table__,
    LegacyRawFileRow.__table__,
    LegacyPositionSnapshotRow.__table__,
    OpeningPositionRow.__table__,
    PortfolioVersionRow.__table__,
    PortfolioSnapshotProjectionRow.__table__,
    PortfolioLotProjectionRow.__table__,
    PortfolioSnapshotRevisionRow.__table__,
    RunRow.__table__,
    RunEventRow.__table__,
)


def _source(root: Path) -> Path:
    holdings = root / "data" / "holdings"
    holdings.mkdir(parents=True)
    (holdings / "持仓.csv").write_text(
        "ts_code,quantity,cost_price\n000001.SZ,100,10.50\n",
        encoding="utf-8-sig",
    )
    return root


@pytest.mark.postgres
def test_imported_opening_position_can_only_be_manually_analyzed_and_fails_closed(
    postgres_engine: Engine,
    tmp_path: Path,
) -> None:
    for table in TABLES:
        table.create(postgres_engine, checkfirst=True)
    with postgres_engine.begin() as connection:
        for table in reversed(TABLES):
            connection.execute(delete(table))

    sessions = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    as_of_time = datetime(2026, 7, 19, 9, 0, tzinfo=UTC)
    imports_root = tmp_path / "imports"
    with sessions.begin() as session:
        imported = LegacyImportService(imports_root, SqlLegacyRepository(session)).import_source(
            source_root=_source(tmp_path / "source"),
            portfolio_id="main",
            effective_at=as_of_time,
        )

    reader = SqlPortfolioReader(sessions)
    opening = reader.snapshot(portfolio_id="main", as_of_time=as_of_time)
    assert opening.lots[0].batch_id == imported.batch_id
    assert opening.lots[0].average_cost == Decimal("10.500000")

    submitted = RunsService(sessions).submit(
        RunKind.HOLDING_ANALYSIS,
        {"portfolio_id": "main", "as_of_time": as_of_time.isoformat()},
        f"holding:main:{as_of_time.isoformat()}",
        as_of_time,
    )
    service = HoldingAnalysisService(
        ResearchPointInTimeWarehouse(()),
        reader,
        StrategyInputBuilder(),
        V212StrategyEngine(),
        SqlHoldingAnalysisRepository(sessions),
    )
    handler = HoldingAnalysisJobHandler(service)

    with pytest.raises(HoldingMarketDataMissing, match="REQUIRED_DATASET_MISSING"):
        handler(
            JobContext(
                run_id=UUID(submitted.run_id),
                payload={"portfolio_id": "main", "as_of_time": as_of_time.isoformat()},
                heartbeat=lambda _stage, _progress: None,
            )
        )
