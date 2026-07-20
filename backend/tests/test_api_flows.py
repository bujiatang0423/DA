from datetime import UTC, datetime

from fastapi.testclient import TestClient

from backend.app.bootstrap.application import _MemoryRuns, create_app
from backend.app.contracts.runs import RunStatus
from backend.app.features.backtests.module import build_backtests_feature
from backend.app.features.candidates.module import build_candidate_feature
from backend.app.features.runs.module import build_runs_feature


def _client() -> TestClient:
    runs = _MemoryRuns()
    return TestClient(
        create_app(
            (
                build_runs_feature(runs),
                build_candidate_feature(runs.submit),
                build_backtests_feature(runs.submit),
            )
        )
    )


def test_candidate_submission_is_idempotent() -> None:
    client = _client()
    payload = {"as_of_time": datetime(2026, 7, 17, 9, 30, tzinfo=UTC).isoformat()}
    first = client.post("/api/v1/candidates", json=payload, headers={"Idempotency-Key": "k1"})
    second = client.post("/api/v1/candidates", json=payload, headers={"Idempotency-Key": "k1"})
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["run_id"] == second.json()["run_id"]
    assert first.json()["links"]["result"] == f"/api/v1/candidates/{first.json()['run_id']}"


def test_backtest_plan_rejects_reversed_dates() -> None:
    client = _client()
    response = client.post(
        "/api/v1/backtests/plan",
        json={
            "strategy_version": "v2.12",
            "start_date": "2026-07-18",
            "end_date": "2026-07-17",
            "initial_cash": "1000000",
            "groups": ["A"],
        },
    )
    assert response.status_code == 422


def test_memory_run_retry_clears_safe_error_details() -> None:
    runs = _MemoryRuns()
    reference = runs.submit(
        kind="backtest",
        payload={},
        idempotency_key=None,
        submitted_at=datetime(2026, 7, 20, 10, 0, tzinfo=UTC),
    )
    runs._rows[reference.run_id] = runs._rows[reference.run_id].model_copy(
        update={
            "status": RunStatus.FAILED,
            "error_code": "JOB_EXECUTION_FAILED",
            "error_message": "任务执行失败，请稍后重试。",
        }
    )

    retried = runs.retry(reference.run_id, datetime(2026, 7, 20, 10, 1, tzinfo=UTC))

    assert retried.error_code is None
    assert retried.error_message is None
