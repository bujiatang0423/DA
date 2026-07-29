from datetime import datetime, timedelta, UTC

import pytest

from backend.app.contracts.grades import DataGrade
from backend.app.core.market.pit_models import DataKind, SnapshotScope, TemporalRecord
from backend.app.core.market.snapshot import FutureDataError, assemble_snapshot


UTC = UTC


def record(
    rid: str, entity: str, event: datetime, available: datetime | None = None
) -> TemporalRecord:
    return TemporalRecord(
        rid,
        DataKind.DAILY_BAR_RAW,
        entity,
        event,
        event,
        available or event,
        "hash-" + rid,
        {"close": 1},
    )


def test_snapshot_requires_timezone_aware_as_of_and_records() -> None:
    with pytest.raises(ValueError):
        assemble_snapshot(
            as_of_time=datetime(2026, 1, 1),
            scope=SnapshotScope(),
            data_grade=DataGrade.RESEARCH,
            records=(),
            lineage=(),
            quality_issues=(),
        )
    naive = record("n", "AAA", datetime(2025, 1, 1, tzinfo=UTC))
    object.__setattr__(naive, "available_at", datetime(2025, 1, 1))
    with pytest.raises(ValueError):
        assemble_snapshot(
            as_of_time=datetime(2026, 1, 1, tzinfo=UTC),
            scope=SnapshotScope(),
            data_grade=DataGrade.RESEARCH,
            records=(naive,),
            lineage=(),
            quality_issues=(),
        )


def test_snapshot_rejects_future_event_or_availability() -> None:
    as_of = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(FutureDataError):
        assemble_snapshot(
            as_of_time=as_of,
            scope=SnapshotScope(),
            data_grade=DataGrade.RESEARCH,
            records=(record("f", "AAA", as_of + timedelta(seconds=1)),),
            lineage=(),
            quality_issues=(),
        )


def test_snapshot_filters_scope_and_history_but_keeps_market_records() -> None:
    as_of = datetime(2026, 1, 10, tzinfo=UTC)
    rows = (
        record("a", "AAA", datetime(2026, 1, 5, tzinfo=UTC)),
        record("b", "BBB", datetime(2026, 1, 5, tzinfo=UTC)),
        record("m", "MARKET:INDEX", datetime(2026, 1, 5, tzinfo=UTC)),
    )
    snap = assemble_snapshot(
        as_of_time=as_of,
        scope=SnapshotScope(("AAA",), history_start=datetime(2026, 1, 3, tzinfo=UTC)),
        data_grade=DataGrade.PIT_VERIFIED,
        records=rows,
        lineage=(),
        quality_issues=(),
    )
    assert [x.security_id for x in snap.security_observations] == ["AAA"]
    assert len(snap.market_inputs) == 1


def test_snapshot_keeps_reference_data_that_predates_requested_price_history() -> None:
    as_of = datetime(2026, 1, 10, tzinfo=UTC)
    master = TemporalRecord(
        "master",
        DataKind.SECURITY_MASTER,
        "AAA",
        datetime(2020, 1, 1, tzinfo=UTC),
        datetime(2020, 1, 1, tzinfo=UTC),
        datetime(2020, 1, 1, tzinfo=UTC),
        "hash-master",
        {"name": "AAA"},
    )

    snapshot = assemble_snapshot(
        as_of_time=as_of,
        scope=SnapshotScope(("AAA",), history_start=datetime(2026, 1, 3, tzinfo=UTC)),
        data_grade=DataGrade.PIT_VERIFIED,
        records=(master,),
        lineage=(),
        quality_issues=(),
    )

    assert snapshot.security_observations[0].records == (master,)


def test_holding_analysis_scope_requires_only_inputs_consumed_by_holding_strategy() -> None:
    scope = SnapshotScope.holding_analysis(("000001.SZ",))

    assert scope.required_kinds == (
        DataKind.SECURITY_MASTER,
        DataKind.DAILY_BAR_RAW,
        DataKind.INDEX_DAILY_BAR,
        DataKind.MARKET_BREADTH,
        DataKind.POLICY_DOCUMENT,
        DataKind.LLM_FACTOR,
    )
    assert scope.optional_kinds == (
        DataKind.FINANCIAL_DISCLOSURE,
        DataKind.FINANCIAL_FACT,
    )
