from typing import Protocol
from backend.app.core.strategy.types import StrategyEvaluation, StrategyEvaluationRequest
class StrategyDecisionPort(Protocol):
    def evaluate(self, request: StrategyEvaluationRequest) -> StrategyEvaluation: ...
