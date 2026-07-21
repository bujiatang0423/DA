# DA Local System Integration and Acceptance Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 foundation、PIT/legacy、候选、持仓和 backtest 接成一个可在本机 PostgreSQL 上重复验收的 DA 本地测试系统。

**Scope boundary:** 本计划不包含上线、生产 provider、发布镜像、Docker/Compose 部署或远程 CI
运行。所有验收均使用本地 `127.0.0.1:5432` PostgreSQL、冻结 fixture、FastAPI、worker 和本地
Web；未来需要上线时另立生产部署计划。

**Architecture:** 组合根只实例化并注入已完成模块，功能逻辑仍留在各自 vertical slice；统一 Alembic 迁移和 OpenAPI 由协调 Agent 生成。系统测试用冻结 fake 数据运行真实 API、PostgreSQL worker 和 Web，并验证 DA 运行时不依赖 LA。

**Tech Stack:** FastAPI、SQLAlchemy/Alembic、PostgreSQL 16、pytest、React/TypeScript、Vitest、Playwright、OpenAPI TypeScript

---

## 前置条件、所有权和冻结导出

本计划必须在 `00`—`05` 全部合入后执行。开始前以下命令必须全绿：

```bash
make verify
python -m pytest backend/tests/core backend/tests/features -q
cd web && npm test -- --run
```

协调 Agent 独占本计划涉及的 `bootstrap/**`、`main.py`、Alembic 迁移链、
`contracts/openapi.json`、`web/src/generated/**`、`web/src/app/**` 和本地验收脚本。
本计划不得修改以下共享公式实现：

```text
backend/app/core/strategy/factors.py
backend/app/core/strategy/market_regime.py
backend/app/core/strategy/risk.py
backend/app/core/strategy/constraints.py
backend/app/core/strategy/service.py
```

必须按下列已冻结导出接线，不另建 adapter 复制 feature 逻辑：

```text
backend.app.features.candidates.module.build_candidate_feature(CandidateDependencies)
backend.app.features.holdings.module.build_holding_feature(HoldingDependencies)
backend.app.features.backtests.module.build_backtest_feature(BacktestDependencies)
web/src/features/candidates/index.tsx       candidateFeature
web/src/features/holdings/index.tsx         holdingFeature
web/src/features/backtests/index.tsx        backtestsFeature
web/src/features/runs/index.tsx             runsFeature
```

候选 ORM 来自 `features/candidates/repository.py`，持仓 ORM 来自
`features/holdings/repository.py`，回测 ORM 来自 `features/backtests/db_models.py`。
PIT/legacy 的 builder 和 ORM 路径以 `01` 最终导出为准；Task 1 的 import-contract test 是
机械发现命名漂移的唯一入口，发现漂移时修改组合根 import，不改 feature 内部实现。

### Task 1: 建立全模块 import contract 和唯一组合根

**Files:**
- Create: `backend/app/bootstrap/composition.py`
- Create: `backend/app/bootstrap/backtest_decision.py`
- Create: `backend/tests/system/conftest.py`
- Create: `backend/tests/system/test_composition.py`
- Create: `backend/tests/system/test_backtest_decision_adapter.py`
- Modify: `backend/app/bootstrap/default_features.py`
- Modify: `backend/app/bootstrap/application.py`

- [ ] **Step 1: 写失败的全模块注册 test**

```python
# backend/tests/system/test_composition.py
from backend.app.bootstrap.composition import build_components
from backend.app.bootstrap.settings import Settings
from backend.app.contracts.runs import RunKind


def test_composition_registers_every_product_feature(test_database_url: str) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=test_database_url,
        provider_mode="fake",
    )
    components = build_components(settings, fake_trading_days)

    assert [module.name for module in components.features] == [
        "runs",
        "candidates",
        "holdings",
        "backtests",
    ]
    assert {kind for module in components.features for kind, _ in module.job_handlers} == {
        RunKind.CANDIDATE_RECOMMENDATION,
        RunKind.HOLDING_ANALYSIS,
        RunKind.BACKTEST,
    }
    assert components.strategy_engine.__class__.__name__ == "V212StrategyEngine"
```

```python
# backend/tests/system/conftest.py
from datetime import date
import os

import pytest

from backend.app.features.backtests.ports import BacktestTradingDayPort
from backend.app.features.backtests.testing import FixedTradingDayPort


@pytest.fixture
def test_database_url() -> str:
    return os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://da:da@127.0.0.1:55433/da_test",
    )


@pytest.fixture
def fake_trading_days() -> BacktestTradingDayPort:
    return FixedTradingDayPort(
        trading_days=(date(2026, 7, 16), date(2026, 7, 17)),
    )
```

```python
# backend/tests/system/test_backtest_decision_adapter.py
from backend.app.bootstrap.backtest_decision import V212BacktestDecisionAdapter


def test_adapter_reuses_shared_rules_and_orders_exits_before_entries(
    backtest_context: object,
    recording_input_builder: object,
    recording_strategy: object,
) -> None:
    adapter = V212BacktestDecisionAdapter(recording_input_builder, recording_strategy)

    decision = adapter.decide(backtest_context)
    intents = decision.intents

    assert recording_input_builder.calls == [
        (
            backtest_context.snapshot,
            backtest_context.portfolio,
            backtest_context.strategy_version,
        )
    ]
    assert recording_strategy.calls == 1
    assert [intent.priority for intent in intents] == [2, 100]
    assert intents[0].side.value == "sell"
    assert intents[1].side.value == "buy"
    assert decision.candidate_states != backtest_context.candidate_states
```

- [ ] **Step 2: 运行 test 并确认组合根缺失**

Run: `python -m pytest backend/tests/system/test_composition.py backend/tests/system/test_backtest_decision_adapter.py -q`
Expected: FAIL，包含 `No module named 'backend.app.bootstrap.composition'`。

- [ ] **Step 3: 实现只做构造和注入的 composition root**

