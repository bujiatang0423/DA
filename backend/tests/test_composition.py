from datetime import datetime
from types import ModuleType

import pytest
from sqlalchemy.orm import sessionmaker

from backend.app.bootstrap.composition import (
    ProviderConfigurationError,
    build_components,
    build_warehouse,
)
from backend.app.bootstrap.settings import Settings
from backend.app.core.market.pit_models import PointInTimeSnapshot, SnapshotScope
from backend.app.infrastructure.market.research_providers import FallbackDailyBarProvider
from backend.app.infrastructure.market.research_warehouse import ResearchPointInTimeWarehouse


class FrozenWarehouse:
    def snapshot(
        self,
        *,
        as_of_time: datetime,
        scope: SnapshotScope,
    ) -> PointInTimeSnapshot:
        raise AssertionError((as_of_time, scope))


def test_fake_provider_mode_requires_an_explicit_frozen_warehouse() -> None:
    settings = Settings(_env_file=None, environment="test", provider_mode="fake")

    with pytest.raises(ProviderConfigurationError, match="fake warehouse"):
        build_warehouse(settings)

    warehouse = FrozenWarehouse()

    assert build_warehouse(settings, fake_warehouse=warehouse) is warehouse


def test_production_provider_mode_builds_the_real_fallback_chain() -> None:
    settings = Settings(_env_file=None, provider_mode="production")
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


def test_components_share_the_explicit_fake_warehouse() -> None:
    settings = Settings(_env_file=None, environment="test", provider_mode="fake")
    warehouse = FrozenWarehouse()

    components = build_components(settings, sessionmaker(), fake_warehouse=warehouse)

    assert components.warehouse is warehouse
    assert components.candidate_service._warehouse is warehouse
    assert components.holding_service._warehouse is warehouse
    assert components.portfolio_writer.__class__.__name__ == "AuditedPortfolioWriter"
