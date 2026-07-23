from datetime import datetime
from types import ModuleType

import pytest
from sqlalchemy.orm import sessionmaker

from backend.app.bootstrap.composition import (
    ProductionResearchProviders,
    ProviderConfigurationError,
    build_components,
    build_warehouse,
)
from backend.app.bootstrap.settings import Settings
from backend.app.core.market.pit_models import (
    DataKind,
    LineageRef,
    PointInTimeSnapshot,
    SnapshotQuality,
    SnapshotScope,
    SecurityObservation,
    TemporalRecord,
)
from backend.app.contracts.grades import DataGrade
from backend.app.infrastructure.market.research_providers import FallbackDailyBarProvider
from backend.app.infrastructure.market.research_warehouse import ResearchPointInTimeWarehouse
from backend.app.infrastructure.market.official_evidence import OfficialEvidenceSource
from backend.app.infrastructure.market.unavailable import UnavailableResearchWarehouse


class FrozenWarehouse:
    def snapshot(
        self,
        *,
        as_of_time: datetime,
        scope: SnapshotScope,
    ) -> PointInTimeSnapshot:
        raise AssertionError((as_of_time, scope))


class DeterministicCandidateWarehouse:
    def snapshot(
        self,
        *,
        as_of_time: datetime,
        scope: SnapshotScope,
    ) -> PointInTimeSnapshot:
        source_hash = "c" * 64
        records = tuple(
            TemporalRecord(
                f"{kind.value}:AAA",
                kind,
                "AAA",
                as_of_time,
                as_of_time,
                as_of_time,
                source_hash,
                {"source_id": "fixture", "value": "neutral"},
            )
            for kind in (
                DataKind.FINANCIAL_DISCLOSURE,
                DataKind.FINANCIAL_FACT,
                DataKind.POLICY_DOCUMENT,
                DataKind.LLM_FACTOR,
            )
        )
        return PointInTimeSnapshot(
            as_of_time=as_of_time,
            scope=scope,
            data_grade=DataGrade.RESEARCH,
            market_inputs=(),
            security_observations=(SecurityObservation("AAA", records),),
            quality=SnapshotQuality(()),
            lineage=(LineageRef("candidate-fixture", "test", source_hash),),
            manifest_hash="d" * 64,
        )


def test_fake_provider_mode_requires_an_explicit_frozen_warehouse() -> None:
    settings = Settings(_env_file=None, environment="test", provider_mode="fake")

    with pytest.raises(ProviderConfigurationError, match="fake warehouse"):
        build_warehouse(settings)

    warehouse = FrozenWarehouse()

    assert build_warehouse(settings, fake_warehouse=warehouse) is warehouse


def test_production_provider_mode_builds_the_real_fallback_chain() -> None:
    settings = Settings(_env_file=None, environment="test", provider_mode="production")
    akshare = ModuleType("akshare")
    baostock = ModuleType("baostock")

    warehouse = build_warehouse(
        settings,
        akshare_module=akshare,
        baostock_module=baostock,
    )

    assert isinstance(warehouse, ResearchPointInTimeWarehouse)
    source = warehouse.sources[0]
    assert isinstance(source.provider, FallbackDailyBarProvider)
    assert source.provider.primary.module is akshare
    assert source.provider.fallback.module is baostock


def test_production_provider_mode_rejects_a_fake_override() -> None:
    settings = Settings(_env_file=None, provider_mode="production")

    with pytest.raises(ProviderConfigurationError, match="production"):
        build_warehouse(settings, fake_warehouse=FrozenWarehouse())


def test_missing_optional_market_clients_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None, environment="test", provider_mode="production")
    from backend.app.bootstrap import composition

    def missing(name: str) -> ModuleType:
        raise composition.ProviderConfigurationError(name)

    monkeypatch.setattr(composition, "_provider_module", missing)

    warehouse = build_warehouse(settings)

    assert isinstance(warehouse, UnavailableResearchWarehouse)