```python
# backend/app/bootstrap/composition.py
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, sessionmaker

from backend.app.bootstrap.feature_registry import FeatureModule
from backend.app.bootstrap.backtest_decision import V212BacktestDecisionAdapter
from backend.app.bootstrap.settings import Settings
from backend.app.core.clock import SystemClock
from backend.app.core.market.strategy_inputs import StrategyInputBuilder
from backend.app.core.portfolio.writer import AuditedPortfolioWriter
from backend.app.core.strategy.service import V212StrategyEngine
from backend.app.features.backtests.module import (
    BacktestDependencies,
    build_backtest_dependencies,
    build_backtest_feature,
)
from backend.app.features.backtests.execution import ExecutionSimulator
from backend.app.features.backtests.ports import BacktestTradingDayPort
from backend.app.features.candidates.jobs import CandidateJobHandler
from backend.app.features.candidates.module import (
    CandidateDependencies,
    build_candidate_feature,
)
from backend.app.features.candidates.repository import SqlCandidateRepository
from backend.app.features.candidates.service import CandidateService
from backend.app.features.holdings.jobs import HoldingAnalysisJobHandler
from backend.app.features.holdings.module import HoldingDependencies, build_holding_feature
from backend.app.features.holdings.repository import SqlHoldingAnalysisRepository
from backend.app.features.holdings.service import HoldingAnalysisService
from backend.app.features.runs.artifacts import SqlArtifactRepository
from backend.app.features.runs.module import build_runs_feature
from backend.app.features.runs.service import RunsService
from backend.app.infrastructure.market.build import build_point_in_time_warehouse
from backend.app.infrastructure.market.provider_source import ProviderResearchSource
from backend.app.infrastructure.market.research_providers import (
    AkShareDailyBarProvider,
    BaoStockDailyBarProvider,
    FallbackDailyBarProvider,
)
from backend.app.infrastructure.persistence.database import (
    build_engine,
    build_session_factory,
)
from backend.app.infrastructure.persistence.portfolio_repository import (
    SessionScopedPortfolioReader,
    SqlPortfolioEventStore,
)
from backend.app.ports.point_in_time import PointInTimeWarehouse
from backend.app.ports.strategy import StrategyDecisionPort


@dataclass(frozen=True)
class ApplicationComponents:
    features: tuple[FeatureModule, ...]
    strategy_engine: V212StrategyEngine
    warehouse: PointInTimeWarehouse


@dataclass(frozen=True)
class FeatureServices:
    runs: RunsService
    candidate_dependencies: CandidateDependencies
    holding_dependencies: HoldingDependencies
    backtest_dependencies: BacktestDependencies


def build_feature_services(
    settings: Settings,
    sessions: sessionmaker[Session],
    warehouse: PointInTimeWarehouse,
    trading_days: BacktestTradingDayPort,
    strategy: StrategyDecisionPort,
) -> FeatureServices:
    clock = SystemClock()
    input_builder = StrategyInputBuilder()
    runs = RunsService(sessions)
    portfolio_reader = SessionScopedPortfolioReader(sessions)
    portfolio_writer = AuditedPortfolioWriter(SqlPortfolioEventStore(sessions))
    artifacts = SqlArtifactRepository(sessions, settings.artifact_root)
    candidate_repository = SqlCandidateRepository(sessions)
    candidate_service = CandidateService(
        warehouse,
        portfolio_reader,
        input_builder,
        strategy,
        candidate_repository,
    )
    candidate_handler = CandidateJobHandler(candidate_service)
    holding_repository = SqlHoldingAnalysisRepository(sessions)
    holding_service = HoldingAnalysisService(
        warehouse,
        portfolio_reader,
        input_builder,
        strategy,
        holding_repository,
    )
    holding_handler = HoldingAnalysisJobHandler(holding_service)
    backtest_decision = V212BacktestDecisionAdapter(input_builder, strategy)
    return FeatureServices(
        runs=runs,
        candidate_dependencies=CandidateDependencies(
            runs,
            candidate_repository,
            clock,
            input_builder,
            candidate_handler,
        ),
        holding_dependencies=HoldingDependencies(
            runs,
            holding_repository,
            portfolio_reader,
            portfolio_writer,
            clock,
            input_builder,
            holding_handler,
        ),
        backtest_dependencies=build_backtest_dependencies(
            sessions,
            warehouse,
            trading_days,
            backtest_decision,
            ExecutionSimulator(),
            artifacts,
            clock,
        ),
    )


def build_components(
    settings: Settings,
    trading_days: BacktestTradingDayPort,
) -> ApplicationComponents:
    engine = build_engine(settings.database_url)
    sessions = build_session_factory(engine)
    strategy = V212StrategyEngine()
    daily_bars = FallbackDailyBarProvider(
        primary=AkShareDailyBarProvider(),
        fallback=BaoStockDailyBarProvider(),
    )
    source = ProviderResearchSource(daily_bars, ZoneInfo(settings.timezone))
    warehouse = build_point_in_time_warehouse(research_sources=(source,))
    services = build_feature_services(settings, sessions, warehouse, trading_days, strategy)
    features = (
        build_runs_feature(services.runs),
        build_candidate_feature(services.candidate_dependencies),
        build_holding_feature(services.holding_dependencies),
        build_backtest_feature(services.backtest_dependencies),
    )
    return ApplicationComponents(features, strategy, warehouse)
```

`backtest_decision.py` is the only order-producing adapter around the shared evaluation. It implements
`BacktestDecisionPort.decide(context)` with this fixed pipeline:

```text
PortfolioLedger.to_portfolio_snapshot(as_of_time)
→ StrategyInputBuilder.build(snapshot, portfolio, strategy_version)
→ V212StrategyEngine.evaluate(request)
→ holdings.priority + holdings.strategy_projection
→ candidates.state_machine + candidates.strategy_projection
→ OrderIntent tuple sorted by (priority, security_id)
```

The implementation uses the 04 bridge and feature projections directly:

