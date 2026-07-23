"""Local-only API and worker process for browser acceptance tests."""

from __future__ import annotations

from os import environ
from threading import Event, Thread

import uvicorn

from backend.app.bootstrap.e2e import (
    bootstrap_local_e2e_strict_pit,
    build_local_e2e_application,
    build_local_e2e_worker,
    require_local_e2e_mode,
)
from backend.app.bootstrap.settings import Settings
from backend.app.infrastructure.persistence.database import build_engine, build_session_factory
from backend.app.infrastructure.tasks.worker import run
from backend.app.infrastructure.market.portfolio_quote_scheduler import run_quote_scheduler


def main() -> None:
    require_local_e2e_mode(environ)
    settings = Settings()
    engine = build_engine(settings.database_url)
    sessions = build_session_factory(engine)
    bootstrap_local_e2e_strict_pit(settings, sessions)
    app = build_local_e2e_application(settings, sessions)
    worker = build_local_e2e_worker(settings, sessions)
    stopped = Event()
    def start_worker() -> None:
        Thread(
            target=run,
            kwargs={"worker": worker, "stop": stopped.is_set, "interval": 0.1},
            daemon=True,
        ).start()
        Thread(target=run_quote_scheduler, args=(sessions, stopped), daemon=True).start()

    def stop_worker() -> None:
        stopped.set()

    app.router.add_event_handler("startup", start_worker)
    app.router.add_event_handler("shutdown", stop_worker)
    uvicorn.run(app, host=settings.bind_host, port=settings.bind_port, access_log=False)


if __name__ == "__main__":
    main()
