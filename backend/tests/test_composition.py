from datetime import UTC, date, datetime
from decimal import Decimal
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
from backend.app.core.market.pit_models import DataKind, PointInTimeSnapshot, SnapshotScope
from backend.app.core.portfolio.models import PortfolioSnapshot
from backend.app.core.strategy.service import V212StrategyEngine
from backend.app.features.candidates.service import (
    CandidateRecommendationCommand,
    CandidateService,
)
from backend.app.infrastructure.market.research_providers import FallbackDailyBarProvider
from backend.app.infrastructure.market.research_warehouse import ResearchPointInTimeWarehouse
from backend.app.infrastructure.market.unavailable import UnavailableResearchWarehouse
from backend.app.ports.llm_factor import StructuredLlmFactor
from backend.app.ports.point_in_time import PointInTimeWarehouse
from backend.app.ports.policy import PolicyMaterial
from backend.app.ports.research_data import (
    CalendarDay,
    FinancialMaterial,
    ResearchBar,
    ResearchFeeSchedule,
    ResearchQuote,
    UniverseSecurity,
)


class FrozenWarehouse:
    def snapshot(
        self,
        *,
        as_of_time: datetime,
        scope: SnapshotScope,
    ) -> PointInTimeSnapshot:
        raise AssertionError((as_of_time, scope))


class CandidateScopeWithSecurity:
    def __init__(self, warehouse: PointInTimeWarehouse) -> None:
        self._warehouse = warehouse

    def snapshot(
        self,
        *,
        as_of_time: datetime,
        scope: SnapshotScope,
    ) -> PointInTimeSnapshot:
        return self._warehouse.snapshot(
            as_of_time=as_of_time,
            scope=SnapshotScope(("000001.SZ",), scope.required_kinds, scope.history_start),
        )


class EmptyPortfolioReader:
    def snapshot(self, *, portfolio_id: str, as_of_time: datetime) -> PortfolioSnapshot:
        return PortfolioSnapshot(portfolio_id, as_of_time, 1, Decimal("1000"), Decimal("1000"), ())


class RecordingCandidateRepository:
    def __init__(self) -> None:
        self.saved: object | None = None

    def save(self, result: object) -> None:
        self.saved = result

    def get(self, run_id: str) -> None:
        del run_id
        return None

    def latest(self) -> None:
        return None

    def states_before(self, as_of_time: datetime) -> dict[object, object]:
        del as_of_time
        return {}


class CompleteMarket:
    def trade_calendar(self, start: date, end: date) -> tuple[CalendarDay, ...]:
        del start, end
        return ()

    def universe(self, as_of_time: datetime) -> tuple[UniverseSecurity, ...]:
        del as_of_time
        return ()

    def quotes(
        self, security_ids: tuple[str, ...], as_of_time: datetime
    ) -> tuple[ResearchQuote, ...]:
        del security_ids, as_of_time
        return ()

    def daily_bars(self, security_id: str, as_of_time: datetime) -> tuple[ResearchBar, ...]:
        del security_id, as_of_time
        return ()

    def financials(self, security_id: str, as_of_time: datetime) -> tuple[FinancialMaterial, ...]:
        del security_id, as_of_time
        return ()

    def fee_schedules(self, as_of_time: datetime) -> tuple[ResearchFeeSchedule, ...]:
        del as_of_time
        return ()


class CompletePolicy:
    def materials(self, *, as_of_time: datetime) -> tuple[PolicyMaterial, ...]:
        del as_of_time
        return ()


class CompleteLlm:
    def extract(
        self,
        *,
        as_of_time: datetime,
        security_id: str,
        policy_materials: tuple[PolicyMaterial, ...],
        financial_materials: tuple[FinancialMaterial, ...],
    ) -> StructuredLlmFactor:
        del as_of_time, security_id, policy_materials, financial_materials
        raise RuntimeError("not used by composition test")


class BrokenMarket(CompleteMarket):
    trade_calendar = 0


def complete_research_provider_factory(settings: Settings) -> ProductionResearchProviders:
    del settings
    return ProductionResearchProviders(
        market=CompleteMarket(), policy=CompletePolicy(), llm=CompleteLlm()
    )


def object_research_provider_factory(settings: Settings) -> ProductionResearchProviders:
    del settings
    return ProductionResearchProviders(market=object(), policy=object(), llm=object())


def broken_market_research_provider_factory(settings: Settings) -> ProductionResearchProviders:
    del settings
    return ProductionResearchProviders(
        market=BrokenMarket(), policy=CompletePolicy(), llm=CompleteLlm()
    )


def missing_research_provider_factory(settings: Settings) -> object:
    del settings
    return object()


def failing_research_provider_factory(settings: Settings) -> ProductionResearchProviders:
    del settings
    raise RuntimeError("upstream secret")


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


def test_unconfigured_production_evidence_factory_fails_closed() -> None:
    settings = Settings(_env_file=None, environment="production", provider_mode="production")

    warehouse = build_warehouse(settings)

    assert isinstance(warehouse, UnavailableResearchWarehouse)
    snapshot = warehouse.snapshot(
        as_of_time=datetime(2026, 7, 20, 16, tzinfo=UTC),
        scope=SnapshotScope.candidate_recommendation(),
    )
    assert snapshot.quality.has_errors
    assert {issue.code for issue in snapshot.quality.issues} == {"REQUIRED_DATASET_MISSING"}
    assert {issue.dataset for issue in snapshot.quality.issues} == {kind.value for kind in DataKind}


