from datetime import UTC, datetime
from decimal import Decimal
from types import ModuleType

import pytest
from sqlalchemy.orm import sessionmaker

from backend.app.bootstrap.composition import (
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
from backend.app.ports.point_in_time import PointInTimeWarehouse


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
