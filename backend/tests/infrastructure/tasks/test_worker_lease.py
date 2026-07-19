from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from backend.app.infrastructure.tasks.health import WorkerLeaseStore


@pytest.fixture
def lease_sessions(postgres_engine: object) -> sessionmaker[Session]:
    with postgres_engine.begin() as connection:  # type: ignore[union-attr]
        connection.execute(text("TRUNCATE TABLE worker_leases"))
    return sessionmaker(bind=postgres_engine, expire_on_commit=False)  # type: ignore[arg-type]


@pytest.mark.postgres
def test_heartbeat_persists_only_for_the_lease_owner(
    lease_sessions: sessionmaker[Session],
) -> None:
    store = WorkerLeaseStore(lease_sessions)
    now = datetime(2026, 7, 19, 9, 30, tzinfo=UTC)

    assert store.acquire("worker-a", "token-a", now) is True
    assert store.heartbeat("worker-a", "token-a", now + timedelta(seconds=10)) is True
    assert store.heartbeat("worker-a", "token-b", now + timedelta(seconds=20)) is False

    with lease_sessions() as session:
        row = session.execute(text("SELECT lease_token, heartbeat_at FROM worker_leases")).one()
    assert row.lease_token == "token-a"
    assert row.heartbeat_at == now + timedelta(seconds=10)


@pytest.mark.postgres
def test_second_token_cannot_acquire_an_active_worker_lease(
    lease_sessions: sessionmaker[Session],
) -> None:
    store = WorkerLeaseStore(lease_sessions)
    now = datetime(2026, 7, 19, 9, 30, tzinfo=UTC)

    assert store.acquire("worker-a", "token-a", now) is True
    assert store.acquire("worker-a", "token-b", now + timedelta(seconds=1)) is False


@pytest.mark.postgres
def test_restart_with_the_same_worker_id_replaces_an_expired_lease(
    lease_sessions: sessionmaker[Session],
) -> None:
    store = WorkerLeaseStore(lease_sessions)
    now = datetime(2026, 7, 19, 9, 30, tzinfo=UTC)

    assert store.acquire("worker-a", "old-token", now) is True
    assert store.acquire("worker-a", "new-token", now + timedelta(seconds=30)) is False
    assert store.acquire("worker-a", "new-token", now + timedelta(seconds=61)) is True
    assert store.heartbeat("worker-a", "old-token", now + timedelta(seconds=62)) is False
    assert store.heartbeat("worker-a", "new-token", now + timedelta(seconds=62)) is True
