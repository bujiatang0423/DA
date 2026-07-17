from datetime import datetime, UTC
from decimal import Decimal

from backend.app.contracts.grades import DataGrade
from backend.app.core.market.pit_models import (
    DataKind,
    PointInTimeSnapshot,
    SecurityObservation,
    SnapshotQuality,
    SnapshotScope,
    TemporalRecord,
)
from backend.app.core.market.strategy_inputs import (
    StrategyInputBuilder,
    atr14,
    moving_average,
    obv_slope,
    winsorized_percentile,
)
from backend.app.core.portfolio.models import PortfolioSnapshot


UTC = UTC


def test_indicator_functions_have_deterministic_values_and_guards() -> None:
    assert moving_average(tuple(range(1, 21)), 20) == 10.5
    bars = tuple({"high": 11, "low": 9, "close": 10, "volume": 100} for _ in range(15))
    assert atr14(bars) == 2
    assert obv_slope(bars) == 0
    assert winsorized_percentile((1.0, 2.0, 3.0), 2.0) == 2 / 3


def _r(rid: str, kind: DataKind, entity: str, payload: dict[str, object]) -> TemporalRecord:
    when = datetime(2026, 1, 1, tzinfo=UTC)
    return TemporalRecord(rid, kind, entity, when, when, when, rid, payload)


def _snapshot(records: tuple[TemporalRecord, ...]) -> PointInTimeSnapshot:
    market = tuple(r for r in records if r.entity_id.startswith("MARKET:"))
    grouped = {}
    for r in records:
        if not r.entity_id.startswith("MARKET:"):
            grouped.setdefault(r.entity_id, []).append(r)
    return PointInTimeSnapshot(
        datetime(2026, 1, 1, tzinfo=UTC),
        SnapshotScope(),
        DataGrade.PIT_VERIFIED,
        market,
        tuple(SecurityObservation(k, tuple(v)) for k, v in grouped.items()),
        SnapshotQuality(()),
        (),
        "a" * 64,
    )


def test_builder_maps_policy_llm_and_marks_incomplete_financial_quality() -> None:
    bars = tuple(
        _r(
            f"bar{i}",
            DataKind.DAILY_BAR_RAW,
            "AAA",
            {
                "trade_date": f"2025-01-{i + 1:02d}",
                "close": 10 + i,
                "high": 11 + i,
                "low": 9 + i,
                "volume": 100000,
                "amount": 60000000,
            },
        )
        for i in range(20)
    )
    rows = (
        _r("breadth", DataKind.REALTIME_QUOTE, "MARKET:INDEX", {"breadth": 0.6, "close": 10}),
        _r("master", DataKind.SECURITY_MASTER, "AAA", {"name": "Alpha", "listing_days": 200}),
        _r(
            "policy",
            DataKind.POLICY_DOCUMENT,
            "AAA",
            {
                "strength": 0.8,
                "relevance": 0.7,
                "stage": "pilot",
                "evidence_confidence": 0.9,
                "data_completeness": 0.8,
            },
        ),
        _r("llm", DataKind.LLM_FACTOR, "AAA", {"factor": {}}),
        *bars,
    )
    portfolio = PortfolioSnapshot(
        "p", datetime(2026, 1, 1, tzinfo=UTC), 1, Decimal("0"), Decimal("100"), ()
    )
    result = StrategyInputBuilder().build(
        snapshot=_snapshot(rows), portfolio=portfolio, strategy_version="v1.0"
    )
    item = result.securities[0]
    assert item.policy_sources_available and item.llm_factor_valid
    assert "FINANCIAL_TEMPLATE_INCOMPLETE" in item.quality_codes
    assert not item.hard_filter_passed
    assert item.above_ma20 and not item.above_ma60
    assert item.breakout_or_valid_pullback
    assert item.breakout_volume_percentile > 0
    assert item.turnover_percentile > 0
