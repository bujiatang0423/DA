from backend.app.infrastructure.tasks.handlers import JobContext
from .contracts import HoldingAnalysisRequest
from .service import (
    HoldingAnalysisCommand,
    HoldingAnalysisInvariantError,
    HoldingMarketDataMissing,
    V212HoldingAnalysisService,
)


class HoldingAnalysisJobHandler:
    def __init__(self, service: V212HoldingAnalysisService) -> None:
        self._service = service

    def __call__(self, context: JobContext) -> None:
        request = HoldingAnalysisRequest.model_validate(context.payload)
        context.heartbeat("evaluating_holdings", 20)
        try:
            self._service.run(
                HoldingAnalysisCommand(
                    str(context.run_id),
                    request.portfolio_id,
                    request.as_of_time,
                    import_batch_id=request.import_batch_id,
                    import_manifest_sha256=request.import_manifest_sha256,
                )
            )
        except (HoldingAnalysisInvariantError, HoldingMarketDataMissing) as error:
            print(
                "holding_analysis_failed "
                f"exception_type={type(error).__name__} detail={error}",
                flush=True,
            )
            raise
        context.heartbeat("persisted", 100)