```python
# backend/app/bootstrap/backtest_decision.py
from decimal import Decimal
from hashlib import sha256

from backend.app.core.market.strategy_inputs import StrategyInputBuilder
from backend.app.features.backtests.models import OrderIntent, OrderSide
from backend.app.features.backtests.ports import (
    BacktestDecision,
    BacktestDecisionContext,
    BacktestDecisionPort,
)
from backend.app.features.candidates.models import CandidateBucket, CandidateState
from backend.app.features.candidates.strategy_projection import project_security
from backend.app.features.holdings.models import AdviceAction, HoldingAdviceItem
from backend.app.features.holdings.strategy_projection import project_holding
from backend.app.ports.strategy import StrategyDecisionPort


def _order_id(context: BacktestDecisionContext, security_id: str, side: OrderSide) -> str:
    raw = f"{context.group.value}|{context.as_of_time.date()}|{security_id}|{side.value}"
    return sha256(raw.encode("utf-8")).hexdigest()[:24]


def _exit_priority(item: HoldingAdviceItem) -> int:
    codes = {code.value for code in item.reason_codes}
    if "FINANCIAL_RED_FLAG" in codes or "DELISTING_RISK" in codes:
        return 1
    if "HARD_STOP_TRIGGERED" in codes:
        return 2
    if item.advised_action is AdviceAction.REDUCE_HALF:
        return 3
    if "RANK_EXIT" in codes or "DYNAMIC_REPLACEMENT" in codes:
        return 5
    return 4


class V212BacktestDecisionAdapter(BacktestDecisionPort):
    def __init__(
        self,
        input_builder: StrategyInputBuilder,
        strategy: StrategyDecisionPort,
    ) -> None:
        self._input_builder = input_builder
        self._strategy = strategy

    def decide(self, context: BacktestDecisionContext) -> BacktestDecision:
        request = self._input_builder.build(
            snapshot=context.snapshot,
            portfolio=context.portfolio,
            strategy_version=context.strategy_version,
        )
        evaluation = self._strategy.evaluate(request)
        by_security = {item.security_id: item for item in evaluation.securities}
        intents: list[OrderIntent] = []

        for position in context.portfolio.positions:
            item = project_holding(position, by_security[position.security_id])
            if item.planned_quantity <= 0:
                continue
            intents.append(
                OrderIntent(
                    order_id=_order_id(context, item.security_id, OrderSide.SELL),
                    security_id=item.security_id,
                    side=OrderSide.SELL,
                    quantity=item.planned_quantity,
                    signal_date=context.as_of_time.date(),
                    earliest_trade_date=context.next_trade_date,
                    strategy_book=item.strategy_book.value if item.strategy_book else "legacy",
                    priority=_exit_priority(item),
                    reason_codes=tuple(code.value for code in item.reason_codes),
                    signal_close=item.close,
                    stop_price=item.proposed_effective_stop,
                )
            )

        next_states = dict(context.candidate_states)
        for security in evaluation.securities:
            previous = CandidateState(
                context.candidate_states.get(security.security_id, CandidateState.UNSELECTED.value)
            )
            item = project_security(security, previous)
            next_states[item.security_id] = item.state.value
            if (
                item.bucket is not CandidateBucket.EXECUTABLE
                or item.planned_quantity <= 0
                or item.strategy_book is None
            ):
                continue
            intents.append(
                OrderIntent(
                    order_id=_order_id(context, item.security_id, OrderSide.BUY),
                    security_id=item.security_id,
                    side=OrderSide.BUY,
                    quantity=item.planned_quantity,
                    signal_date=context.as_of_time.date(),
                    earliest_trade_date=context.next_trade_date,
                    strategy_book=item.strategy_book.value,
                    priority=100,
                    reason_codes=tuple(code.value for code in item.reason_codes),
                    signal_close=Decimal(str(security.close)),
                    stop_price=item.initial_stop,
                )
            )
        ordered = tuple(sorted(intents, key=lambda item: (item.priority, item.security_id)))
        return BacktestDecision(ordered, next_states)
```

It maps `OrderIntent` exactly as follows: red light/delisting priority 1, hard stop 2,
market/portfolio reduction 3, book exit 4, rank/replacement 5, buy 100. Sell quantity comes from
`HoldingAdviceItem.planned_quantity` and may be an odd lot; buy quantity comes from
`CandidateItem.planned_quantity` and is already 100-share rounded by shared risk logic.
`signal_date=context.as_of_time.date()`, `earliest_trade_date=context.next_trade_date`,
`signal_close` and `stop_price` come from the same security evaluation, and reason codes are copied without
translation. The adapter returns `BacktestDecision(intents, candidate_states)`，with all sell intents
before any priority-100 buy, and does not create fills.

`BacktestDecisionContext.candidate_states` is experiment-local state owned by `BacktestEngine`; the adapter
returns the next mapping after candidate transition and must not keep lifecycle state on itself.

The E2E fixture must contain one existing hard-stop position and one executable strengthened candidate so
this assertion exercises 03 exit priority and 02 lifecycle/projection, not adapter-local rules.

`build_feature_services` in the same file instantiates only concrete repositories, services and handlers
exported by plans `01`—`04`, returns a frozen `FeatureServices` dataclass, and contains no scoring,
position, execution or result-mapping logic. It injects the `PortfolioReader` and `PortfolioWriter` from
`backend.app.ports.portfolio` into holding dependencies; it never updates position rows directly.
`default_features.py` passes the injected `BacktestTradingDayPort` to
`build_components(settings, trading_days).features`.
`build_application()` and `build_worker()` pass the same injected calendar to `build_components` once each
and register the exact same
`FeatureModule.job_handlers`. Add a local-only `provider_mode: Literal["fake"] = "fake"` setting to
`Settings`; local startup must never access network providers implicitly.

- [ ] **Step 4: 验证组合顺序、重复 handler 拒绝和本地默认值**

Run: `python -m pytest backend/tests/system/test_composition.py backend/tests/system/test_backtest_decision_adapter.py backend/tests/infrastructure/tasks/test_worker.py -q`
Expected: tests PASS；同一 `RunKind` 注册两次仍抛 `ValueError`；默认 provider mode 是 `fake`，
并且不会隐式访问网络 provider。

- [ ] **Step 5: 提交组合根**

```bash
git add backend/app/bootstrap backend/tests/system/test_composition.py backend/tests/system/test_backtest_decision_adapter.py
git commit -m "feat: compose product slices without duplicating feature logic"
```

### Task 2: 把全部 ORM 纳入单一 Alembic metadata 和迁移链

**Files:**
- Create: `backend/app/bootstrap/model_registry.py`
- Create: `backend/migrations/versions/20260716_0002_feature_schema.py`
- Modify: `backend/migrations/env.py`
- Test: `backend/tests/system/test_integrated_migrations.py`

- [ ] **Step 1: 写失败的完整 schema test**

