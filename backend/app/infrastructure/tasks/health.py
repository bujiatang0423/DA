from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.infrastructure.tasks.db_models import WorkerLeaseRow

WORKER_LEASE_STALE_AFTER = timedelta(seconds=60)


@dataclass(frozen=True)
class ReadinessStatus:
    ready: bool
    database: str
    worker: str


class LocalReadinessProbe:
    """Fail closed unless local PostgreSQL and a recent durable worker lease are available."""

    def __init__(
        self,
        factory: sessionmaker[Session],
        worker_stale_after_seconds: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._factory = factory
        self._worker_stale_after = timedelta(seconds=worker_stale_after_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))

    def check(self) -> ReadinessStatus:
        try:
            with self._factory() as session:
                session.execute(text("SELECT 1"))
                heartbeat_at = session.scalar(
                    select(WorkerLeaseRow.heartbeat_at)
                    .order_by(WorkerLeaseRow.heartbeat_at.desc())
                    .limit(1)
                )
        except SQLAlchemyError:
            return ReadinessStatus(False, "unavailable", "unknown")

        if heartbeat_at is None:
            return ReadinessStatus(False, "ready", "missing")
        if heartbeat_at < self._clock() - self._worker_stale_after:
            return ReadinessStatus(False, "ready", "stale")
        return ReadinessStatus(True, "ready", "ready")


class WorkerLeaseStore:
    """Durably tracks a worker identity without allowing token replacement."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def acquire(self, worker_id: str, lease_token: str, now: datetime) -> bool:
        statement = insert(WorkerLeaseRow).values(
            worker_id=worker_id,
            lease_token=lease_token,
            heartbeat_at=now,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[WorkerLeaseRow.worker_id],
            set_={"lease_token": lease_token, "heartbeat_at": now},
            where=or_(
                WorkerLeaseRow.lease_token == lease_token,
                WorkerLeaseRow.heartbeat_at < now - WORKER_LEASE_STALE_AFTER,
            ),
        ).returning(WorkerLeaseRow.worker_id)
        with self._factory.begin() as session:
            return session.scalar(statement) is not None

    def heartbeat(self, worker_id: str, lease_token: str, now: datetime) -> bool:
        return self._touch(worker_id, lease_token, now)

    def _touch(self, worker_id: str, lease_token: str, now: datetime) -> bool:
        statement = insert(WorkerLeaseRow).values(
            worker_id=worker_id,
            lease_token=lease_token,
            heartbeat_at=now,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[WorkerLeaseRow.worker_id],
            set_={"heartbeat_at": now},
            where=WorkerLeaseRow.lease_token == lease_token,
        ).returning(WorkerLeaseRow.worker_id)
        with self._factory.begin() as session:
            return session.scalar(statement) is not None
