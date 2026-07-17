from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import APIRouter, Header

from backend.app.contracts.runs import RunKind, RunRef
from .contracts import CandidateRecommendationResponse, CandidateSubmitRequest
from .repository import CandidateRepository


def build_router(
    submit: Callable[[RunKind, dict[str, object], str | None, datetime], RunRef] | None = None,
    repository: CandidateRepository | None = None,
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
            {"portfolio_id": request.portfolio_id, "as_of_time": request.as_of_time.isoformat()},
            idempotency_key,
            datetime.now(UTC),
        )

    @router.get("/latest", response_model=CandidateRecommendationResponse)
    def latest() -> CandidateRecommendationResponse:
        if repository is None:
            raise KeyError("candidate result repository")
        result = repository.latest()
        if result is None:
            raise KeyError("candidate result")
        return CandidateRecommendationResponse.from_domain(result)

    @router.get("/{run_id}", response_model=CandidateRecommendationResponse)
    def get_result(run_id: str) -> CandidateRecommendationResponse:
        if repository is None:
            raise KeyError("candidate result repository")
        result = repository.get(run_id)
        if result is None:
            raise KeyError(run_id)
        return CandidateRecommendationResponse.from_domain(result)

    return router