```python
# backend/tests/system/test_integrated_migrations.py
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import Engine


EXPECTED = {
    "runs",
    "run_events",
    "run_artifacts",
    "ingest_batches",
    "source_artifacts",
    "security_master_history",
    "security_status_daily",
    "trading_calendar",
    "daily_bars_raw",
    "index_daily_bars",
    "corporate_actions",
    "adjustment_factors",
    "industry_membership_history",
    "theme_mapping_versions",
    "financial_disclosures",
    "financial_facts",
    "policy_documents",
    "llm_factor_runs",
    "factor_snapshots",
    "strategy_versions",
    "strategy_input_manifests",
    "portfolios",
    "position_lots",
    "portfolio_snapshots",
    "order_intents",
    "execution_attempts",
    "fills",
    "risk_events",
    "fee_schedules",
    "trading_rule_versions",
    "legacy_import_batches",
    "legacy_raw_files",
    "legacy_position_snapshots",
    "legacy_trade_events",
    "opening_positions",
    "candidate_results",
    "candidate_items",
    "candidate_state_events",
    "holding_analysis_results",
    "holding_analysis_items",
    "backtest_runs",
    "backtest_metrics",
    "experiment_results",
}


def test_head_contains_every_feature_table(
    postgres_engine: Engine,
    monkeypatch: object,
) -> None:
    monkeypatch.setenv("DA_DATABASE_URL", str(postgres_engine.url))
    config = Config("alembic.ini")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    assert EXPECTED <= set(inspect(postgres_engine).get_table_names())
```

- [ ] **Step 2: 运行 migration test 并确认 feature tables 缺失**

Run: `python -m pytest backend/tests/system/test_integrated_migrations.py -q -m postgres`
Expected: FAIL，assertion 显示 `candidate_results`、`holding_analysis_results`、
`backtest_runs` 和 PIT/legacy tables 缺失。

- [ ] **Step 3: 显式加载全部 model modules 并 autogenerate**

```python
# backend/app/bootstrap/model_registry.py
from backend.app.infrastructure.persistence.models import Base


def load_all_models() -> None:
    from backend.app.features.backtests import db_models as backtest_models
    from backend.app.features.candidates import repository as candidate_models
    from backend.app.features.holdings import repository as holding_models
    from backend.app.infrastructure.persistence import legacy_rows
    from backend.app.infrastructure.persistence import pit_rows
    from backend.app.infrastructure.persistence import portfolio_rows

    loaded = (
        backtest_models,
        candidate_models,
        holding_models,
        legacy_rows,
        pit_rows,
        portfolio_rows,
    )
    if not loaded:
        raise RuntimeError("model registry is empty")
```

Call `load_all_models()` before assigning `target_metadata = Base.metadata` in `env.py`, then run:

```bash
DA_DATABASE_URL=postgresql+psycopg://da:da@127.0.0.1:55433/da_test \
  alembic revision --autogenerate --rev-id 20260716_0002 -m "integrate feature schemas"
```

Rename to `20260716_0002_feature_schema.py`, fix `down_revision = "20260716_0001"`, and ensure its
`upgrade()` creates exactly the tables/constraints/indexes represented by feature ORM metadata.
`downgrade()` must drop foreign-key dependants before parents. Do not hand-edit feature ORM classes here.

- [ ] **Step 4: 验证 clean upgrade、downgrade 和 no-schema-diff**

Run: `python -m pytest backend/tests/system/test_integrated_migrations.py -q -m postgres && DA_DATABASE_URL=postgresql+psycopg://da:da@127.0.0.1:55433/da_test alembic check`
Expected: test PASS；`alembic check` 输出 `No new upgrade operations detected.`。

- [ ] **Step 5: 提交集成迁移**

```bash
git add backend/app/bootstrap/model_registry.py backend/migrations backend/tests/system/test_integrated_migrations.py
git commit -m "feat: migrate all feature data through one ordered schema chain"
```

### Task 3: 验证统一 202 API、Location、幂等和结果查询契约

**Files:**
- Create: `backend/tests/system/test_api_contracts.py`
- Modify: `backend/app/bootstrap/application.py`
- Modify: `contracts/openapi.json`
- Modify: `web/src/generated/schema.d.ts`

- [ ] **Step 1: 写全功能失败的 API contract test**

```python
# backend/tests/system/test_api_contracts.py
import pytest
from fastapi.testclient import TestClient

CREATE_CASES = (
    ("/api/v1/candidate-recommendations", {"as_of_time": "2026-07-16T15:00:00+08:00"}),
    ("/api/v1/holding-analyses", {"as_of_time": "2026-07-16T15:00:00+08:00"}),
    (
        "/api/v1/backtests",
        {
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
            "initial_cash": 150000,
        },
    ),
)


@pytest.mark.parametrize(("path", "payload"), CREATE_CASES)
def test_creators_return_202_location_and_idempotent_run(
    integrated_client: TestClient,
    path: str,
    payload: dict[str, object],
) -> None:
    headers = {"Idempotency-Key": f"contract-{path}"}
    first = integrated_client.post(path, json=payload, headers=headers)
    second = integrated_client.post(path, json=payload, headers=headers)

    assert first.status_code == 202
    assert first.headers["location"] == first.json()["links"]["self"]
    assert first.json()["run_id"] == second.json()["run_id"]
    assert first.json()["status"] == "queued"


def test_position_correction_maps_optimistic_conflict_to_409(
    integrated_client: TestClient,
) -> None:
    seed_portfolio_version(portfolio_id="default", version=1)
    response = integrated_client.put(
        "/api/v1/portfolio/positions",
        json={
            "portfolio_id": "default",
            "expected_version": 0,
            "reason": "人工核对券商对账单",
            "positions": [
                {
                    "security_id": "000001.SZ",
                    "quantity": 100,
                    "average_cost": "10.20",
                    "effective_at": "2026-07-16T15:30:00+08:00",
                }
            ],
        },
    )
    assert response.status_code == 409
    assert response.json() == {
        "code": "PORTFOLIO_VERSION_CONFLICT",
        "message": "portfolio version conflict",
        "request_id": response.headers["x-request-id"],
        "details": {"expected_version": 0, "current_version": 1},
    }


```

- [ ] **Step 2: 运行 test 并记录每个不合约响应**

Run: `python -m pytest backend/tests/system/test_api_contracts.py -q`
Expected: FAIL；失败只来自未接线 route、非 202、缺 Location 或不同 run id。

