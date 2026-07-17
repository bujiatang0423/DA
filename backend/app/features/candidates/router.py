from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import APIRouter, Header

from backend.app.contracts.runs import RunKind, RunRef
from .contracts import CandidateSubmitRequest


def build_router(
    submit: Callable[[RunKind, dict[str, object], str | None, datetime], RunRef] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/candidates", tags=["candidates"])

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.post("", response_model=RunRef, status_code=202)
    def submit_candidate(
        request: CandidateSubmitRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> RunRef:
        if submit is None:
            raise RuntimeError("candidate submission is not configured")
        return submit(
            RunKind.CANDIDATE_RECOMMENDATION,
            {"as_of_time": request.as_of_time.isoformat()},
            idempotency_key,
            datetime.now(UTC),
        )

    return router
