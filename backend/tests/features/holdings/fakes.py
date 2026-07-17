from dataclasses import dataclass, field

from backend.app.features.holdings.models import HoldingAnalysisResult


@dataclass
class FakeHoldingAnalysisRepository:
    saved: list[HoldingAnalysisResult] = field(default_factory=list)

    def save(self, result: HoldingAnalysisResult) -> None:
        self.saved.append(result)

    def get(self, run_id: str) -> HoldingAnalysisResult | None:
        return next((result for result in self.saved if result.run_id == run_id), None)

    def latest(self, portfolio_id: str) -> HoldingAnalysisResult | None:
        matches = [result for result in self.saved if result.portfolio_id == portfolio_id]
        return max(matches, key=lambda result: (result.as_of_time, result.run_id), default=None)
