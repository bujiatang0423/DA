from fastapi import APIRouter

from .models import BacktestRequest
from .walk_forward import WalkForwardPlan


def build_router() -> APIRouter:
    router = APIRouter(prefix="/backtests", tags=["backtests"])

    @router.post("/plan")
    def plan(request: BacktestRequest) -> dict[str, object]:
        value = WalkForwardPlan.rolling(request.start_date, request.end_date)
        return {
            "strategy_version": request.strategy_version,
            "holdout": {"start": value.holdout.start, "end": value.holdout.end},
            "windows": [window.__dict__ for window in value.windows],
            "groups": list(request.groups),
        }

    return router
