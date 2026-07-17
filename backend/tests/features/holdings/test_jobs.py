from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from backend.app.features.holdings.contracts import HoldingAnalysisRequest
from backend.app.features.holdings.jobs import HoldingAnalysisJobHandler
from backend.app.infrastructure.tasks.handlers import JobContext
from backend.tests.features.holdings.test_api import RecordingAnalysisService


def test_request_rejects_client_owned_strategy_and_llm_fields() -> None:
    with pytest.raises(ValidationError):
        HoldingAnalysisRequest.model_validate(
            {
                "portfolio_id": "default",
                "as_of_time": "2026-07-17T15:00:00+08:00",
                "strategy_version": "v9.99",
                "llm_grade": "forward_observed",
            }
        )


def test_worker_reports_durable_progress() -> None:
    service = RecordingAnalysisService()
    heartbeats: list[tuple[str, int]] = []
    handler = HoldingAnalysisJobHandler(service)

    handler(
        JobContext(
            run_id=UUID("00000000-0000-0000-0000-000000000008"),
            payload={
                "portfolio_id": "default",
                "as_of_time": datetime(2026, 7, 17, 7, 0, tzinfo=UTC).isoformat(),
            },
            heartbeat=lambda stage, progress: heartbeats.append((stage, progress)),
        )
    )

    assert service.run_ids == ["00000000-0000-0000-0000-000000000008"]
    assert heartbeats == [("evaluating_holdings", 20), ("persisted", 100)]
