from __future__ import annotations

import signal
from datetime import UTC, datetime
from os import environ
from socket import gethostname

from sqlalchemy.orm import Session, sessionmaker

from backend.app.bootstrap.settings import Settings
from backend.app.bootstrap.backtest_worker import (
    BacktestWorkerConfigurationError,
    build_backtest_job_handler,
)
from backend.app.bootstrap.composition import build_components
from backend.app.bootstrap.composition import ApplicationComponents
from backend.app.contracts.runs import RunKind
from backend.app.features.candidates.jobs import CandidateJobHandler
from backend.app.features.holdings.jobs import HoldingAnalysisJobHandler
from backend.app.features.runs.service import RunsService
from backend.app.infrastructure.persistence.database import build_engine, build_session_factory
from backend.app.infrastructure.tasks.handlers import HandlerRegistry
from backend.app.infrastructure.tasks.health import WorkerLeaseStore
from backend.app.infrastructure.tasks.worker import build_worker, run


def register_worker_handlers(
    settings: Settings,
    sessions: sessionmaker[Session],
    components: ApplicationComponents,
    handlers: HandlerRegistry,
) -> None:
    """Register handlers whose production dependencies are safe to construct."""
    handlers.register(
        RunKind.CANDIDATE_RECOMMENDATION, CandidateJobHandler(components.candidate_service)
    )
    handlers.register(
        RunKind.HOLDING_ANALYSIS, HoldingAnalysisJobHandler(components.holding_service)
    )
    try:
        handlers.register(RunKind.BACKTEST, build_backtest_job_handler(settings, sessions))
    except BacktestWorkerConfigurationError:
        return


def main() -> None:
    settings = Settings()
    engine = build_engine(settings.database_url)
    sessions = build_session_factory(engine)
    runs = RunsService(sessions)
    components = build_components(settings, sessions)
    handlers = HandlerRegistry()
    register_worker_handlers(settings, sessions, components, handlers)
    worker = build_worker(
        runs,
        handlers,
        lambda: datetime.now(UTC),
        WorkerLeaseStore(sessions),
        environ.get("DA_WORKER_ID", gethostname()),
        settings.worker_stale_after_seconds,
    )
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
