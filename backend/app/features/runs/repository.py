from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.contracts.runs import RunKind, RunStatus
from backend.app.infrastructure.persistence.models import RunEventRow, RunRow


class InvalidRunTransition(RuntimeError):
    """Raised when a run state transition is not allowed."""


ALLOWED: dict[RunStatus, set[RunStatus]] = {
    RunStatus.QUEUED: {RunStatus.RUNNING, RunStatus.CANCELLED},
    RunStatus.RUNNING: {
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.QUEUED,
    },
    RunStatus.SUCCEEDED: set(),
    RunStatus.FAILED: set(),
    RunStatus.CANCELLED: set(),
}


class RunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def submit(
        self, kind: RunKind, payload: dict[str, object], key: str | None, now: datetime
    ) -> RunRow:
        if key:
            existing = self._session.scalar(
                select(RunRow).where(RunRow.kind == kind.value, RunRow.idempotency_key == key)
            )
            if existing:
                return existing
        row = RunRow(
            kind=kind.value,
            status=RunStatus.QUEUED.value,
            request_payload=payload,
            idempotency_key=key,
            submitted_at=now,
            progress=0,
            retry_count=0,
        )
        nested = self._session.begin_nested()
        try:
            self._session.add(row)
            self._session.flush()
            nested.commit()
        except IntegrityError:
            nested.rollback()
            if key is None:
                raise
            existing = self._session.scalar(
                select(RunRow).where(RunRow.kind == kind.value, RunRow.idempotency_key == key)
            )
            if existing is None:
                raise
            return existing
        self._event(row.id, "submitted", now)
        return row

    def claim_next(self, now: datetime) -> RunRow | None:
        row = self._session.scalar(
            select(RunRow)
            .where(RunRow.status == RunStatus.QUEUED.value)
            .order_by(RunRow.submitted_at, RunRow.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if row is None:
            return None
        row.status = RunStatus.RUNNING.value
        row.started_at = row.started_at or now
        row.heartbeat_at = now
        self._event(row.id, "claimed", now)
        self._session.flush()
        return row

    def transition(self, run_id: UUID, target: RunStatus, now: datetime) -> RunRow:
        row = self._session.get(RunRow, run_id, with_for_update=True)
        if row is None:
            raise KeyError(str(run_id))
        current = RunStatus(row.status)
        if target not in ALLOWED[current]:
            raise InvalidRunTransition(f"{current.value} -> {target.value}")
        row.status = target.value
        if target in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}:
            row.finished_at = now
        self._event(run_id, target.value, now)
        self._session.flush()
        return row

    def heartbeat(self, run_id: UUID, stage: str, progress: int, now: datetime) -> None:
        self._session.execute(
            update(RunRow)
            .where(RunRow.id == run_id, RunRow.status == RunStatus.RUNNING.value)
            .values(heartbeat_at=now, stage=stage, progress=progress)
        )

    def requeue_stale(self, cutoff: datetime, now: datetime) -> tuple[UUID, ...]:
        result = self._session.execute(
            update(RunRow)
            .where(RunRow.status == RunStatus.RUNNING.value, RunRow.heartbeat_at < cutoff)
            .values(
                status=RunStatus.QUEUED.value,
                retry_count=RunRow.retry_count + 1,
                stage=None,
                progress=0,
            )
            .returning(RunRow.id)
        )
        ids = tuple(result.scalars())
        for run_id in ids:
            self._event(run_id, "requeued_after_stale_heartbeat", now)
        return ids

    def _event(self, run_id: UUID, event_type: str, now: datetime) -> None:
        self._session.add(
            RunEventRow(run_id=run_id, occurred_at=now, event_type=event_type, payload={})
        )
