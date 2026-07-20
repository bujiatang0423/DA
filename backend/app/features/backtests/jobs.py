from __future__ import annotations

from backend.app.features.backtests.models import BacktestRequest
from backend.app.features.backtests.service import BacktestService
from backend.app.infrastructure.tasks.handlers import JobContext


class BacktestJobHandler:
    def __init__(self, service: BacktestService) -> None:
        self._service = service

    def __call__(self, context: JobContext) -> None:
        request = BacktestRequest.model_validate(context.payload)
        context.heartbeat("running_backtest", 20)
        self._service.run(
            context.run_id,
            request,
            claim_owner=context.claim_owner,
            claim_token=context.claim_token,
        )
        context.heartbeat("persisted", 100)
