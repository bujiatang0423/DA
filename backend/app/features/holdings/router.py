from fastapi import APIRouter

from backend.app.contracts.holdings import HoldingAnalysisRequest, HoldingAnalysisResponse
from backend.app.core.portfolio.analysis import HoldingAnalysisService


def build_router(service: HoldingAnalysisService) -> APIRouter:
    router = APIRouter(prefix="/holdings", tags=["holdings"])

    @router.post("/analysis", response_model=HoldingAnalysisResponse)
    def analyze(request: HoldingAnalysisRequest) -> HoldingAnalysisResponse:
        return service.analyze(request)

    return router
