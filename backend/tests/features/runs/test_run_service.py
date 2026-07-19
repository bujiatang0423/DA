from datetime import UTC, datetime
from uuid import uuid4

import pytest

from backend.app.contracts.runs import RunKind, RunStatus
from backend.app.features.runs.service import RunsService
from backend.app.infrastructure.persistence.models import RunRow


@pytest.mark.parametrize(
    ("kind", "result_path"),
    (
        (RunKind.CANDIDATE_RECOMMENDATION, "/api/v1/candidates/{run_id}"),
        (RunKind.HOLDING_ANALYSIS, "/api/v1/holding-analyses/{run_id}"),
        (RunKind.BACKTEST, None),
        (RunKind.LEGACY_IMPORT, None),
    ),
)
def test_run_reference_exposes_only_available_business_result_links(
    kind: RunKind,
    result_path: str | None,
) -> None:
    run_id = uuid4()
    row = RunRow(
        id=run_id,
        kind=kind.value,
        status=RunStatus.SUCCEEDED.value,
        request_payload={},
        submitted_at=datetime.now(UTC),
        progress=100,
        retry_count=0,
    )

    reference = RunsService._ref(row)

    assert reference.links.artifacts == f"/api/v1/runs/{run_id}/artifacts"
    expected = result_path.format(run_id=run_id) if result_path is not None else None
    assert reference.links.result == expected
