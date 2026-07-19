from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import APIRouter, Header, Query, Response
from uuid import UUID

from backend.app.contracts.runs import RunKind, RunRef
from .models import BacktestRequest
from .models import StrategyGroup
from .repository import BacktestResultRepository
from .schemas import BacktestResultResponse
from .walk_forward import WalkForwardPlan


def build_router(
    submit: Callable[[RunKind, dict[str, object], str | None, datetime], RunRef] | None = None,
    repository: BacktestResultRepository | None = None,
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
        response: Response,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> RunRef:
        if submit is None:
            raise RuntimeError("backtest submission is not configured")
        run_ref = submit(
            RunKind.BACKTEST,
            request.model_dump(mode="json"),
            idempotency_key,
            datetime.now(UTC),
        )
        response.headers["Location"] = f"/api/v1/backtests/{run_ref.run_id}"
        return run_ref

    @router.get("/{run_id}", response_model=BacktestResultResponse)
    def result(
        run_id: UUID,
        group: StrategyGroup = StrategyGroup.A,
        curve_limit: int = Query(default=200, ge=1, le=1000),
        curve_cursor: str | None = None,
        trade_limit: int = Query(default=100, ge=1, le=500),
        trade_cursor: str | None = None,
        rejected_limit: int = Query(default=100, ge=1, le=500),
        rejected_cursor: str | None = None,
    ) -> BacktestResultResponse:
        if repository is None:
            raise KeyError(str(run_id))
        restored = repository.fetch_result(run_id)
        if restored is None:
            raise KeyError(str(run_id))
        group_result = next((item for item in restored.groups if item.group is group), None)
        if group_result is None:
            raise KeyError(group.value)
        summary = repository.fetch_summary(run_id)
        return BacktestResultResponse(
            run_id=summary.run_id,
            status=summary.status,
            strategy_version=summary.strategy_version,
            input_manifest_hash=summary.input_manifest_hash,
            created_at=summary.created_at,
            groups=summary.groups,
            group=group,
            metrics=group_result.metrics,
            metric_details=group_result.metric_details,
            warnings=group_result.warnings,
            equity_curve=repository.page_curve(
                run_id, group, limit=curve_limit, cursor=curve_cursor
            ),
            trades=repository.page_trades(run_id, group, limit=trade_limit, cursor=trade_cursor),
            rejected_attempts=repository.page_rejected_attempts(
                run_id, group, limit=rejected_limit, cursor=rejected_cursor
            ),
        )

    return router
