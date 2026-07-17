from fastapi import APIRouter

from backend.app.contracts.holdings import HoldingAnalysisRequest, HoldingAnalysisResponse
from backend.app.core.portfolio.analysis import HoldingAnalysisService
from backend.app.contracts.runs import RunKind, RunRef
from .contracts import HoldingAnalysisResponse as V212HoldingAnalysisResponse
from .repository import HoldingResultRepository
from collections.abc import Callable
from datetime import UTC, datetime
from fastapi import Header


def build_router(
    service: HoldingAnalysisService,
    submit: Callable[[RunKind, dict[str, object], str | None, datetime], RunRef] | None = None,
    repository: HoldingResultRepository | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/holdings", tags=["holdings"])

    @router.post("/analysis", response_model=HoldingAnalysisResponse)
    def analyze(request: HoldingAnalysisRequest) -> HoldingAnalysisResponse:
        return service.analyze(request)

    @router.post("/analysis/submit", response_model=RunRef, status_code=202)
    def submit_analysis(
        request: HoldingAnalysisRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> RunRef:
        if submit is None:
            raise RuntimeError("holding analysis submission is not configured")
        return submit(
            RunKind.HOLDING_ANALYSIS,
            request.model_dump(mode="json"),
            idempotency_key,
            datetime.now(UTC),
        )

    @router.get("/analysis/{run_id}", response_model=V212HoldingAnalysisResponse)
    def result(run_id: str) -> V212HoldingAnalysisResponse:
        if repository is None:
            raise KeyError(run_id)
        value = repository.get(run_id)
        if value is None:
            raise KeyError(run_id)
        return V212HoldingAnalysisResponse.from_domain(value)

    return router
