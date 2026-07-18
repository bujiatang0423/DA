from datetime import UTC, datetime

from backend.app.core.market.pit_models import (
    DataKind,
    LineageRef,
    SnapshotScope,
    TemporalRecord,
)
from backend.app.infrastructure.market.research_source import ResearchBatch
from backend.app.infrastructure.market.research_warehouse import ResearchPointInTimeWarehouse


AS_OF = datetime(2026, 7, 18, tzinfo=UTC)


class FailingSource:
    provider = "market_provider"

    def fetch(self, *, as_of_time: datetime, scope: SnapshotScope) -> ResearchBatch:
        raise RuntimeError("credential=secret provider response body")


class EmptySource:
    provider = "empty_provider"

    def fetch(self, *, as_of_time: datetime, scope: SnapshotScope) -> ResearchBatch:
        return ResearchBatch((), ())


class DailyBarSource:
    provider = "daily_bar_provider"

    def fetch(self, *, as_of_time: datetime, scope: SnapshotScope) -> ResearchBatch:
        record = TemporalRecord(
            "bar-1",
            DataKind.DAILY_BAR_RAW,
            "000001.SZ",
            as_of_time,
            as_of_time,
            as_of_time,
            "a" * 64,
            {"close": "10"},
        )
        return ResearchBatch((record,), (LineageRef("batch-1", self.provider, "a" * 64),))


def test_source_failure_becomes_sanitized_provider_quality_error() -> None:
    snapshot = ResearchPointInTimeWarehouse((FailingSource(),)).snapshot(
        as_of_time=AS_OF,
        scope=SnapshotScope(required_kinds=(DataKind.DAILY_BAR_RAW,)),
    )

    issue = next(issue for issue in snapshot.quality.issues if issue.code == "PROVIDER_UNAVAILABLE")

    assert snapshot.quality.has_errors
    assert issue.severity.value == "error"
    assert issue.dataset == "market_provider"
    assert "secret" not in issue.detail
    assert "provider response" not in issue.detail


def test_successful_source_records_and_lineage_are_preserved() -> None:
    snapshot = ResearchPointInTimeWarehouse((DailyBarSource(),)).snapshot(
        as_of_time=AS_OF,
        scope=SnapshotScope(("000001.SZ",), (DataKind.DAILY_BAR_RAW,)),
    )

    assert snapshot.quality.has_errors is False
    assert snapshot.security_observations[0].records[0].record_id == "bar-1"
    assert snapshot.lineage[0].provider == "daily_bar_provider"


def test_missing_required_dataset_remains_a_quality_error() -> None:
    snapshot = ResearchPointInTimeWarehouse((EmptySource(),)).snapshot(
        as_of_time=AS_OF,
        scope=SnapshotScope(required_kinds=(DataKind.DAILY_BAR_RAW,)),
    )

    assert snapshot.quality.has_errors
    assert "REQUIRED_DATASET_MISSING" in {issue.code for issue in snapshot.quality.issues}
