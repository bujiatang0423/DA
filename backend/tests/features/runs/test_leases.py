from datetime import UTC, datetime
from threading import Event, Thread
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from backend.app.contracts.runs import RunKind, RunStatus
from backend.app.features.runs.repository import RunRepository


@pytest.fixture
def run_sessions(postgres_engine: object) -> sessionmaker[Session]:
    with postgres_engine.begin() as connection:  # type: ignore[union-attr]
        connection.execute(text("TRUNCATE TABLE run_events, runs CASCADE"))
    return sessionmaker(bind=postgres_engine, expire_on_commit=False)  # type: ignore[arg-type]


@pytest.mark.postgres
def test_only_the_claiming_worker_can_update_a_run_heartbeat(
    run_sessions: sessionmaker[Session],
) -> None:
    now = datetime(2026, 7, 19, 9, 30, tzinfo=UTC)
    with run_sessions.begin() as session:
        RunRepository(session).submit(RunKind.BACKTEST, {}, None, now)
    with run_sessions.begin() as session:
        claimed = RunRepository(session).claim_next(now, "worker-a", "token-a")
    assert claimed is not None

    with run_sessions.begin() as session:
        updated = RunRepository(session).heartbeat(
            claimed.id, "running", 50, now, "worker-b", "token-b"
        )
    assert updated is False

    with run_sessions() as session:
        row = session.execute(
            text("SELECT claim_owner, claim_token, progress FROM runs WHERE id = :id"),
            {"id": claimed.id},
        ).one()
    assert row.claim_owner == "worker-a"
    assert row.claim_token == "token-a"
    assert row.progress == 0


@pytest.mark.postgres
def test_only_the_claiming_worker_can_complete_a_run(
    run_sessions: sessionmaker[Session],
) -> None:
    now = datetime(2026, 7, 19, 9, 30, tzinfo=UTC)
    with run_sessions.begin() as session:
        RunRepository(session).submit(RunKind.BACKTEST, {}, None, now)
    with run_sessions.begin() as session:
        claimed = RunRepository(session).claim_next(now, "worker-a", "token-a")
    assert claimed is not None

    with run_sessions.begin() as session:
        completed = RunRepository(session).transition(
            claimed.id, RunStatus.SUCCEEDED, now, "worker-b", "token-b"
        )
    assert completed is None

    with run_sessions() as session:
        status = session.execute(
            text("SELECT status FROM runs WHERE id = :id"), {"id": claimed.id}
        ).scalar_one()
    assert status == RunStatus.RUNNING.value


@pytest.mark.postgres
def test_claim_is_not_available_to_a_second_worker(
    run_sessions: sessionmaker[Session],
) -> None:
    now = datetime(2026, 7, 19, 9, 30, tzinfo=UTC)
    with run_sessions.begin() as session:
        RunRepository(session).submit(RunKind.BACKTEST, {}, None, now)
    with run_sessions.begin() as session:
        first = RunRepository(session).claim_next(now, "worker-a", "token-a")
    with run_sessions.begin() as session:
        second = RunRepository(session).claim_next(now, "worker-b", "token-b")

    assert first is not None
    assert second is None
    assert isinstance(first.id, UUID)


@pytest.mark.postgres
def test_stale_requeue_clears_claim_and_fences_the_old_worker(
    run_sessions: sessionmaker[Session],
) -> None:
    claimed_at = datetime(2026, 7, 19, 9, 30, tzinfo=UTC)
    recovered_at = datetime(2026, 7, 19, 9, 32, tzinfo=UTC)
    with run_sessions.begin() as session:
        RunRepository(session).submit(RunKind.BACKTEST, {}, None, claimed_at)
    with run_sessions.begin() as session:
        claimed = RunRepository(session).claim_next(claimed_at, "worker-a", "token-a")
    assert claimed is not None

    with run_sessions.begin() as session:
        requeued = RunRepository(session).requeue_stale(recovered_at, recovered_at)
    assert requeued == (claimed.id,)

    with run_sessions.begin() as session:
        progress_updated = RunRepository(session).heartbeat(
            claimed.id, "persisted", 100, recovered_at, "worker-a", "token-a"
        )
        completed = RunRepository(session).transition(
            claimed.id, RunStatus.SUCCEEDED, recovered_at, "worker-a", "token-a"
        )
    assert progress_updated is False
    assert completed is None

    with run_sessions() as session:
        row = session.execute(
            text("SELECT status, claim_owner, claim_token FROM runs WHERE id = :id"),
            {"id": claimed.id},
        ).one()
    assert row.status == RunStatus.QUEUED.value
    assert row.claim_owner is None
    assert row.claim_token is None


@pytest.mark.postgres
def test_concurrent_workers_cannot_claim_the_same_run(
    run_sessions: sessionmaker[Session],
) -> None:
    now = datetime(2026, 7, 19, 9, 30, tzinfo=UTC)
    with run_sessions.begin() as session:
        RunRepository(session).submit(RunKind.BACKTEST, {}, None, now)

    first_claimed = Event()
    second_finished = Event()
    claims: list[object | None] = []

    def claim_first() -> None:
        with run_sessions.begin() as session:
            claims.append(RunRepository(session).claim_next(now, "worker-a", "token-a"))
            first_claimed.set()
            assert second_finished.wait(timeout=2)

    def claim_second() -> None:
        assert first_claimed.wait(timeout=2)
        with run_sessions.begin() as session:
            claims.append(RunRepository(session).claim_next(now, "worker-b", "token-b"))
        second_finished.set()

    first = Thread(target=claim_first)
    second = Thread(target=claim_second)
    first.start()
    second.start()
    first.join(timeout=3)
    second.join(timeout=3)

    assert not first.is_alive()
    assert not second.is_alive()
    assert sum(claim is not None for claim in claims) == 1
