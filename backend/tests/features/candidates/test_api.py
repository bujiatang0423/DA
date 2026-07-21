from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from backend.app.bootstrap.application import create_app
from backend.app.bootstrap.feature_registry import FeatureModule
from backend.app.contracts.runs import RunKind, RunLinks, RunRef, RunStatus
from backend.app.features.candidates.router import build_router


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
        run_id = "00000000-0000-0000-0000-000000000009"
        return RunRef(
            run_id=run_id,
            kind=kind,
            status=RunStatus.QUEUED,
            submitted_at=submitted_at,
            links=RunLinks(self=f"/api/v1/runs/{run_id}"),
        )


def test_submission_sets_location_and_preserves_worker_payload() -> None:
    submitter = RecordingSubmitter()
    client = TestClient(create_app((FeatureModule("candidates", build_router(submitter), ()),)))

    response = client.post(
        "/api/v1/candidates",
        headers={"Idempotency-Key": "candidate-20260720"},
        json={
            "portfolio_id": "default",
            "as_of_time": "2026-07-20T15:00:00+08:00",
        },
    )

    assert response.status_code == 202
    assert response.headers["location"].endswith(response.json()["run_id"])
    kind, payload, key, submitted_at = submitter.calls[0]
    assert kind is RunKind.CANDIDATE_RECOMMENDATION
    assert payload == {
        "portfolio_id": "default",
        "as_of_time": "2026-07-20T15:00:00+08:00",
    }
    assert key == "candidate-20260720"
    assert submitted_at.tzinfo is UTC
