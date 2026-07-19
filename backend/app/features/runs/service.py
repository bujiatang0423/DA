from __future__ import annotations
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.contracts.runs import Page, RunDetail, RunKind, RunRef, RunLinks, RunStatus
from backend.app.features.runs.repository import RunRepository
from backend.app.infrastructure.persistence.models import RunArtifactRow, RunRow


class RunsService:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    @staticmethod
    def _ref(row: RunRow) -> RunRef:
        run_id = str(row.id)
        return RunRef(
            run_id=run_id,
            kind=RunKind(row.kind),
            status=RunStatus(row.status),
            submitted_at=row.submitted_at,
            links=RunLinks(
                self=f"/api/v1/runs/{run_id}",
                artifacts=f"/api/v1/runs/{run_id}/artifacts",
                result=RunsService.result_link(RunKind(row.kind), run_id),
            ),
        )

    @staticmethod
    def result_link(kind: RunKind, run_id: str) -> str | None:
        if kind is RunKind.CANDIDATE_RECOMMENDATION:
            return f"/api/v1/candidates/{run_id}"
        if kind is RunKind.HOLDING_ANALYSIS:
            return f"/api/v1/holding-analyses/{run_id}"
        if kind is RunKind.BACKTEST:
            return f"/api/v1/backtests/{run_id}"
        return None

    def submit(
        self,
        kind: RunKind,
        payload: dict[str, object],
        idempotency_key: str | None,
        submitted_at: datetime,
    ) -> RunRef:
        with self._factory.begin() as session:
            return self._ref(
                RunRepository(session).submit(kind, payload, idempotency_key, submitted_at)
            )

    def get(self, run_id: UUID | str) -> RunDetail:
        with self._factory() as session:
            row = session.get(RunRow, UUID(str(run_id)))
            if row is None:
                raise KeyError(str(run_id))
            return RunDetail(
                **self._ref(row).model_dump(),
                stage=row.stage,
                progress=row.progress,
                heartbeat_at=row.heartbeat_at,
                retry_count=row.retry_count,
                error_code=row.error_code,
            )

    def list(self, cursor: str | None = None, limit: int = 50) -> Page[RunDetail]:
        with self._factory() as session:
            stmt = (
                select(RunRow)
                .order_by(RunRow.submitted_at.desc(), RunRow.id.desc())
                .limit(limit + 1)
            )
            rows = list(session.scalars(stmt))
            next_cursor = str(rows.pop().id) if len(rows) > limit else None
            return Page(items=[self.get(r.id) for r in rows], next_cursor=next_cursor)

    def artifacts(self, run_id: UUID | str) -> list[dict[str, object]]:
        with self._factory() as session:
            if session.get(RunRow, UUID(str(run_id))) is None:
                raise KeyError(str(run_id))
            return [
                dict(kind=a.kind, path=a.relative_path, sha256=a.sha256, media_type=a.media_type)
                for a in session.scalars(
                    select(RunArtifactRow).where(RunArtifactRow.run_id == UUID(str(run_id)))
                )
            ]

    def claim_next(self, now: datetime, worker_id: str, lease_token: str) -> RunRow | None:
        with self._factory.begin() as session:
            return RunRepository(session).claim_next(now, worker_id, lease_token)

    def heartbeat(
        self,
        run_id: UUID,
        stage: str,
        progress: int,
        now: datetime,
        worker_id: str,
        lease_token: str,
    ) -> bool:
        with self._factory.begin() as session:
            return RunRepository(session).heartbeat(
                run_id, stage, progress, now, worker_id, lease_token
            )

    def transition(
        self,
        run_id: UUID,
        target: RunStatus,
        now: datetime,
        worker_id: str,
        lease_token: str,
        error_code: str | None = None,
    ) -> RunRow | None:
        with self._factory.begin() as session:
            return RunRepository(session).transition(
                run_id,
                target,
                now,
                worker_id,
                lease_token,
                error_code,
            )

    def requeue_stale(self, cutoff: datetime, now: datetime) -> tuple[UUID, ...]:
        with self._factory.begin() as session:
            return RunRepository(session).requeue_stale(cutoff, now)