def test_configured_provider_factory_builds_the_unified_research_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        provider_mode="production",
        research_provider_factory="fixture_provider:build",
    )

    class Market:
        def trade_calendar(self, *args: object) -> tuple[object, ...]:
            return ()

        def universe(self, *args: object) -> tuple[object, ...]:
            return ()

        def quotes(self, *args: object) -> tuple[object, ...]:
            return ()

        def daily_bars(self, *args: object) -> tuple[object, ...]:
            return ()

        def financials(self, *args: object) -> tuple[object, ...]:
            return ()

        def fee_schedules(self, *args: object) -> tuple[object, ...]:
            return ()

    class Policy:
        def materials(self, *, as_of_time: datetime) -> tuple[object, ...]:
            del as_of_time
            return ()

    class Llm:
        def extract(self, **kwargs: object) -> object:
            del kwargs
            return object()

    import sys

    module = ModuleType("fixture_provider")
    module.build = lambda current: ProductionResearchProviders(Market(), Policy(), Llm())
    monkeypatch.setitem(sys.modules, "fixture_provider", module)

    warehouse = build_warehouse(settings)

    assert isinstance(warehouse, ResearchPointInTimeWarehouse)
    assert warehouse.sources[0].sources[0].provider == "research_market"


def test_incomplete_configured_provider_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        provider_mode="production",
        research_provider_factory="fixture_provider:build",
    )
    import sys

    module = ModuleType("fixture_provider")
    module.build = lambda current: object()
    monkeypatch.setitem(sys.modules, "fixture_provider", module)

    warehouse = build_warehouse(settings)

    assert isinstance(warehouse, UnavailableResearchWarehouse)


def test_production_components_inject_persisted_official_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        provider_mode="production",
        research_provider_factory="fixture_provider:build",
    )

    class Market:
        def trade_calendar(self, *args: object) -> tuple[object, ...]: return ()
        def universe(self, *args: object) -> tuple[object, ...]: return ()
        def quotes(self, *args: object) -> tuple[object, ...]: return ()
        def daily_bars(self, *args: object) -> tuple[object, ...]: return ()
        def financials(self, *args: object) -> tuple[object, ...]: return ()
        def fee_schedules(self, *args: object) -> tuple[object, ...]: return ()

    class Policy:
        def materials(self, *, as_of_time: datetime) -> tuple[object, ...]: return ()

    class Llm:
        def extract(self, **kwargs: object) -> object: return object()

    import sys

    module = ModuleType("fixture_provider")
    module.build = lambda current: ProductionResearchProviders(Market(), Policy(), Llm())
    monkeypatch.setitem(sys.modules, "fixture_provider", module)

    components = build_components(settings, sessionmaker())

    assert isinstance(components.warehouse, ResearchPointInTimeWarehouse)
    assert any(
        isinstance(source, OfficialEvidenceSource)
        for source in components.warehouse.sources[0].sources
    )


def test_components_share_the_explicit_fake_warehouse() -> None:
    settings = Settings(_env_file=None, environment="test", provider_mode="fake")
    warehouse = FrozenWarehouse()

    components = build_components(settings, sessionmaker(), fake_warehouse=warehouse)

    assert components.warehouse is warehouse
    assert components.candidate_service._warehouse is warehouse
    assert components.holding_service._warehouse is warehouse
    assert components.portfolio_writer.__class__.__name__ == "AuditedPortfolioWriter"


def test_candidate_composition_accepts_deterministic_policy_financial_llm_fixture() -> None:
    settings = Settings(_env_file=None, environment="test", provider_mode="fake")
    warehouse = DeterministicCandidateWarehouse()

    components = build_components(settings, sessionmaker(), fake_warehouse=warehouse)
    snapshot = components.warehouse.snapshot(
        as_of_time=datetime(2026, 1, 1),
        scope=SnapshotScope(
            security_ids=("AAA",),
            required_kinds=(
                DataKind.FINANCIAL_DISCLOSURE,
                DataKind.FINANCIAL_FACT,
                DataKind.POLICY_DOCUMENT,
                DataKind.LLM_FACTOR,
            ),
        ),
    )

    assert components.candidate_service._warehouse is warehouse
    assert {record.kind for record in snapshot.security_observations[0].records} == {
        DataKind.FINANCIAL_DISCLOSURE,
        DataKind.FINANCIAL_FACT,
        DataKind.POLICY_DOCUMENT,
        DataKind.LLM_FACTOR,
    }
