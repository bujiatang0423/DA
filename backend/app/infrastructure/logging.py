from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from uuid import UUID


_REQUEST_LOGGER = logging.getLogger("da.request")
_REQUEST_EVENT_CODE = "HTTP_REQUEST_COMPLETED"
_REQUEST_HANDLER_NAME = "da.request.json"


def configure_request_logging() -> None:
    _REQUEST_LOGGER.setLevel(logging.INFO)
    _REQUEST_LOGGER.propagate = False
    if any(handler.name == _REQUEST_HANDLER_NAME for handler in _REQUEST_LOGGER.handlers):
        return
    handler = logging.StreamHandler()
    handler.name = _REQUEST_HANDLER_NAME
    handler.setFormatter(logging.Formatter("%(message)s"))
    _REQUEST_LOGGER.addHandler(handler)


def configure_asgi_logging() -> None:
    configure_request_logging()
    logging.getLogger("uvicorn.access").disabled = True


def normalize_request_id(value: str | None) -> str:
    if value is None:
        return ""
    try:
        return str(UUID(value))
    except ValueError:
        return ""


def safe_run_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return str(UUID(value))
    except ValueError:
        return None


def log_request_completed(
    *,
    request_id: str,
    method: str,
    path_template: str,
    status_code: int,
    run_id: object,
) -> None:
    event = {
        "timestamp": datetime.now(UTC).isoformat(),
        "level": "INFO",
        "request_id": request_id,
        "method": method,
        "path_template": path_template,
        "status_code": status_code,
        "run_id": safe_run_id(run_id),
        "event_code": _REQUEST_EVENT_CODE,
    }
    _REQUEST_LOGGER.info(json.dumps(event, separators=(",", ":"), sort_keys=True))
