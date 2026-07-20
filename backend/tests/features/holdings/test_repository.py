from dataclasses import replace
from datetime import UTC, datetime
from threading import Barrier, Lock, Thread
from uuid import uuid4

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy import create_engine
from sqlalchemy.orm import ORMExecuteState, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.features.holdings.repository import (
    HoldingAnalysisConflict,
    HoldingAnalysisItemRow,
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
    HoldingAnalysisItemRow.__table__.create(engine)
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


def test_repository_projects_each_item_once_in_security_id_order(
    memory_sessions: sessionmaker[Session],
) -> None:
    repository = SqlHoldingAnalysisRepository(memory_sessions)
    result = holding_analysis_result("holding-normalized-items")

    repository.save(result)
    repository.save(result)

    with memory_sessions() as session:
        rows = session.query(HoldingAnalysisItemRow).filter_by(run_id=result.run_id).all()

    assert [(row.item_index, row.security_id) for row in rows] == [
        (0, "000001.SZ"),
        (1, "600000.SH"),
    ]
    assert rows[0].average_cost == "10.20"
    assert rows[0].reason_codes == ["ELIGIBLE"]
    assert rows[1].evidence_refs == ["market-close:600000.SH:2026-07-17"]


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


def test_at_is_scoped_to_the_exact_portfolio_decision_time(
    memory_sessions: sessionmaker[Session],
) -> None:
    repository = SqlHoldingAnalysisRepository(memory_sessions)
    first_time = datetime(2026, 7, 17, 7, 0, tzinfo=UTC)
    later_time = datetime(2026, 7, 19, 7, 0, tzinfo=UTC)
    repository.save(holding_analysis_result("run-first", as_of_time=first_time))
    repository.save(holding_analysis_result("run-later", as_of_time=later_time))

    exact = repository.at("default", first_time)
    missing = repository.at("default", datetime(2026, 7, 18, 7, 0, tzinfo=UTC))

    assert exact is not None
    assert exact.run_id == "run-first"
    assert missing is None


@pytest.mark.postgres
def test_repository_round_trips_on_postgresql(postgres_engine: Engine) -> None:
    HoldingResultRow.__table__.create(postgres_engine, checkfirst=True)
    HoldingAnalysisItemRow.__table__.create(postgres_engine, checkfirst=True)
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
    assert stored.items[0].evidence_refs == ("market-close:000001.SZ:2026-07-17",)

    with sessions() as session:
        item_rows = session.query(HoldingAnalysisItemRow).filter_by(run_id=result.run_id).all()
    assert [(row.item_index, row.security_id) for row in item_rows] == [
        (0, "000001.SZ"),
        (1, "600000.SH"),
    ]


@pytest.mark.postgres
def test_repository_persists_parent_before_items_in_a_fresh_postgresql_schema(
    postgres_engine: Engine,
) -> None:
    schema_name = f"holding_items_{uuid4().hex}"
    with postgres_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
    schema_engine = postgres_engine.execution_options(schema_translate_map={None: schema_name})
    try:
        HoldingResultRow.__table__.create(schema_engine)
        HoldingAnalysisItemRow.__table__.create(schema_engine)
        repository = SqlHoldingAnalysisRepository(
            sessionmaker(bind=schema_engine, expire_on_commit=False)
        )
        result = holding_analysis_result("holding-fresh-schema")

        repository.save(result)

        stored = repository.get(result.run_id)
        assert stored is not None
        assert stored.items == tuple(sorted(result.items, key=lambda item: item.security_id))
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))


@pytest.mark.postgres
def test_concurrent_initial_same_run_saves_are_idempotent_on_postgresql(
    postgres_engine: Engine,
) -> None:
    HoldingResultRow.__table__.create(postgres_engine, checkfirst=True)
    HoldingAnalysisItemRow.__table__.create(postgres_engine, checkfirst=True)
    sessions = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    repository = SqlHoldingAnalysisRepository(sessions)
    result = holding_analysis_result(f"holding-concurrent-{uuid4().hex}")
    barrier = Barrier(2)
    lock = Lock()
    lookup_count = 0
    errors: list[Exception] = []

    def synchronize_initial_lookup(orm_execute_state: ORMExecuteState) -> None:
        nonlocal lookup_count
        statement = str(orm_execute_state.statement)
        if "holding_analysis_results" not in statement:
            return
        with lock:
            if lookup_count >= 2:
                return
            lookup_count += 1
        barrier.wait(timeout=5)

    event.listen(Session, "do_orm_execute", synchronize_initial_lookup)
    try:

        def save() -> None:
            try:
                repository.save(result)
            except Exception as exc:  # The assertion below reports an unexpected database failure.
                errors.append(exc)

        first = Thread(target=save)
        second = Thread(target=save)
        first.start()
        second.start()
        first.join()
        second.join()
    finally:
        event.remove(Session, "do_orm_execute", synchronize_initial_lookup)

    assert errors == []
    stored = repository.get(result.run_id)
    assert stored is not None
    assert replace(stored, items=result.items) == result
