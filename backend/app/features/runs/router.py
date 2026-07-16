from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Header, Response

from backend.app.contracts.runs import Page, RunDetail, RunKind, RunRef
from backend.app.features.runs.service import RunsService


def build_router(service: RunsService) -> APIRouter:
    router = APIRouter(prefix="/runs", tags=["runs"])

    @router.get("", response_model=Page[RunDetail])
    def list_runs(cursor: str | None = None, limit: int = 50) -> Page[RunDetail]:
        return service.list(cursor, min(limit, 100))

    @router.get("/{run_id}", response_model=RunDetail)
    def get_run(run_id: UUID) -> RunDetail:
        return service.get(run_id)

    @router.get("/{run_id}/artifacts")
    def artifacts(run_id: UUID) -> list[dict[str, object]]:
        return service.artifacts(run_id)

    @router.post("", response_model=RunRef, status_code=202)
    def submit_run(kind: RunKind, payload: dict[str, object], response: Response,
                   idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> RunRef:
        result = service.submit(kind, payload, idempotency_key, datetime.now(timezone.utc))
        response.headers["Location"] = result.links.self
        return result

    return router
