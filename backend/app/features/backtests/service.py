from __future__ import annotations

from typing import Protocol
from uuid import UUID

from backend.app.features.backtests.models import BacktestExperimentResult, BacktestRequest
from backend.app.features.backtests.ports import BacktestRepository
from backend.app.ports.artifacts import ArtifactRepository


class BacktestExperimentRunner(Protocol):
    def run(self, request: BacktestRequest) -> BacktestExperimentResult: ...


class BacktestService:
    """Runs one persisted research request and publishes its structured evidence."""

    def __init__(
        self,
        runner: BacktestExperimentRunner,
        repository: BacktestRepository,
        artifacts: ArtifactRepository,
    ) -> None:
        self._runner = runner
        self._repository = repository
        self._artifacts = artifacts

    def run(
        self,
        run_id: UUID,
        request: BacktestRequest,
        *,
        claim_owner: str | None = None,
        claim_token: str | None = None,
    ) -> BacktestExperimentResult:
        result = self._runner.run(request)
        self._repository.publish_result(
            run_id,
            result,
            self._artifacts,
            claim_owner=claim_owner,
            claim_token=claim_token,
        )
        return result
