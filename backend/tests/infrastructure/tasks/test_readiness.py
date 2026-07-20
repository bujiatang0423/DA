from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.bootstrap.application import create_app
from backend.app.infrastructure.tasks.health import LocalReadinessProbe, WorkerLeaseStore


@pytest.fixture
def readiness_sessions(postgres_engine: Engine) -> sessionmaker[Session]:
    with postgres_engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE worker_leases"))
    return sessionmaker(bind=postgres_engine, expire_on_commit=False)


def _client(probe: LocalReadinessProbe) -> TestClient:
    return TestClient(create_app((), ready_probe=probe.check))


@pytest.mark.postgres
def test_ready_reports_local_database_and_recent_durable_worker_lease(
    readiness_sessions: sessionmaker[Session],
) -> None:
    now = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)
    WorkerLeaseStore(readiness_sessions).acquire("worker-a", "token-a", now)

    response = _client(LocalReadinessProbe(readiness_sessions, 120, lambda: now)).get(
        "/api/v1/health/ready"
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "components": {"database": "ready", "worker": "ready"},
    }


@pytest.mark.postgres
def test_ready_fails_closed_when_no_durable_worker_lease_exists(
    readiness_sessions: sessionmaker[Session],
) -> None:
    now = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)

    response = _client(LocalReadinessProbe(readiness_sessions, 120, lambda: now)).get(
        "/api/v1/health/ready"
    )

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "components": {"database": "ready", "worker": "missing"},
    }


@pytest.mark.postgres
def test_ready_fails_closed_when_latest_durable_worker_lease_is_stale(
    readiness_sessions: sessionmaker[Session],
) -> None:
    now = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)
    WorkerLeaseStore(readiness_sessions).acquire(
        "worker-a", "token-a", now - timedelta(seconds=121)
    )

    response = _client(LocalReadinessProbe(readiness_sessions, 120, lambda: now)).get(
        "/api/v1/health/ready"
    )

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "components": {"database": "ready", "worker": "stale"},
    }


def test_ready_hides_local_database_connection_failures() -> None:
    unavailable_sessions = sessionmaker(
        bind=create_engine("postgresql+psycopg://da:da@127.0.0.1:1/da_test"),
        expire_on_commit=False,
    )
    probe = LocalReadinessProbe(
        unavailable_sessions,
        120,
        lambda: datetime(2026, 7, 20, 10, 0, tzinfo=UTC),
    )

    response = _client(probe).get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "components": {"database": "unavailable", "worker": "unknown"},
    }
    assert "connection" not in response.text.lower()


def test_ready_preserves_legacy_probe_injection_without_readiness_status() -> None:
    calls: list[None] = []

    response = TestClient(create_app((), ready_probe=lambda: calls.append(None))).get(
        "/api/v1/health/ready"
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "components": {"database": "ready", "worker": "ready"},
    }
    assert calls == [None]
