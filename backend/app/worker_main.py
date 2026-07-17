from __future__ import annotations

import signal
from datetime import UTC, datetime
from os import environ

from backend.app.bootstrap.settings import Settings
from backend.app.contracts.grades import DataGrade
from backend.app.contracts.runs import RunKind
from backend.app.core.market.pit_models import (
    QualityIssue,
    QualitySeverity,
    SnapshotScope,
    PointInTimeSnapshot,
)
from backend.app.core.market.snapshot import assemble_snapshot
from backend.app.core.market.strategy_inputs import StrategyInputBuilder
from backend.app.core.strategy.service import V212StrategyEngine
from backend.app.features.candidates.jobs import CandidateJobHandler
from backend.app.features.candidates.repository import SqlCandidateRepository
from backend.app.features.candidates.service import CandidateService
from backend.app.infrastructure.persistence.portfolio_reader import SqlPortfolioReader
from backend.app.features.runs.service import RunsService
from backend.app.infrastructure.persistence.database import build_engine, build_session_factory
from backend.app.infrastructure.tasks.handlers import HandlerRegistry
from backend.app.infrastructure.tasks.worker import build_worker, run


class UnavailableResearchWarehouse:
    """Fail-closed source used until a market/provider adapter is configured."""

    def snapshot(self, *, as_of_time: datetime, scope: SnapshotScope) -> PointInTimeSnapshot:
        missing = tuple(
            QualityIssue(
                "REQUIRED_DATASET_MISSING",
                QualitySeverity.ERROR,
                kind.value,
                None,
                "candidate provider is not configured",
            )
            for kind in scope.required_kinds
        )
        return assemble_snapshot(
            as_of_time=as_of_time,
            scope=scope,
            data_grade=DataGrade.RESEARCH,
            records=(),
            lineage=(),
            quality_issues=missing,
        )


def main() -> None:
    settings = Settings()
    engine = build_engine(settings.database_url)
    sessions = build_session_factory(engine)
    runs = RunsService(sessions)
    repository = SqlCandidateRepository(sessions)
    service = CandidateService(
        UnavailableResearchWarehouse(),
        SqlPortfolioReader(sessions),
        StrategyInputBuilder(),
        V212StrategyEngine(),
        repository,
    )
    handlers = HandlerRegistry()
    handlers.register(RunKind.CANDIDATE_RECOMMENDATION, CandidateJobHandler(service))
    worker = build_worker(runs, handlers, lambda: datetime.now(UTC))
    stopping = False

    def stop_handler(signum: int, frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    interval = float(environ.get("DA_WORKER_INTERVAL", "1"))
    run(worker, stop=lambda: stopping, interval=interval)


if __name__ == "__main__":
    main()
