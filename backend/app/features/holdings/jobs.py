from backend.app.infrastructure.tasks.handlers import JobContext
from .contracts import HoldingAnalysisRequest
from .service import HoldingAnalysisCommand, V212HoldingAnalysisService


class HoldingAnalysisJobHandler:
    def __init__(self, service: V212HoldingAnalysisService) -> None:
        self._service = service

    def __call__(self, context: JobContext) -> None:
        request = HoldingAnalysisRequest.model_validate(context.payload)
        context.heartbeat("evaluating_holdings", 20)
        self._service.run(
            HoldingAnalysisCommand(str(context.run_id), request.portfolio_id, request.as_of_time)
        )
        context.heartbeat("persisted", 100)
