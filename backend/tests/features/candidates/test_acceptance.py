from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from backend.app.bootstrap.application import create_app
from backend.app.bootstrap.feature_registry import FeatureModule
from backend.app.contracts.grades import DataGrade, LlmGrade
from backend.app.contracts.runs import RunKind, RunLinks, RunRef, RunStatus
from backend.app.features.candidates.models import (
    CandidateBucket,
    CandidateFactors,
    CandidateItem,
    CandidateRecommendationResult,
    CandidateState,
)
from backend.app.features.candidates.jobs import CandidateJobHandler
from backend.app.features.candidates.repository import SqlCandidateRepository
from backend.app.features.candidates.router import build_router
from backend.app.features.candidates.service import CandidateRecommendationCommand
from backend.app.infrastructure.tasks.handlers import JobContext


@dataclass
class RecordingSubmitter:
    calls: list[tuple[RunKind, dict[str, object], str | None, datetime]] = field(
        default_factory=list
    )

    def __call__(
        self,
        kind: RunKind,
        payload: dict[str, object],
        idempotency_key: str | None,
        submitted_at: datetime,
    ) -> RunRef:
        self.calls.append((kind, payload, idempotency_key, submitted_at))
        run_id = "candidate-run"
        return RunRef(
            run_id=run_id,
            kind=kind,
            status=RunStatus.QUEUED,
            submitted_at=submitted_at,
            links=RunLinks(self=f"/api/v1/runs/{run_id}"),
        )


@dataclass
class RecordingCandidateService:
    run_ids: list[str] = field(default_factory=list)

    def run(self, command: CandidateRecommendationCommand) -> object:
        self.run_ids.append(command.run_id)
        return object()


def _result(run_id: str, as_of_time: datetime) -> CandidateRecommendationResult:
    return CandidateRecommendationResult(
        run_id=run_id,
        as_of_time=as_of_time,
        strategy_version="v2.12",
        manifest_hash=f"manifest-{run_id}",
        data_grade=DataGrade.RESEARCH,
        llm_grade=LlmGrade.NOT_USED,
        market_state="neutral",
        market_confidence="normal",
        quality_codes=("LLM_EVIDENCE_MISSING",),
        items=(
            CandidateItem(
                security_id="000001.SZ",
                security_name="Ping An",
                bucket=CandidateBucket.WATCHLIST,
                state=CandidateState.SELECTED,
                strategy_book=None,
                factors=CandidateFactors(*([1] * 7)),
                planned_quantity=0,
                initial_stop=None,
                trigger_condition="trigger",
                invalidation_condition="invalidation",
                reason_codes=(),
                quality_codes=(),
                evidence_refs=("pit:daily_bar_raw:" + "a" * 64,),
            ),
        ),
    )


def test_submit_returns_result_location_and_manual_only_contract() -> None:
    submitter = RecordingSubmitter()
    client = TestClient(create_app((FeatureModule("candidates", build_router(submitter), ()),)))

    response = client.post(
        "/api/v1/candidates",
        headers={"Idempotency-Key": "candidate-20260720"},
        json={"portfolio_id": "default", "as_of_time": "2026-07-20T15:00:00+08:00"},
    )

    assert response.status_code == 202
    assert response.headers["location"] == "/api/v1/candidates/candidate-run"
    assert response.json()["auto_trade_enabled"] is False
    assert response.json()["human_confirm_required"] is True
    assert submitter.calls[0][1] == {
        "portfolio_id": "default",
        "as_of_time": "2026-07-20T15:00:00+08:00",
    }


def test_worker_accepts_api_payload_and_reports_durable_progress() -> None:
    service = RecordingCandidateService()
    heartbeats: list[tuple[str, int]] = []

    CandidateJobHandler(service)(  # type: ignore[arg-type]
        JobContext(
            run_id=UUID("00000000-0000-0000-0000-000000000009"),
            payload={
                "portfolio_id": "default",
                "as_of_time": "2026-07-20T15:00:00+08:00",
            },
            heartbeat=lambda stage, progress: heartbeats.append((stage, progress)),
        )
    )

    assert service.run_ids == ["00000000-0000-0000-0000-000000000009"]
    assert heartbeats == [("evaluating_candidates", 20), ("persisted", 100)]


@pytest.mark.postgres
def test_postgres_latest_breaks_same_time_ties_by_run_id(postgres_engine: Engine) -> None:
    with postgres_engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE candidate_results"))
    repository = SqlCandidateRepository(sessionmaker(bind=postgres_engine, expire_on_commit=False))
    as_of_time = datetime(2026, 7, 20, 7, 0, tzinfo=UTC)
    repository.save(_result("run-a", as_of_time))
    repository.save(_result("run-b", as_of_time))

    latest = repository.latest()

    assert latest is not None
    assert latest.run_id == "run-b"