- [ ] **Step 3: 在组合层补齐公共 HTTP 行为并重新生成契约**

Feature creators already own `202 + Location` through their frozen contracts. If this test finds a
feature-specific mismatch, return the failure to that feature owner and merge its contract correction before
continuing; do not implement a second creator in `bootstrap`. Add shared exception mappings only:
`RequestValidationError` → 422 `VALIDATION_ERROR` and the portfolio writer's optimistic conflict →
409 `PORTFOLIO_VERSION_CONFLICT`，both using `ErrorResponse` and request id. A strict request is routed
only through `build_strict_pit_warehouse(session=..., audit_report=PassedAuditReport,
authorizer=PitAuditAuthorizer)` and `PitPromotionAuthorizer.assert_authorized` from plan 05; raw
`data_grade`, certificate strings or request flags can never construct a strict warehouse. Missing passed
audit maps to 422 `PIT_AUDIT_REQUIRED`. Then regenerate:

```bash
python -m tools.export_openapi
cd web
npm run generate:api
```

- [ ] **Step 4: 验证 API test、OpenAPI no-diff 和 TypeScript**

Run: `python -m pytest backend/tests/system/test_api_contracts.py backend/tests/api -q && python -m tools.check_openapi && cd web && npm run typecheck`
Expected: API tests 全部 PASS；202 responses 均包含 `Location` 且重复幂等键返回同一 `run_id`；409
响应完整匹配 `ErrorResponse` envelope；未提供已通过审计的 strict PIT 请求返回 422
`PIT_AUDIT_REQUIRED`；OpenAPI export/check 退出码为 0；TypeScript typecheck 退出码为 0 且生成文件无差异。

- [ ] **Step 5: 提交统一 HTTP 契约**

```bash
git add backend/app/bootstrap/application.py backend/tests/system/test_api_contracts.py contracts/openapi.json web/src/generated/schema.d.ts
git commit -m "feat: make every long-running API durable and contract-consistent"
```

### Task 4: 运行真实 PostgreSQL worker 的跨功能生命周期

**Files:**
- Modify: `backend/tests/system/conftest.py`
- Create: `backend/tests/system/fixtures/research_snapshot.json`
- Create: `backend/tests/system/fixtures/legacy_positions.csv`
- Create: `backend/tests/system/test_job_lifecycle.py`

- [ ] **Step 1: 写失败的 queued—running—succeeded 生命周期 test**

```python
# backend/tests/system/test_job_lifecycle.py
import pytest


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("path", "result_path"),
    (
        ("/api/v1/candidate-recommendations", "/api/v1/candidate-recommendations/{run_id}"),
        ("/api/v1/holding-analyses", "/api/v1/holding-analyses/{run_id}"),
        ("/api/v1/backtests", "/api/v1/backtests/{run_id}"),
    ),
)
def test_persisted_worker_completes_each_feature(
    integrated_harness: object,
    path: str,
    result_path: str,
) -> None:
    response = integrated_harness.client.post(
        path,
        json=integrated_harness.payload_for(path),
        headers={"Idempotency-Key": f"lifecycle-{path}"},
    )
    run_id = response.json()["run_id"]
    assert integrated_harness.client.get(f"/api/v1/runs/{run_id}").json()["status"] == "queued"

    assert integrated_harness.worker.run_once() is True

    detail = integrated_harness.client.get(f"/api/v1/runs/{run_id}").json()
    result = integrated_harness.client.get(result_path.format(run_id=run_id))
    assert detail["status"] == "succeeded"
    assert detail["progress"] == 100
    assert result.status_code == 200
    assert result.json()["run_id"] == run_id
```

- [ ] **Step 2: 运行 test 并确认至少一个 handler 未真实接线**

Run: `python -m pytest backend/tests/system/test_job_lifecycle.py -q -m postgres`
Expected: FAIL；错误指出未注册 handler、结果未持久化或 run 未进入 succeeded。

- [ ] **Step 3: 建立冻结 fake harness 并只修组合依赖**

`research_snapshot.json` contains one Shanghai trade day, two securities, one index, industry membership,
financial facts with `available_at <= as_of_time`, one policy document and a frozen LLM factor. Every
record contains `source_id`, `observed_at`, `available_at` and `content_hash`. One security passes V2.12
and one has `FINANCIAL_RED_FLAG`. The backtest extension adds one existing hard-stop position and one
strengthened executable candidate; the persisted intent audit must record priority 2 sell before priority 100
buy. `legacy_positions.csv` contains:

```csv
security_id,name,quantity,cost_price,buy_date
600000.SH,浦发银行,100,10.00,2026-07-15
```

`system/conftest.py` must:

1. clean and migrate PostgreSQL to head for each test session;
2. create `Settings(environment="test", provider_mode="fake")`;
3. build the local composition root with only adapter constructors replaced by frozen fake providers;
4. expose a TestClient and Worker sharing the same database;
5. return exact valid payloads for all three create routes;
6. assert fake providers never open network sockets.

Fix only dependency construction, transaction boundaries and handler registration discovered by the test.
Do not add conditional scoring or feature result transformations to `bootstrap`.

- [ ] **Step 4: 验证生命周期、重启和幂等重放**

Run: `for i in 1 2; do python -m pytest backend/tests/system/test_job_lifecycle.py -q -m postgres || exit 1; done`
Expected: both repetitions PASS；新建 Client/Worker 后仍能查询第一轮结果；相同 key 不生成第二份
账本事件或结果；backtest intent audit 每次均为 sell priority 2 then buy priority 100。

- [ ] **Step 5: 提交系统 harness 和接线**

```bash
git add backend/app/bootstrap backend/tests/system
git commit -m "test: prove every product job survives the persisted worker path"
```

### Task 5: 接入全局 Web 导航、总览和生成客户端

**Files:**
- Create: `web/src/features/overview/OverviewPage.tsx`
- Create: `web/src/features/overview/index.tsx`
- Create: `web/src/features/overview/OverviewPage.test.tsx`
- Modify: `web/src/app/defaultFeatures.tsx`
- Modify: `web/src/app/App.test.tsx`

- [ ] **Step 1: 写失败的五页导航和可信度总览 test**