def test_configured_production_evidence_factory_builds_one_complete_warehouse() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        provider_mode="production",
        research_provider_factory="backend.tests.test_composition:complete_research_provider_factory",
    )

    warehouse = build_warehouse(settings)

    assert isinstance(warehouse, ResearchPointInTimeWarehouse)
    assert len(warehouse.sources) == 1
    evidence = warehouse.sources[0]
    assert len(evidence.sources) == 3


def test_factory_with_non_port_members_fails_closed_before_warehouse_construction() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        provider_mode="production",
        research_provider_factory="backend.tests.test_composition:object_research_provider_factory",
    )

    warehouse = build_warehouse(settings)

    assert isinstance(warehouse, UnavailableResearchWarehouse)


def test_factory_with_non_callable_port_member_fails_closed_before_warehouse_construction() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        provider_mode="production",
        research_provider_factory=(
            "backend.tests.test_composition:broken_market_research_provider_factory"
        ),
    )

    warehouse = build_warehouse(settings)

    assert isinstance(warehouse, UnavailableResearchWarehouse)


@pytest.mark.parametrize(
    "factory_name",
    ("missing_research_provider_factory", "failing_research_provider_factory"),
)
def test_missing_or_failing_factory_fails_closed(factory_name: str) -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        provider_mode="production",
        research_provider_factory=f"backend.tests.test_composition:{factory_name}",
    )

    assert isinstance(build_warehouse(settings), UnavailableResearchWarehouse)


def test_invalid_production_evidence_factory_fails_closed_without_import_details() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        provider_mode="production",
        research_provider_factory="missing.provider:factory",
    )

    warehouse = build_warehouse(settings)
    snapshot = warehouse.snapshot(
        as_of_time=datetime(2026, 7, 20, 16, tzinfo=UTC),
        scope=SnapshotScope(("000001.SZ",), (DataKind.DAILY_BAR_RAW,)),
    )

    assert isinstance(warehouse, UnavailableResearchWarehouse)
    assert [(issue.code, issue.dataset) for issue in snapshot.quality.issues] == [
        ("REQUIRED_DATASET_MISSING", DataKind.DAILY_BAR_RAW.value)
    ]


def test_production_provider_mode_rejects_a_fake_override() -> None:
    settings = Settings(_env_file=None, provider_mode="production")

    with pytest.raises(ProviderConfigurationError, match="production"):
        build_warehouse(settings, fake_warehouse=FrozenWarehouse())


def test_non_test_environment_rejects_injected_provider_modules() -> None:
    settings = Settings(_env_file=None, environment="production", provider_mode="production")

    with pytest.raises(ProviderConfigurationError, match="test environment"):
        build_warehouse(settings, akshare_module=ModuleType("akshare"))


def test_non_test_environment_rejects_fake_provider_mode() -> None:
    settings = Settings(_env_file=None, environment="production", provider_mode="fake")

    with pytest.raises(ProviderConfigurationError, match="test environment"):
        build_warehouse(settings, fake_warehouse=FrozenWarehouse())


def test_components_share_the_explicit_fake_warehouse() -> None:
    settings = Settings(_env_file=None, environment="test", provider_mode="fake")
    warehouse = FrozenWarehouse()

    components = build_components(settings, sessionmaker(), fake_warehouse=warehouse)

    assert components.warehouse is warehouse
    assert components.candidate_service._warehouse is warehouse
    assert components.holding_service._warehouse is warehouse
    assert components.portfolio_writer.__class__.__name__ == "AuditedPortfolioWriter"


def test_configured_provider_failure_is_sanitized_and_cannot_create_candidates() -> None:
    settings = Settings(_env_file=None, environment="test", provider_mode="production")
    akshare = ModuleType("akshare")
    baostock = ModuleType("baostock")

    def unavailable(**kwargs: object) -> None:
        del kwargs
        raise RuntimeError("credential=secret upstream response")

    akshare.stock_zh_a_hist = unavailable  # type: ignore[attr-defined]
    components = build_components(
        settings,
        sessionmaker(),
        akshare_module=akshare,
        baostock_module=baostock,
    )
    as_of_time = datetime(2026, 7, 19, 16, tzinfo=UTC)
    snapshot = components.warehouse.snapshot(
        as_of_time=as_of_time,
        scope=SnapshotScope(("000001.SZ",), (DataKind.DAILY_BAR_RAW,)),
    )

    issue = next(issue for issue in snapshot.quality.issues if issue.code == "PROVIDER_UNAVAILABLE")
    repository = RecordingCandidateRepository()
    service = CandidateService(
        CandidateScopeWithSecurity(components.warehouse),
        EmptyPortfolioReader(),
        components.candidate_service._input_builder,
        V212StrategyEngine(),
        repository,
    )
    result = service.run(CandidateRecommendationCommand("run-1", "portfolio-1", as_of_time))

    assert snapshot.quality.has_errors
    assert "secret" not in issue.detail
    assert result.items == ()
    assert "PROVIDER_UNAVAILABLE" in result.quality_codes
