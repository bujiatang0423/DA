from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.features.holdings.repository import (
    HoldingAnalysisConflict,
    HoldingResultRow,
    SqlHoldingAnalysisRepository,
)
from backend.tests.features.holdings.factories import holding_analysis_result


@pytest.fixture
def memory_sessions() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    HoldingResultRow.__table__.create(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_repository_round_trips_and_replays_idempotently(
    memory_sessions: sessionmaker[Session],
) -> None:
    repository = SqlHoldingAnalysisRepository(memory_sessions)
    result = holding_analysis_result()

    repository.save(result)
    repository.save(result)

    stored = repository.get(result.run_id)
    assert stored is not None
    assert tuple(item.security_id for item in stored.items) == ("000001.SZ", "600000.SH")
    assert replace(stored, items=result.items) == result


def test_repository_rejects_same_run_with_a_different_manifest(
    memory_sessions: sessionmaker[Session],
) -> None:
    repository = SqlHoldingAnalysisRepository(memory_sessions)
    result = holding_analysis_result()
    repository.save(result)

    with pytest.raises(HoldingAnalysisConflict, match=result.run_id):
        repository.save(replace(result, manifest_hash="different-manifest"))


def test_latest_is_scoped_to_portfolio_with_a_stable_tie_breaker(
    memory_sessions: sessionmaker[Session],
) -> None:
    repository = SqlHoldingAnalysisRepository(memory_sessions)
    as_of_time = datetime(2026, 7, 17, 7, 0, tzinfo=UTC)
    repository.save(holding_analysis_result("run-a", as_of_time=as_of_time))
    repository.save(holding_analysis_result("run-b", as_of_time=as_of_time))
    repository.save(holding_analysis_result("run-z", portfolio_id="other", as_of_time=as_of_time))

    latest = repository.latest("default")

    assert latest is not None
    assert latest.run_id == "run-b"


@pytest.mark.postgres
def test_repository_round_trips_on_postgresql(postgres_engine: Engine) -> None:
    HoldingResultRow.__table__.create(postgres_engine, checkfirst=True)
    sessions = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    repository = SqlHoldingAnalysisRepository(sessions)
    result = holding_analysis_result(
        "holding-postgres-roundtrip-20260717",
        portfolio_id="postgres-roundtrip",
    )

    repository.save(result)

    stored = repository.get(result.run_id)
    latest = repository.latest(result.portfolio_id)
    assert stored is not None
    assert latest is not None
    assert stored.run_id == result.run_id
    assert latest.run_id == result.run_id
    assert stored.manifest_hash == result.manifest_hash
