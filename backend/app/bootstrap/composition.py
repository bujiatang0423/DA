from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from types import ModuleType
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, sessionmaker

from backend.app.bootstrap.settings import Settings
from backend.app.core.market.strategy_inputs import StrategyInputBuilder
from backend.app.core.portfolio.writer import AuditedPortfolioWriter
from backend.app.core.strategy.service import V212StrategyEngine
from backend.app.features.candidates.repository import SqlCandidateRepository
from backend.app.features.candidates.service import CandidateService
from backend.app.features.holdings.repository import SqlHoldingResultRepository
from backend.app.features.holdings.service import V212HoldingAnalysisService
from backend.app.infrastructure.market.provider_source import ProviderResearchSource
from backend.app.infrastructure.market.build import build_point_in_time_warehouse
from backend.app.infrastructure.market.research_providers import (
    AkShareDailyBarProvider,
    BaoStockDailyBarProvider,
    FallbackDailyBarProvider,
)
from backend.app.infrastructure.market.research_warehouse import ResearchPointInTimeWarehouse
from backend.app.infrastructure.market.unavailable import UnavailableResearchWarehouse
from backend.app.infrastructure.persistence.portfolio_reader import SqlPortfolioReader
from backend.app.infrastructure.persistence.portfolio_repository import SqlPortfolioEventStore
from backend.app.ports.llm_factor import LlmFactorPort
from backend.app.ports.point_in_time import PointInTimeWarehouse
from backend.app.ports.policy import PolicyPort
from backend.app.ports.research_data import ResearchMarketDataPort


class ProviderConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class ProductionResearchProviders:
    """Complete ports required to build the production research evidence chain."""

    market: ResearchMarketDataPort
    policy: PolicyPort
    llm: LlmFactorPort


ResearchProviderFactory = Callable[[Settings], ProductionResearchProviders]

_MARKET_PORT_METHODS = (
    "trade_calendar",
    "universe",
    "quotes",
    "daily_bars",
    "financials",
    "fee_schedules",
)
_POLICY_PORT_METHODS = ("materials",)
_LLM_PORT_METHODS = ("extract",)


@dataclass(frozen=True)
class ApplicationComponents:
    strategy_engine: V212StrategyEngine
    warehouse: PointInTimeWarehouse
    candidate_service: CandidateService
    holding_service: V212HoldingAnalysisService
    holding_repository: SqlHoldingResultRepository
    portfolio_writer: AuditedPortfolioWriter


def _provider_module(name: str) -> ModuleType:
    try:
        return import_module(name)
    except ImportError as exc:
        raise ProviderConfigurationError(
            f"production provider dependency is missing: {name}"
        ) from exc


def _configured_research_providers(settings: Settings) -> ProductionResearchProviders | None:
    """Load deployment-owned providers without leaking configuration or client failures."""
    reference = settings.research_provider_factory
    if not reference:
        return None
    module_name, separator, attribute = reference.partition(":")
    if not module_name or not separator or not attribute:
        return None
    try:
        factory = getattr(import_module(module_name), attribute)
        providers = factory(settings)
    except Exception:
        return None
    if not isinstance(providers, ProductionResearchProviders):
        return None
    if not _supports_port(providers.market, ResearchMarketDataPort, _MARKET_PORT_METHODS):
        return None
    if not _supports_port(providers.policy, PolicyPort, _POLICY_PORT_METHODS):
        return None
    if not _supports_port(providers.llm, LlmFactorPort, _LLM_PORT_METHODS):
        return None
    return providers


def _supports_port(value: object, protocol: type[object], methods: tuple[str, ...]) -> bool:
    return isinstance(value, protocol) and all(
        callable(getattr(value, method, None)) for method in methods
    )


def build_warehouse(
    settings: Settings,
    *,
    fake_warehouse: PointInTimeWarehouse | None = None,
    akshare_module: ModuleType | None = None,
    baostock_module: ModuleType | None = None,
) -> PointInTimeWarehouse:
    if settings.environment != "test" and settings.provider_mode == "fake":
        raise ProviderConfigurationError("fake provider mode is allowed only in test environment")

    if settings.environment != "test" and (
        akshare_module is not None or baostock_module is not None
    ):
        raise ProviderConfigurationError(
            "injected provider modules are allowed only in test environment"
        )

    if settings.provider_mode == "fake":
        if fake_warehouse is None:
            raise ProviderConfigurationError(
                "fake provider mode requires an explicit fake warehouse"
            )
        return fake_warehouse

    if fake_warehouse is not None:
        raise ProviderConfigurationError("production provider mode rejects a fake warehouse")

    providers = _configured_research_providers(settings)
    if providers is not None:
        return build_point_in_time_warehouse(
            market=providers.market,
            policy=providers.policy,
            llm=providers.llm,
        )

    if settings.environment != "test":
        return UnavailableResearchWarehouse()

    akshare = akshare_module or _provider_module("akshare")
    baostock = baostock_module or _provider_module("baostock")
    daily_bars = FallbackDailyBarProvider(
        primary=AkShareDailyBarProvider(akshare),
        fallback=BaoStockDailyBarProvider(baostock),
    )
    source = ProviderResearchSource(daily_bars, ZoneInfo(settings.timezone))
    return ResearchPointInTimeWarehouse((source,))


def build_components(
    settings: Settings,
    sessions: sessionmaker[Session],
    *,
    fake_warehouse: PointInTimeWarehouse | None = None,
    akshare_module: ModuleType | None = None,
    baostock_module: ModuleType | None = None,
) -> ApplicationComponents:
    """Build shared strategy dependencies without duplicating feature logic.

    Fake data is accepted only through the explicit test-mode seam. Production always selects the
    real provider chain and missing datasets remain subject to the warehouse's fail-closed checks.
    """
    warehouse = build_warehouse(
        settings,
        fake_warehouse=fake_warehouse,
        akshare_module=akshare_module,
        baostock_module=baostock_module,
    )
    strategy = V212StrategyEngine()
    service = CandidateService(
        warehouse,
        SqlPortfolioReader(sessions),
        StrategyInputBuilder(),
        strategy,
        SqlCandidateRepository(sessions),
    )
    holding_repository = SqlHoldingResultRepository(sessions)
    holding_service = V212HoldingAnalysisService(
        warehouse,
        SqlPortfolioReader(sessions),
        StrategyInputBuilder(),
        strategy,
        holding_repository,
    )
    portfolio_writer = AuditedPortfolioWriter(SqlPortfolioEventStore(sessions))
    return ApplicationComponents(
        strategy,
        warehouse,
        service,
        holding_service,
        holding_repository,
        portfolio_writer,
    )
