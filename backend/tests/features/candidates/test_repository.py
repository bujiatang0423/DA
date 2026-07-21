from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from backend.app.contracts.grades import DataGrade, LlmGrade
from backend.app.features.candidates.models import (
    CandidateBucket,
    CandidateFactors,
    CandidateItem,
    CandidateRecommendationResult,
    CandidateState,
)
from backend.app.features.candidates.repository import SqlCandidateRepository


def candidate_result(run_id: str, as_of_time: datetime) -> CandidateRecommendationResult:
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
                factors=CandidateFactors(*(Decimal("1") for _ in range(7))),
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


@pytest.fixture
def candidate_sessions(postgres_engine: object) -> sessionmaker[Session]:
    with postgres_engine.begin() as connection:  # type: ignore[union-attr]
        connection.execute(text("TRUNCATE TABLE candidate_results"))
    return sessionmaker(bind=postgres_engine, expire_on_commit=False)  # type: ignore[arg-type]


@pytest.mark.postgres
def test_latest_uses_run_id_as_a_deterministic_tie_breaker(
    candidate_sessions: sessionmaker[Session],
) -> None:
    repository = SqlCandidateRepository(candidate_sessions)
    as_of_time = datetime(2026, 7, 20, 7, 0, tzinfo=UTC)
    repository.save(candidate_result("run-a", as_of_time))
    repository.save(candidate_result("run-b", as_of_time))

    latest = repository.latest()

    assert latest is not None
    assert latest.run_id == "run-b"
    assert latest.items[0].evidence_refs == ("pit:daily_bar_raw:" + "a" * 64,)
