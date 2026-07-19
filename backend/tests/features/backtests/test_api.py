from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from backend.app.bootstrap.application import _MemoryRuns, create_app
from backend.app.features.backtests.module import build_backtests_feature
from backend.tests.features.backtests.test_repository import fixed_result as result_fixture


REQUEST_BODY: dict[str, object] = {
    "strategy_version": "v2.12",
    "start_date": "2023-01-02",
    "end_date": "2023-01-04",
    "initial_cash": "150000",
    "groups": ["A", "B"],
}


def test_submit_is_async_research_only_and_idempotent() -> None:
    runs = _MemoryRuns()
    client = TestClient(create_app((build_backtests_feature(runs.submit),)))
    headers = {"Idempotency-Key": "research-run-1"}

    first = client.post("/api/v1/backtests", json=REQUEST_BODY, headers=headers)
    second = client.post("/api/v1/backtests", json=REQUEST_BODY, headers=headers)

    assert first.status_code == 202
    assert first.headers["Location"] == f"/api/v1/backtests/{first.json()['run_id']}"
    assert first.json()["run_id"] == second.json()["run_id"]
    assert first.json()["status"] == "queued"
    assert first.json()["auto_trade_enabled"] is False


def test_result_retrieval_preserves_grades_gates_and_trade_cursor() -> None:
    from backend.app.features.backtests.repository import MemoryBacktestResultRepository

    result = result_fixture.__wrapped__()
    run_id = UUID("00000000-0000-0000-0000-000000000010")
    repository = MemoryBacktestResultRepository()
    repository.save_result(run_id, result, created_at=datetime(2026, 7, 19, tzinfo=UTC))
    client = TestClient(create_app((build_backtests_feature(_MemoryRuns().submit, repository),)))

    response = client.get(f"/api/v1/backtests/{run_id}?group=A&trade_limit=1")

    assert response.status_code == 200
    body = response.json()
    assert [(item["group"], item["data_grade"], item["llm_grade"]) for item in body["groups"]] == [
        ("A", "research", "not_used"),
        ("B", "research", "reconstructed"),
    ]
    assert body["metric_details"]["acceptance_gates"] == [
        {"name": "net_profit_factor", "passed": False}
    ]
    assert body["trades"]["next_cursor"] == "A-trade-2"
    assert body["rejected_attempts"]["items"][0]["reason_code"] == "LIMIT_UP_LOCKED"
