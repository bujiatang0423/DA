from backend.app.infrastructure.tasks.handlers import JobContext
from .contracts import CandidateSubmitRequest
from .service import CandidateRecommendationCommand, CandidateService


class CandidateJobHandler:
    def __init__(self, service: CandidateService) -> None:
        self._service = service

    def __call__(self, context: JobContext) -> None:
        request = CandidateSubmitRequest.model_validate(context.payload)
        context.heartbeat("evaluating_candidates", 20)
        self._service.run(
            CandidateRecommendationCommand(
                run_id=str(context.run_id),
                portfolio_id=request.portfolio_id,
                as_of_time=request.as_of_time,
            )
        )
        context.heartbeat("persisted", 100)
