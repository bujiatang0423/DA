from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from backend.app.core.market.pit_models import DataKind, SnapshotScope
from backend.app.infrastructure.market.extended_provider_source import (
    ExtendedMarketProviderSource,
    ProviderDataUnavailableError,
    ProviderIndexBar,
    ProviderMarketBreadth,
    ProviderMembership,
    ProviderUniverseSecurity,
)
from backend.app.infrastructure.market.research_warehouse import ResearchPointInTimeWarehouse


AS_OF = datetime(2026, 7, 20, 16, tzinfo=UTC)


@dataclass
class Provider:
    provider_name: str = "fixture_extended_market"
    future_breadth: bool = False
    universe_unavailable: bool = False

    def index_daily_bars(
        self, index_id: str, start: date, end: date
    ) -> tuple[ProviderIndexBar, ...]:
        del start, end
        return (
            ProviderIndexBar(
                index_id=index_id,
                trade_date=AS_OF.date(),
                open=Decimal("10"),
                high=Decimal("11"),
                low=Decimal("9"),
                close=Decimal("10.5"),
                volume=100,
                amount=Decimal("1000"),
                available_at=AS_OF,
                source_artifact_hash="index-hash",
            ),
        )

    def market_breadth(self, as_of_time: datetime) -> ProviderMarketBreadth:
        available_at = (
            as_of_time.replace(day=as_of_time.day + 1) if self.future_breadth else as_of_time
        )
        return ProviderMarketBreadth(
            market_id="CN-A",
            event_time=as_of_time,
            breadth=Decimal("0.6"),
            advancing_count=3000,
            declining_count=1000,
            security_count=4000,
            available_at=available_at,
            source_artifact_hash="breadth-hash",
        )

    def universe(self, as_of_time: datetime) -> tuple[ProviderUniverseSecurity, ...]:
        if self.universe_unavailable:
            raise RuntimeError("universe is unavailable")
        return (
            ProviderUniverseSecurity(
                security_id="000001.SZ",
                name="Ping An Bank",
                listed_on=date(1991, 4, 3),
                valid_from=date(1991, 4, 3),
                valid_to=None,
                available_at=as_of_time,
                source_artifact_hash="universe-hash",
            ),
        )

    def industry_memberships(
        self, security_ids: tuple[str, ...], as_of_time: datetime
    ) -> tuple[ProviderMembership, ...]:
        return tuple(
            ProviderMembership(
                security_id=security_id,
                classification_id="bank",
                effective_from=date(2020, 1, 1),
                effective_to=None,
                available_at=as_of_time,
                source_artifact_hash="industry-hash",
            )
            for security_id in security_ids
        )

    def theme_memberships(
        self, security_ids: tuple[str, ...], as_of_time: datetime
    ) -> tuple[ProviderMembership, ...]:
        return tuple(
            ProviderMembership(
                security_id=security_id,
                classification_id="financials",
                effective_from=date(2020, 1, 1),
                effective_to=None,
                available_at=as_of_time,
                source_artifact_hash="theme-hash",
            )
            for security_id in security_ids
        )


def test_extended_source_maps_pit_records_and_lineage() -> None:
    source = ExtendedMarketProviderSource(Provider(), benchmark_ids=("000300.SH",))
    batch = source.fetch(
        as_of_time=AS_OF,
        scope=SnapshotScope(
            required_kinds=(
                DataKind.INDEX_DAILY_BAR,
                DataKind.MARKET_BREADTH,
                DataKind.SECURITY_MASTER,
                DataKind.INDUSTRY_MEMBERSHIP,
                DataKind.THEME_MEMBERSHIP,
            )
        ),
    )

    assert {record.kind for record in batch.records} == {
        DataKind.INDEX_DAILY_BAR,
        DataKind.MARKET_BREADTH,
        DataKind.SECURITY_MASTER,
        DataKind.INDUSTRY_MEMBERSHIP,
        DataKind.THEME_MEMBERSHIP,
    }
    assert all(record.available_at <= AS_OF for record in batch.records)
    assert {lineage.source_artifact_hash for lineage in batch.lineage} == {
        "index-hash",
        "breadth-hash",
        "universe-hash",
        "industry-hash",
        "theme-hash",
    }


def test_extended_source_rejects_future_only_required_data() -> None:
    source = ExtendedMarketProviderSource(Provider(future_breadth=True))

    with pytest.raises(ProviderDataUnavailableError, match="market_breadth"):
        source.fetch(
            as_of_time=AS_OF,
            scope=SnapshotScope(required_kinds=(DataKind.MARKET_BREADTH,)),
        )


def test_future_only_data_fails_closed_when_used_by_the_research_warehouse() -> None:
    source = ExtendedMarketProviderSource(Provider(future_breadth=True))

    snapshot = ResearchPointInTimeWarehouse((source,)).snapshot(
        as_of_time=AS_OF,
        scope=SnapshotScope(required_kinds=(DataKind.MARKET_BREADTH,)),
    )

    assert snapshot.quality.has_errors
    assert {issue.code for issue in snapshot.quality.issues} >= {
        "PROVIDER_UNAVAILABLE",
        "REQUIRED_DATASET_MISSING",
    }


def test_extended_source_rejects_a_scoped_security_missing_from_the_universe() -> None:
    source = ExtendedMarketProviderSource(Provider())

    with pytest.raises(ProviderDataUnavailableError, match="security_master"):
        source.fetch(
            as_of_time=AS_OF,
            scope=SnapshotScope(
                security_ids=("000002.SZ",),
                required_kinds=(DataKind.SECURITY_MASTER,),
            ),
        )


def test_index_only_scope_does_not_require_an_unrelated_universe_call() -> None:
    source = ExtendedMarketProviderSource(Provider(universe_unavailable=True))

    batch = source.fetch(
        as_of_time=AS_OF,
        scope=SnapshotScope(required_kinds=(DataKind.INDEX_DAILY_BAR,)),
    )

    assert {record.kind for record in batch.records} == {DataKind.INDEX_DAILY_BAR}


def test_scoped_warehouse_keeps_required_extended_market_inputs() -> None:
    source = ExtendedMarketProviderSource(Provider(), benchmark_ids=("000300.SH",))
    scope = SnapshotScope(
        security_ids=("000001.SZ",),
        required_kinds=(DataKind.INDEX_DAILY_BAR, DataKind.MARKET_BREADTH),
    )

    snapshot = ResearchPointInTimeWarehouse((source,)).snapshot(
        as_of_time=AS_OF,
        scope=scope,
    )

    assert snapshot.quality.has_errors is False
    assert {record.kind for record in snapshot.market_inputs} == set(scope.required_kinds)
    assert {record.entity_id for record in snapshot.market_inputs} == {
        "MARKET:000300.SH",
        "MARKET:CN-A:BREADTH",
    }
