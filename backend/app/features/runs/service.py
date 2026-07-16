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
        return RunRef(run_id=run_id, kind=RunKind(row.kind), status=RunStatus(row.status),
                      submitted_at=row.submitted_at,
                      links=RunLinks(self=f"/api/v1/runs/{run_id}", artifacts=f"/api/v1/runs/{run_id}/artifacts"))

    def submit(self, kind: RunKind, payload: dict[str, object], idempotency_key: str | None,
               submitted_at: datetime) -> RunRef:
        with self._factory.begin() as session:
            return self._ref(RunRepository(session).submit(kind, payload, idempotency_key, submitted_at))

    def get(self, run_id: UUID | str) -> RunDetail:
        with self._factory() as session:
            row = session.get(RunRow, UUID(str(run_id)))
            if row is None:
                raise KeyError(str(run_id))
            return RunDetail(**self._ref(row).model_dump(), stage=row.stage, progress=row.progress,
                             heartbeat_at=row.heartbeat_at)

    def list(self, cursor: str | None = None, limit: int = 50) -> Page[RunDetail]:
        with self._factory() as session:
            stmt = select(RunRow).order_by(RunRow.submitted_at.desc(), RunRow.id.desc()).limit(limit + 1)
            rows = list(session.scalars(stmt))
            next_cursor = str(rows.pop().id) if len(rows) > limit else None
            return Page(items=[self.get(r.id) for r in rows], next_cursor=next_cursor)

    def artifacts(self, run_id: UUID | str) -> list[dict[str, object]]:
        with self._factory() as session:
            if session.get(RunRow, UUID(str(run_id))) is None:
                raise KeyError(str(run_id))
            return [dict(kind=a.kind, path=a.relative_path, sha256=a.sha256, media_type=a.media_type)
                    for a in session.scalars(select(RunArtifactRow).where(RunArtifactRow.run_id == UUID(str(run_id))))]