```tsx
// web/src/features/overview/OverviewPage.test.tsx
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { OverviewPage } from "./OverviewPage";

it("shows health, strategy and trust grades without performance claims", async () => {
  const load = vi.fn().mockResolvedValue({
    strategyVersion: "v2.12",
    dataGrade: "research",
    llmGrade: "reconstructed",
    api: "ready",
    worker: "ready",
    database: "ready",
  });
  render(<OverviewPage load={load} />);

  expect(await screen.findByText("研究级数据")).toBeInTheDocument();
  expect(screen.getByText("历史重建 LLM")).toBeInTheDocument();
  expect(screen.getByText("v2.12")).toBeInTheDocument();
  expect(screen.queryByText(/策略已验证有效/)).not.toBeInTheDocument();
});
```

Extend `App.test.tsx` to assert links for `总览`、`候选推荐`、`持仓分析`、`历史回测` and
`运行中心`.

- [ ] **Step 2: 运行 test 并确认 overview/注册缺失**

Run: `cd web && npm test -- --run src/features/overview/OverviewPage.test.tsx src/app/App.test.tsx`
Expected: FAIL，包含 `Failed to resolve import "./OverviewPage"` 或缺少导航 link。

- [ ] **Step 3: 实现 overview projection 并注册既有 features**

```tsx
// web/src/features/overview/index.tsx
import type { FeatureDefinition } from "../../app/featureRegistry";
import { OverviewPage } from "./OverviewPage";

export const overviewFeature: FeatureDefinition = {
  id: "overview",
  path: "/overview",
  label: "总览",
  element: <OverviewPage />,
};
```

```tsx
// web/src/app/defaultFeatures.tsx
import { backtestsFeature } from "../features/backtests";
import { candidateFeature } from "../features/candidates";
import { holdingFeature } from "../features/holdings";
import { overviewFeature } from "../features/overview";
import { runsFeature } from "../features/runs";

export const defaultFeatures = [
  overviewFeature,
  candidateFeature,
  holdingFeature,
  backtestsFeature,
  runsFeature,
] as const;
```

`OverviewPage` uses only `web/src/shared/api/client.ts` generated operations to load health, latest runs,
strategy version and portfolio risk. It maps `research` to `研究级数据`,
`pit_verified` to `PIT 已验证数据`, `reconstructed` to `历史重建 LLM` and
`forward_observed` to `前瞻冻结 LLM`. API errors render a stable retry state and request id.

- [ ] **Step 4: 运行全部 Web tests、typecheck 和 build**

Run: `cd web && npm test -- --run && npm run typecheck && npm run build`
Expected: tests PASS，TypeScript 零错误，local Web build 成功。

- [ ] **Step 5: 提交全局 Web 接线**

```bash
git add web/src/app web/src/features/overview
git commit -m "feat: connect all product slices through one trustworthy dashboard"
```

### Task 6: 用 Playwright 覆盖四项用户关键路径

**Files:**
- Create: `web/playwright.config.ts`
- Create: `web/e2e/product-flow.spec.ts`
- Create: `tools/start_e2e_stack.sh`
- Modify: `web/package.json`
- Modify: `tools/start_e2e_stack.sh`

- [ ] **Step 1: 写失败的浏览器端到端 test**

```typescript
// web/e2e/product-flow.spec.ts
import { expect, test } from "@playwright/test";

test("candidate, holding, backtest and run center share persisted jobs", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("研究级数据")).toBeVisible();

  await page.getByRole("link", { name: "候选推荐" }).click();
  await page.getByRole("button", { name: "发起候选推荐" }).click();
  await expect(page.getByText("已完成")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("FINANCIAL_RED_FLAG")).toBeVisible();

  await page.getByRole("link", { name: "持仓分析" }).click();
  await page.getByRole("button", { name: "发起持仓分析" }).click();
  await expect(page.getByText("人工确认")).toBeVisible({ timeout: 20_000 });

  await page.getByRole("link", { name: "历史回测" }).click();
  await page.getByLabel("开始日期").fill("2025-01-01");
  await page.getByLabel("结束日期").fill("2025-12-31");
  await page.getByRole("button", { name: "运行研究级回测" }).click();
  await expect(page.getByText("data_grade: research")).toBeVisible({ timeout: 30_000 });

  await page.getByRole("link", { name: "运行中心" }).click();
  await expect(page.getByRole("row", { name: /candidate_recommendation.*succeeded/ })).toBeVisible();
  await expect(page.getByRole("row", { name: /holding_analysis.*succeeded/ })).toBeVisible();
  await expect(page.getByRole("row", { name: /backtest.*succeeded/ })).toBeVisible();
});
```

- [ ] **Step 2: 安装 Playwright 并确认 E2E 配置缺失**

Run: `cd web && npm install -D @playwright/test@^1.47.2 && npx playwright install chromium && npm run e2e`
Expected: FAIL，包含 `Missing script: "e2e"`。

- [ ] **Step 3: 实现隔离的 E2E stack**

Add `"e2e": "playwright test"` to `package.json`. `playwright.config.ts` uses
`baseURL: "http://127.0.0.1:5173"`, one Chromium project, trace on first retry, and:

```typescript
webServer: {
  command: "bash ../tools/start_e2e_stack.sh",
  url: "http://127.0.0.1:5173",
  reuseExistingServer: false,
  timeout: 120_000,
}
```

```bash
#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
export DA_ENVIRONMENT=test
export DA_PROVIDER_MODE=fake
export DA_DATABASE_URL=postgresql+psycopg://da:da@127.0.0.1:5432/da_test
alembic downgrade base
alembic upgrade head
da-api &
api_pid=$!
da-worker &
worker_pid=$!
cd "$root/web"
npm run dev -- --host 127.0.0.1 &
web_pid=$!
trap 'kill "$api_pid" "$worker_pid" "$web_pid" 2>/dev/null || true' EXIT
wait "$web_pid"
```

Ensure the local PostgreSQL service is healthy before the script. The fake mode reads only checked-in system fixtures;
it never calls AkShare, BaoStock, policy sites or an LLM endpoint.

- [ ] **Step 4: 运行 Chromium E2E 两次验证确定性**

Run: `pg_isready -h 127.0.0.1 -p 5432 && cd web && npm run e2e && npm run e2e`
Expected: both runs PASS；每次三类 job 均 succeeded，backtest 始终显示 research/reconstructed。

