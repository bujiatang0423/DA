import json
import logging
from uuid import UUID

from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app.bootstrap.application import create_app
from backend.app.bootstrap.feature_registry import FeatureModule


def test_request_log_uses_allowlisted_fields_and_omits_sensitive_input(
    caplog: object,
) -> None:
    router = APIRouter()

    @router.post("/explode")
    def explode() -> None:
        raise RuntimeError("provider raw text: DEEPSEEK_API_KEY=top-secret; note=private-position")

    client = TestClient(
        create_app((FeatureModule("test", router, ()),)),
        raise_server_exceptions=False,
    )
    caplog.set_level(logging.INFO, logger="da.request")

    response = client.post(
        "/api/v1/explode?email=person@example.test",
        content='{"position_note":"private-position","cost_price":123.45}',
        headers={
            "Authorization": "Bearer top-secret",
            "X-Request-ID": "person@example.test",
        },
    )

    assert response.status_code == 500
    assert response.json()["message"] == "internal server error"
    records = [record for record in caplog.records if record.name == "da.request"]
    assert len(records) == 1
    event = json.loads(records[0].getMessage())
    assert set(event) == {
        "timestamp",
        "level",
        "request_id",
        "method",
        "path_template",
        "status_code",
        "run_id",
        "event_code",
    }
    assert event["method"] == "POST"
    assert event["path_template"] == "/api/v1/explode"
    assert event["status_code"] == 500
    assert event["run_id"] is None
    assert event["event_code"] == "HTTP_REQUEST_COMPLETED"
    UUID(event["request_id"])

    serialized = json.dumps(event)
    for forbidden in (
        "person@example.test",
        "top-secret",
        "private-position",
        "cost_price",
        "DEEPSEEK_API_KEY",
        "position_note",
    ):
        assert forbidden not in serialized


def test_http_exception_detail_is_not_returned_or_logged(caplog: object) -> None:
    router = APIRouter()

    @router.get("/rejected")
    def rejected() -> None:
        raise HTTPException(
            status_code=400, detail="provider raw text: DEEPSEEK_API_KEY=top-secret"
        )

    client = TestClient(create_app((FeatureModule("test", router, ()),)))
    caplog.set_level(logging.INFO, logger="da.request")

    response = client.get("/api/v1/rejected")

    assert response.status_code == 400
    assert response.json()["message"] == "request failed"
    assert "top-secret" not in response.text
    assert "DEEPSEEK_API_KEY" not in "\n".join(record.getMessage() for record in caplog.records)
