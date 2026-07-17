from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import APIRouter, Header

from backend.app.contracts.runs import RunKind, RunRef
from .models import BacktestRequest
from .walk_forward import WalkForwardPlan


def build_router(
    submit: Callable[[RunKind, dict[str, object], str | None, datetime], RunRef] | None = None,
) -> APIRouter:
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

    @router.post("", response_model=RunRef, status_code=202)
    def submit_backtest(
        request: BacktestRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> RunRef:
        if submit is None:
            raise RuntimeError("backtest submission is not configured")
        return submit(
            RunKind.BACKTEST,
            request.model_dump(mode="json"),
            idempotency_key,
            datetime.now(UTC),
        )

    return router