- [ ] **Step 5: 提交关键路径 E2E**

```bash
git add web/package.json web/package-lock.json web/playwright.config.ts web/e2e tools/start_e2e_stack.sh
git commit -m "test: exercise all four product capabilities through the browser"
```

### Task 7: 执行本地安全边界和日志最小化

**Files:**
- Create: `backend/app/bootstrap/security.py`
- Create: `backend/app/infrastructure/logging.py`
- Create: `backend/tests/security/test_startup_policy.py`
- Create: `backend/tests/security/test_artifact_paths.py`
- Create: `backend/tests/security/test_api_boundaries.py`
- Modify: `backend/app/bootstrap/settings.py`
- Modify: `backend/app/bootstrap/application.py`

- [ ] **Step 1: 写失败的 host、path traversal、SQL injection 和日志 test**

```python
# backend/tests/security/test_startup_policy.py
import pytest
from pydantic import ValidationError

from backend.app.bootstrap.settings import Settings


@pytest.mark.parametrize("authentication_enabled", (False, True))
def test_local_startup_rejects_non_loopback(authentication_enabled: bool) -> None:
    with pytest.raises(ValidationError, match="non-loopback"):
        Settings(
            _env_file=None,
            bind_host="0.0.0.0",
            authentication_enabled=authentication_enabled,
        )


def test_wildcard_cors_is_rejected() -> None:
    with pytest.raises(ValidationError, match="wildcard"):
        Settings(_env_file=None, allowed_origins=("*",))
```

```python
# backend/tests/security/test_artifact_paths.py
from pathlib import Path

import pytest

from backend.app.infrastructure.persistence.artifact_paths import UnsafeArtifactPath, resolve_artifact


def test_artifact_path_cannot_escape_root(tmp_path: Path) -> None:
    with pytest.raises(UnsafeArtifactPath):
        resolve_artifact(tmp_path / "artifacts", "../../.env")
```

```python
# backend/tests/security/test_api_boundaries.py
def test_sql_text_in_run_id_is_data_and_logs_omit_payload(
    integrated_client: object,
    caplog: object,
) -> None:
    response = integrated_client.get("/api/v1/runs/x%27%20OR%201%3D1--")
    assert response.status_code == 404
    joined = "\n".join(record.message for record in caplog.records)
    assert "cost_price" not in joined
    assert "DEEPSEEK_API_KEY" not in joined
    assert "request_payload" not in joined
```

- [ ] **Step 2: 运行安全 tests 并确认边界未实现**

Run: `python -m pytest backend/tests/security -q`
Expected: FAIL；非 loopback 设置被接受，path traversal 未拒绝，或日志包含禁止字段。

- [ ] **Step 3: 实现 fail-fast startup、受限产物路径和结构化日志**

```python
# backend/app/bootstrap/security.py
from ipaddress import ip_address


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def validate_security(
    bind_host: str,
    authentication_enabled: bool,
    allowed_origins: tuple[str, ...],
) -> None:
    if not is_loopback(bind_host):
        suffix = "configured auth is not implemented" if authentication_enabled else "auth is required"
        raise ValueError(f"non-loopback binding rejected: {suffix}")
    if "*" in allowed_origins:
        raise ValueError("wildcard CORS origin is forbidden")
```

Call `validate_security` from a `Settings.model_validator(mode="after")`. The local test system has no remote
authentication subsystem, so even `authentication_enabled=true` cannot bypass this guard. Keep CORS
`allow_credentials=False` and methods limited to GET/POST/PUT.

`infrastructure/logging.py` configures one JSON line per request with only
`timestamp`, `level`, `request_id`, `method`, `path_template`, `status_code`, `run_id`,
`event_code` and hashes. It never serializes headers, body, provider raw text, position notes or environment.
Replace any `str(exc)` response with stable error code and generic user message; stack traces stay server-side.
All SQL remains SQLAlchemy expression language or `text()` with named parameters.

- [ ] **Step 4: 运行安全 suite 和敏感字符串扫描**

Run: `python -m pytest backend/tests/security -q && ! rg -n "allow_origins=\\[\"\\*\"\\]|log.*request_payload|print\\(.*API_KEY" backend`
Expected: tests PASS，`rg` 无匹配。

- [ ] **Step 5: 提交安全边界**

```bash
git add backend/app/bootstrap backend/app/infrastructure backend/tests/security
git commit -m "fix: fail closed at DA network, artifact, SQL, and logging boundaries"
```

### Task 8: 增加 readiness、worker lease 和本地恢复 runbook

**Files:**
- Create: `backend/app/infrastructure/tasks/health.py`
- Create: `backend/app/infrastructure/tasks/db_models.py`
- Create: `backend/migrations/versions/20260716_0003_worker_lease.py`
- Create: `backend/tests/operations/test_readiness.py`
- Create: `docs/runbook.md`
- Modify: `backend/app/infrastructure/tasks/worker.py`
- Modify: `backend/app/bootstrap/application.py`
- Modify: `backend/app/bootstrap/model_registry.py`

- [ ] **Step 1: 写失败的 component readiness test**

```python
# backend/tests/operations/test_readiness.py
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def test_ready_requires_database_and_recent_worker(
    operational_client: object,
    worker_health: object,
) -> None:
    now = datetime(2026, 7, 16, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    worker_health.touch("worker-1", now)
    ready = operational_client.get("/api/v1/health/ready")
    assert ready.status_code == 200
    assert ready.json() == {
        "status": "ready",
        "components": {"database": "ready", "worker": "ready"},
    }

    worker_health.touch("worker-1", now - timedelta(minutes=5))
    stale = operational_client.get("/api/v1/health/ready")
    assert stale.status_code == 503
    assert stale.json()["components"]["worker"] == "stale"
```

- [ ] **Step 2: 运行 test 并确认 readiness/lease 缺失**

Run: `python -m pytest backend/tests/operations/test_readiness.py -q -m postgres`
Expected: FAIL，`/api/v1/health/ready` 为 404 或没有 worker component。

- [ ] **Step 3: 实现 persistent worker lease 和本地启动顺序**

```python
# backend/app/infrastructure/tasks/db_models.py
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.infrastructure.persistence.models import Base


class WorkerLeaseRow(Base):
    __tablename__ = "worker_leases"
    worker_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
```

