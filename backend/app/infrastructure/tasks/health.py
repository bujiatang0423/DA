from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from backend.app.infrastructure.tasks.db_models import WorkerLeaseRow


class WorkerLeaseStore:
    """Durably tracks a worker identity without allowing token replacement."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def acquire(self, worker_id: str, lease_token: str, now: datetime) -> bool:
        return self._touch(worker_id, lease_token, now)

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