`health.py` defines `WorkerHealth.touch(worker_id, now)` as PostgreSQL upsert and
`WorkerHealth.status(now, stale_after_seconds) -> Literal["ready", "missing", "stale"]`.
Worker calls `touch` before each claim and after each handler. The API readiness dependency runs
`SELECT 1` and checks the most recent lease. Add
`from backend.app.infrastructure.tasks import db_models as worker_models` to `load_all_models()` and include
`worker_models` in its loaded tuple before generating:

```bash
DA_DATABASE_URL=postgresql+psycopg://da:da@127.0.0.1:5432/da_test \
  alembic revision --autogenerate --rev-id 20260716_0003 -m "add worker lease"
```

Set `down_revision = "20260716_0002"`. API and Web are started directly by local commands and bind only
to loopback. Secrets enter only through environment variables. `docs/runbook.md` gives exact local start,
stop, migration, health, stale-worker restart, database backup and artifact-hash verification commands.

- [ ] **Step 4: 验证 readiness 和 health**

Run: `TEST_DATABASE_URL=postgresql+psycopg://da:da@127.0.0.1:5432/da_test python -m pytest backend/tests/operations/test_readiness.py -q -m postgres && curl -fsS http://127.0.0.1:8000/api/v1/health/ready`
Expected: test PASS，curl JSON 为 `status=ready`。

- [ ] **Step 5: 提交运维边界**

```bash
git add backend/app/infrastructure/tasks backend/app/bootstrap/application.py backend/migrations backend/tests/operations docs/runbook.md
git commit -m "feat: make DA startup order and worker health observable"
```

### Task 9: 执行独立性、legacy 冻结导入和本地验收

**Files:**
- Create: `tools/audit_release.py`
- Create: `docs/local-acceptance-checklist.md`
- Test: `backend/tests/system/test_release_audit.py`

- [ ] **Step 1: 写失败的本地审计 test**

```python
# backend/tests/system/test_release_audit.py
from pathlib import Path

from tools.audit_release import audit_repository


def test_local_audit_proves_independence_and_labels() -> None:
    findings = audit_repository(Path("."))
    assert findings == []
    assert "research" in Path("contracts/openapi.json").read_text(encoding="utf-8")
    assert "pit_verified" in Path("contracts/openapi.json").read_text(encoding="utf-8")
```

- [ ] **Step 2: 运行本地审计 test 并确认工具缺失**

Run: `python -m pytest backend/tests/system/test_release_audit.py -q`
Expected: FAIL，包含 `No module named 'tools.audit_release'`。

- [ ] **Step 3: 实现本地审计并执行一次冻结 legacy 导入**

```python
# tools/audit_release.py
from pathlib import Path

RUNTIME_ROOTS = ("backend", "web/src", "strategies", "contracts")
FORBIDDEN = ("/Users/bujiatang/workspace/LA", "../LA/", "PYTHONPATH")


def audit_repository(root: Path) -> list[str]:
    findings: list[str] = []
    for relative in RUNTIME_ROOTS:
        for path in (root / relative).rglob("*"):
            if path.is_symlink():
                findings.append(f"symlink:{path}")
            elif path.is_file():
                text = path.read_text(encoding="utf-8", errors="ignore")
                findings.extend(f"reference:{path}:{item}" for item in FORBIDDEN if item in text)
    return findings


def main() -> None:
    findings = audit_repository(Path("."))
    if findings:
        raise SystemExit("\n".join(findings))


if __name__ == "__main__":
    main()
```

After backing up DA PostgreSQL, execute the user-authorized one-time read-only import:

```bash
python -m backend.app.features.legacy_import.cli \
  --source-root /Users/bujiatang/workspace/LA \
  --effective-at 2026-07-17T00:00:00+08:00 \
  --portfolio-id default \
  --imports-root data/imports
```

Expected: one batch with `origin=legacy_opening_balance`; raw bytes copied under
`data/imports/<batch_id>/raw/`; quality report contains discovered
`missing_archive`, `checksum_mismatch`, `unindexed_file` and
`buy_date_after_snapshot` when present; no source file mtime/hash changes. Re-run the exact command and
assert it returns the same batch id and creates no duplicate opening positions.

`local-acceptance-checklist.md` requires recorded evidence for local pytest, Playwright, migrations,
OpenAPI no-diff, security suite, local health, legacy quality report and the four-feature browser flow.
Backtest evidence is labeled as research capability; strategy effectiveness is not claimed without
`pit_verified` evidence and V2.12 sample-out thresholds.

- [ ] **Step 4: 运行最终 no-LA-context 和全量本地验收**

Run:

```bash
python -m tools.audit_release
TEST_DATABASE_URL=postgresql+psycopg://da:da@127.0.0.1:5432/da_test make verify
python -m pytest backend/tests/security backend/tests/system backend/tests/operations -q
cd web && npm run e2e
cd ..
python -m tools.check_openapi
git diff --exit-code
```

Expected: 全部退出 0；工作树无生成差异；research 与 PIT/LLM grades 在 API、Web 和导出报告中保留。

- [ ] **Step 5: 提交本地验收证据**

Record the local PostgreSQL-backed system/security tests, Playwright Chromium, independence audit and
generated-file checks. No Docker build or production secret is required.

```bash
git add tools/audit_release.py docs/local-acceptance-checklist.md backend/tests/system/test_release_audit.py
git commit -m "chore: record DA local acceptance evidence"
```

## 本地验收门槛

- Web 可以发起/查看候选、持仓和回测，并在运行中心看到跨重启保存的状态与产物。
- research 结果始终显示 `data_grade=research`；只有 `05` 的毒丸审计全部通过才显示
  `pit_verified`；LLM grade 独立展示。
- V2.12 共享公式只有 `core/strategy` 一份，backtest 与实时功能注入同一
  `StrategyDecisionPort`。
- 默认 API/Web 只监听 loopback；非 loopback 且未配置认证时启动失败。
- 日志不含密钥、完整 LLM 原文、请求 payload、持仓备注或 PII。
- legacy batch 保留原始字节、SHA-256、来源和质量标签，只从
  `effective_at` 起作为 `legacy_opening_balance`。
- 本地 PostgreSQL、Playwright、迁移 no-diff、OpenAPI no-diff 和独立性审计均通过。
