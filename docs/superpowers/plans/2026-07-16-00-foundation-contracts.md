# DA Foundation and Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立独立 DA 工程基线、冻结 V2.12 与共享契约、PostgreSQL 持久任务系统、OpenAPI 生成链路和可注册 Web 壳。

**Architecture:** FastAPI、Pydantic v2、SQLAlchemy 2 和 Alembic 组成后端；长任务先写 PostgreSQL，再由独立 worker 使用 `FOR UPDATE SKIP LOCKED` 领取。React/Vite 前端与后端都通过窄 feature 接口注册，功能 Agent 不修改全局入口。

**Tech Stack:** Python 3.11、FastAPI、Pydantic v2、SQLAlchemy 2、Alembic、PostgreSQL 16、pytest、React 18、TypeScript、Vite、Vitest、OpenAPI TypeScript

---

## 执行边界与文件地图

- 本计划是 `01`—`05` 的阻塞依赖，必须先合入。
- 协调 Agent 独占根配置、`contracts/**`、`main.py`、默认 feature 列表、Alembic 迁移链和
  `web/src/app/**`；功能 Agent 只导出注册对象。
- Task 2 从 LA 复制策略是一次性构建动作。此后 runtime、测试、部署都只读取 DA。
- PostgreSQL 测试 URL：
  `postgresql+psycopg://da:da@127.0.0.1:55433/da_test`。

```text
backend/app/contracts/                  稳定枚举与 API envelope
backend/app/core/strategy/              DA 内冻结策略 registry
backend/app/infrastructure/persistence/ 数据库和 ORM
backend/app/infrastructure/tasks/       handler registry 与 worker
backend/app/features/runs/              持久任务 API
backend/app/bootstrap/                  配置、应用工厂、默认 feature
web/src/app/                            壳、导航、Web feature contract
contracts/                              OpenAPI 与固定示例
```

### Task 1: 初始化 Python、PostgreSQL 与测试基线

**Files:**
- Create: `.gitignore`
- Create: `.python-version`
- Create: `.env.example`
- Create: `pyproject.toml`
- Create: `compose.yaml`
- Create: `backend/__init__.py`
- Create: `backend/app/__init__.py`
- Create: `backend/app/bootstrap/__init__.py`
- Create: `backend/app/bootstrap/settings.py`
- Create: `backend/tests/conftest.py`
- Test: `backend/tests/test_project_baseline.py`

- [ ] **Step 1: 写失败的独立配置测试**

```python
# backend/tests/test_project_baseline.py
from pathlib import Path

from backend.app.bootstrap.settings import Settings


def test_defaults_are_local_and_do_not_reference_la() -> None:
    settings = Settings(_env_file=None)

    assert settings.bind_host == "127.0.0.1"
    assert settings.timezone == "Asia/Shanghai"
    assert settings.artifact_root == Path("data/artifacts")
    assert "/workspace/LA" not in settings.model_dump_json()
```

- [ ] **Step 2: 运行测试并确认因模块缺失而失败**

Run: `python -m pytest backend/tests/test_project_baseline.py -q`
Expected: FAIL，包含 `ModuleNotFoundError: No module named 'backend.app.bootstrap.settings'`。

- [ ] **Step 3: 写最小工程配置**

```toml
# pyproject.toml
[build-system]
requires = ["hatchling>=1.25"]
build-backend = "hatchling.build"

[project]
name = "da-platform"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "alembic>=1.13,<2",
  "akshare>=1.17,<2",
  "baostock>=0.8.9,<1",
  "fastapi>=0.115,<1",
  "httpx>=0.27,<1",
  "pandas>=2.2,<3",
  "pydantic-settings>=2.5,<3",
  "psycopg[binary]>=3.2,<4",
  "sqlalchemy>=2.0,<3",
  "uvicorn[standard]>=0.30,<1",
]

[project.optional-dependencies]
dev = [
  "mypy>=1.11,<2",
  "pytest>=8.3,<9",
  "pytest-cov>=5,<6",
  "ruff>=0.6,<1",
]

[project.scripts]
da-api = "backend.app.main:run"
da-worker = "backend.app.infrastructure.tasks.worker:run"

[tool.hatch.build.targets.wheel]
packages = ["backend"]

[tool.pytest.ini_options]
testpaths = ["backend/tests"]
addopts = "-ra --strict-markers"
markers = ["postgres: requires PostgreSQL"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "ANN"]

[tool.mypy]
python_version = "3.11"
strict = true
plugins = ["pydantic.mypy"]
```

```python
# backend/app/bootstrap/settings.py
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="DA_", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    bind_host: str = "127.0.0.1"
    bind_port: int = Field(default=8000, ge=1, le=65535)
    database_url: str = "postgresql+psycopg://da:da@127.0.0.1:55432/da"
    artifact_root: Path = Path("data/artifacts")
    allowed_origins: tuple[str, ...] = ("http://127.0.0.1:5173",)
    timezone: str = "Asia/Shanghai"
    authentication_enabled: bool = False
    worker_stale_after_seconds: int = Field(default=120, ge=30)
```

Write `.python-version` as `3.11`; create empty package `__init__.py` files; write:

```dotenv
# .env.example
DA_DATABASE_URL=postgresql+psycopg://da:da@127.0.0.1:55432/da
DA_BIND_HOST=127.0.0.1
DA_ALLOWED_ORIGINS=["http://127.0.0.1:5173"]
```

```yaml
# compose.yaml
services:
  postgres:
    image: postgres:16-alpine
    environment: {POSTGRES_USER: da, POSTGRES_PASSWORD: da, POSTGRES_DB: da}
    ports: ["55432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U da -d da"]
      interval: 2s
      timeout: 2s
      retries: 20
    volumes: [da-postgres:/var/lib/postgresql/data]
  postgres-test:
    image: postgres:16-alpine
    environment: {POSTGRES_USER: da, POSTGRES_PASSWORD: da, POSTGRES_DB: da_test}
    ports: ["55433:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U da -d da_test"]
      interval: 2s
      timeout: 2s
      retries: 20
volumes:
  da-postgres:
```

```python
# backend/tests/conftest.py
import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


@pytest.fixture
def postgres_engine() -> Iterator[Engine]:
    url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://da:da@127.0.0.1:55433/da_test",
    )
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("SELECT 1"))
    yield engine
    engine.dispose()
```

`.gitignore` must ignore `.env`, `.venv/`, Python caches, `data/artifacts/`,
`data/imports/`, `web/node_modules/`, `web/dist/` and Playwright output.

- [ ] **Step 4: 安装并验证配置测试**

Run: `python -m pip install -e ".[dev]" && python -m pytest backend/tests/test_project_baseline.py -q`
Expected: `1 passed`。

- [ ] **Step 5: 提交工程基线**

```bash
git add .gitignore .python-version .env.example pyproject.toml compose.yaml backend
git commit -m "build: establish an independent DA runtime baseline"
```

### Task 2: 冻结 V2.12 并建立 fail-closed registry

**Files:**
- Create: `strategies/四维盾剑v2.12.md`
- Create: `strategies/manifest.json`
- Create: `backend/app/core/__init__.py`
- Create: `backend/app/core/strategy/__init__.py`
- Create: `backend/app/core/strategy/registry.py`
- Test: `backend/tests/core/strategy/test_registry.py`

- [ ] **Step 1: 写失败的哈希校验测试**

```python
# backend/tests/core/strategy/test_registry.py
from pathlib import Path

import pytest

from backend.app.core.strategy.registry import StrategyIntegrityError, StrategyRegistry

HASH = "a88acc752be00783b9462368d57e647d0033563467e3ed5c364c7a501ca5a026"


def test_repository_strategy_matches_recorded_hash() -> None:
    loaded = StrategyRegistry.from_manifest(Path("strategies/manifest.json")).load("v2.12")
    assert loaded.sha256 == HASH
    assert loaded.path == Path("strategies/四维盾剑v2.12.md")


def test_modified_strategy_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "strategy.md"
    path.write_text("modified", encoding="utf-8")
    registry = StrategyRegistry.from_entries({"v2.12": (path, HASH)})
    with pytest.raises(StrategyIntegrityError):
        registry.load("v2.12")
```

- [ ] **Step 2: 运行测试并确认模块缺失**

Run: `python -m pytest backend/tests/core/strategy/test_registry.py -q`
Expected: FAIL，包含 `No module named 'backend.app.core.strategy'`。

- [ ] **Step 3: 执行一次性复制并实现 registry**

```bash
mkdir -p strategies
cp /Users/bujiatang/workspace/LA/手册/四维盾剑v2.12.md strategies/四维盾剑v2.12.md
shasum -a 256 strategies/四维盾剑v2.12.md
```

Expected: `a88acc752be00783b9462368d57e647d0033563467e3ed5c364c7a501ca5a026`。

```json
// strategies/manifest.json
{
  "strategies": {
    "v2.12": {
      "path": "strategies/四维盾剑v2.12.md",
      "sha256": "a88acc752be00783b9462368d57e647d0033563467e3ed5c364c7a501ca5a026",
      "source_commit": "43d8b8cb5305b09c4c9deef38e7f074a39717445",
      "source_path": "手册/四维盾剑v2.12.md",
      "copied_at": "2026-07-16T00:00:00+08:00"
    }
  }
}
```

```python
# backend/app/core/strategy/registry.py
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


class StrategyIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class FrozenStrategy:
    version: str
    path: Path
    sha256: str
    text: str


class StrategyRegistry:
    def __init__(self, entries: dict[str, tuple[Path, str]]) -> None:
        self._entries = entries

    @classmethod
    def from_entries(cls, entries: dict[str, tuple[Path, str]]) -> "StrategyRegistry":
        return cls(entries)

    @classmethod
    def from_manifest(cls, path: Path) -> "StrategyRegistry":
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            {
                version: (Path(item["path"]), item["sha256"])
                for version, item in payload["strategies"].items()
            }
        )

    def load(self, version: str) -> FrozenStrategy:
        try:
            path, expected = self._entries[version]
        except KeyError as exc:
            raise StrategyIntegrityError(f"unknown strategy version: {version}") from exc
        raw = path.read_bytes()
        actual = sha256(raw).hexdigest()
        if actual != expected:
            raise StrategyIntegrityError(
                f"strategy hash mismatch for {version}: expected {expected}, got {actual}"
            )
        return FrozenStrategy(version, path, actual, raw.decode("utf-8"))
```

Create empty package `__init__.py` files.

- [ ] **Step 4: 验证内容和 runtime 路径**

Run: `python -m pytest backend/tests/core/strategy/test_registry.py -q && ! rg -n "/Users/bujiatang/workspace/LA" backend strategies/manifest.json`
Expected: `2 passed`，`rg` 无匹配。

- [ ] **Step 5: 提交冻结策略**

```bash
git add strategies backend/app/core backend/tests/core
git commit -m "feat: freeze V2.12 so DA never reads LA at runtime"
```

### Task 3: 冻结共享 Pydantic 契约与原因码

**Files:**
- Create: `backend/app/contracts/__init__.py`
- Create: `backend/app/contracts/common.py`
- Create: `backend/app/contracts/grades.py`
- Create: `backend/app/contracts/runs.py`
- Create: `backend/app/contracts/strategy.py`
- Test: `backend/tests/contracts/test_common_contracts.py`

- [ ] **Step 1: 写失败的序列化测试**

```python
# backend/tests/contracts/test_common_contracts.py
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from backend.app.contracts.grades import DataGrade, LlmGrade
from backend.app.contracts.runs import (
    ErrorResponse,
    Page,
    RunKind,
    RunLinks,
    RunRef,
    RunStatus,
)
from backend.app.contracts.strategy import AsOf, StrategyVersion


def test_run_ref_uses_stable_values_and_aware_time() -> None:
    ref = RunRef(
        run_id="01J00000000000000000000000",
        kind=RunKind.BACKTEST,
        status=RunStatus.QUEUED,
        submitted_at=datetime(2026, 7, 16, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        links=RunLinks(self="/api/v1/runs/01J00000000000000000000000"),
    )
    assert ref.model_dump(mode="json")["kind"] == "backtest"
    assert ref.model_dump(mode="json")["submitted_at"].endswith("+08:00")


def test_envelopes_reject_naive_time() -> None:
    with pytest.raises(ValidationError):
        RunRef(
            run_id="r1",
            kind="backtest",
            status="queued",
            submitted_at=datetime(2026, 7, 16, 9, 30),
            links={"self": "/api/v1/runs/r1"},
        )
    assert DataGrade.RESEARCH == "research"
    assert LlmGrade.FORWARD_OBSERVED == "forward_observed"
    assert Page[int](items=[1], next_cursor=None).items == [1]
    assert ErrorResponse(code="BAD", message="bad", request_id="req").details == {}
    assert AsOf(as_of_time=datetime(2026, 7, 16, tzinfo=ZoneInfo("Asia/Shanghai"))).timezone == "Asia/Shanghai"
    assert StrategyVersion(
        version="v2.12",
        sha256="a" * 64,
    ).version == "v2.12"
```

- [ ] **Step 2: 运行测试并确认契约缺失**

Run: `python -m pytest backend/tests/contracts/test_common_contracts.py -q`
Expected: FAIL，包含 `No module named 'backend.app.contracts'`。

- [ ] **Step 3: 实现枚举、时间校验和 envelope**

```python
# backend/app/contracts/common.py
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware datetime required")
    return value
```

```python
# backend/app/contracts/grades.py
from enum import StrEnum


class DataGrade(StrEnum):
    RESEARCH = "research"
    PIT_VERIFIED = "pit_verified"


class LlmGrade(StrEnum):
    NOT_USED = "not_used"
    RECONSTRUCTED = "reconstructed"
    FORWARD_OBSERVED = "forward_observed"
```

```python
# backend/app/contracts/runs.py
from datetime import datetime
from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import Field, field_validator

from backend.app.contracts.common import ContractModel, require_aware

T = TypeVar("T")


class ErrorResponse(ContractModel):
    code: str
    message: str
    request_id: str
    details: dict[str, object] = Field(default_factory=dict)


class Page(ContractModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None


class RunKind(StrEnum):
    CANDIDATE_RECOMMENDATION = "candidate_recommendation"
    HOLDING_ANALYSIS = "holding_analysis"
    BACKTEST = "backtest"
    LEGACY_IMPORT = "legacy_import"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunLinks(ContractModel):
    self: str
    artifacts: str | None = None
    result: str | None = None


class RunRef(ContractModel):
    run_id: str = Field(min_length=1, max_length=64)
    kind: RunKind
    status: RunStatus
    submitted_at: datetime
    links: RunLinks

    _aware_submitted_at = field_validator("submitted_at")(require_aware)


class RunDetail(RunRef):
    stage: str | None = None
    progress: int = Field(default=0, ge=0, le=100)
    heartbeat_at: datetime | None = None
    error: dict[str, object] | None = None
```

```python
# backend/app/contracts/strategy.py
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from backend.app.contracts.common import ContractModel, require_aware
from backend.app.contracts.grades import DataGrade, LlmGrade


class StrategyVersion(ContractModel):
    version: str = Field(pattern=r"^v\\d+\\.\\d+$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AsOf(ContractModel):
    as_of_time: datetime
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    data_grade: DataGrade = DataGrade.RESEARCH
    llm_grade: LlmGrade = LlmGrade.NOT_USED

    _aware_as_of_time = field_validator("as_of_time")(require_aware)
```

`contracts/__init__.py` explicitly exports `DataGrade` and `LlmGrade` from `grades.py` and
`ErrorResponse`, `Page`, `RunDetail`, `RunKind`, `RunLinks`, `RunRef` and `RunStatus` from
`runs.py`，and `AsOf` and `StrategyVersion` from `strategy.py`. Feature code must import from these
public paths.

- [ ] **Step 4: 运行测试与 mypy**

Run: `python -m pytest backend/tests/contracts/test_common_contracts.py -q && python -m mypy backend/app/contracts`
Expected: `2 passed`，mypy 输出 `Success: no issues found`。

- [ ] **Step 5: 提交共享契约**

```bash
git add backend/app/contracts backend/tests/contracts
git commit -m "feat: freeze stable cross-feature API contracts"
```

### Task 4: 冻结共享策略类型、原因码和市场状态

**Files:**
- Create: `backend/app/core/strategy/types.py`
- Create: `backend/app/core/strategy/reason_codes.py`
- Create: `backend/app/core/strategy/market_regime.py`
- Create: `backend/app/core/clock.py`
- Create: `backend/app/ports/__init__.py`
- Create: `backend/app/ports/strategy.py`
- Test: `backend/tests/core/strategy/test_market_regime.py`

- [ ] **Step 1: 写失败的市场状态 golden tests**

```python
# backend/tests/core/strategy/test_market_regime.py
from backend.app.core.strategy.market_regime import evaluate_market_regime
from backend.app.core.strategy.types import MarketRegimeInput, MarketState


def strong_input(**changes: object) -> MarketRegimeInput:
    values: dict[str, object] = {
        "index_close": 110.0,
        "index_ma20": 105.0,
        "index_ma20_5d_ago": 103.0,
        "index_ma60": 100.0,
        "breadth": 0.66,
        "index_return_1d": 0.0,
        "index_return_20d": 0.08,
        "limit_down_count": 10,
        "portfolio_open_drawdown": 0.0,
        "portfolio_week_drawdown": 0.0,
        "portfolio_month_drawdown": 0.0,
        "week_cooldown_remaining": -1,
        "month_cooldown_remaining": -1,
        "cooldown_recovery_confirmed": True,
        "current_state": MarketState.STRONG,
        "candidate_streak": 2,
        "low_confidence": False,
    }
    values.update(changes)
    return MarketRegimeInput(**values)


def test_strong_breadth_allows_ninety_percent() -> None:
    result = evaluate_market_regime(strong_input())
    assert result.state is MarketState.STRONG
    assert result.max_exposure == 0.90
    assert result.allow_new_risk is True
    assert result.allow_swing is True


def test_low_confidence_uses_range_floor() -> None:
    result = evaluate_market_regime(strong_input(low_confidence=True))
    assert result.max_exposure == 0.70


def test_systemic_overlay_is_immediate() -> None:
    result = evaluate_market_regime(strong_input(index_return_1d=-0.041))
    assert result.allow_new_risk is False


def test_week_cooldown_persists_after_trigger_day() -> None:
    result = evaluate_market_regime(
        strong_input(
            portfolio_week_drawdown=0.0,
            week_cooldown_remaining=2,
            cooldown_recovery_confirmed=False,
        )
    )
    assert result.max_exposure == 0.40
    assert result.week_cooldown_remaining == 2


def test_expired_cooldown_needs_recovery_confirmation() -> None:
    waiting = evaluate_market_regime(
        strong_input(week_cooldown_remaining=0, cooldown_recovery_confirmed=False)
    )
    recovered = evaluate_market_regime(
        strong_input(week_cooldown_remaining=0, cooldown_recovery_confirmed=True)
    )
    assert waiting.max_exposure == 0.40
    assert recovered.max_exposure == 0.90


def test_month_cooldown_enforces_twenty_percent_cap() -> None:
    result = evaluate_market_regime(
        strong_input(
            portfolio_month_drawdown=0.0,
            month_cooldown_remaining=7,
            cooldown_recovery_confirmed=False,
        )
    )
    assert result.max_exposure == 0.20
    assert result.month_cooldown_remaining == 7
```

- [ ] **Step 2: 运行测试并确认共享模块缺失**

Run: `python -m pytest backend/tests/core/strategy/test_market_regime.py -q`
Expected: FAIL，包含 `No module named 'backend.app.core.strategy.market_regime'`。

- [ ] **Step 3: 实现稳定类型、原因码和两日确认**

```python
# backend/app/core/strategy/reason_codes.py
from enum import StrEnum


class ReasonCode(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    MARKET_WEAK = "MARKET_WEAK"
    MARKET_LOW_CONFIDENCE = "MARKET_LOW_CONFIDENCE"
    MARKET_OVERHEATED = "MARKET_OVERHEATED"
    SYSTEMIC_RISK_OVERLAY = "SYSTEMIC_RISK_OVERLAY"
    FINANCIAL_RED_FLAG = "FINANCIAL_RED_FLAG"
    HARD_STOP_TRIGGERED = "HARD_STOP_TRIGGERED"
    BREAKOUT_NOT_CONFIRMED = "BREAKOUT_NOT_CONFIRMED"
    ORDER_BELOW_MIN_NOTIONAL = "ORDER_BELOW_MIN_NOTIONAL"
    STOP_TOO_WIDE = "STOP_TOO_WIDE"
    POSITION_COUNT_LIMIT = "POSITION_COUNT_LIMIT"
    SECURITY_WEIGHT_LIMIT = "SECURITY_WEIGHT_LIMIT"
    INDUSTRY_WEIGHT_LIMIT = "INDUSTRY_WEIGHT_LIMIT"
    THEME_WEIGHT_LIMIT = "THEME_WEIGHT_LIMIT"
    LEDGER_WEIGHT_LIMIT = "LEDGER_WEIGHT_LIMIT"
    MARKET_EXPOSURE_LIMIT = "MARKET_EXPOSURE_LIMIT"
    PORTFOLIO_RISK_LIMIT = "PORTFOLIO_RISK_LIMIT"
    LIQUIDITY_LIMIT = "LIQUIDITY_LIMIT"
    BUY_GAP_OVER_3_PERCENT = "BUY_GAP_OVER_3_PERCENT"
    POLICY_UNAVAILABLE = "POLICY_UNAVAILABLE"
    LLM_INVALID = "LLM_INVALID"
    LLM_FACTOR_INVALID = "LLM_FACTOR_INVALID"
    DATA_STALE = "DATA_STALE"
    PRICE_DATE_MISMATCH = "PRICE_DATE_MISMATCH"
    SUSPENDED = "SUSPENDED"
    LIMIT_LOCKED = "LIMIT_LOCKED"
    INSUFFICIENT_VOLUME = "INSUFFICIENT_VOLUME"
    T_PLUS_ONE_LOCKED = "T_PLUS_ONE_LOCKED"
    MANUAL_CONFIRM_REQUIRED = "MANUAL_CONFIRM_REQUIRED"
```

```python
# backend/app/core/strategy/types.py
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from backend.app.contracts.strategy import AsOf, StrategyVersion
from backend.app.core.strategy.reason_codes import ReasonCode


class MarketState(StrEnum):
    STRONG = "strong"
    NEUTRAL = "neutral"
    WEAK = "weak"


class LedgerKind(StrEnum):
    CORE = "core"
    SWING = "swing"


@dataclass(frozen=True)
class MarketRegimeInput:
    index_close: float
    index_ma20: float
    index_ma20_5d_ago: float
    index_ma60: float
    breadth: float
    index_return_1d: float
    index_return_20d: float
    limit_down_count: int
    portfolio_open_drawdown: float
    portfolio_week_drawdown: float
    portfolio_month_drawdown: float
    week_cooldown_remaining: int
    month_cooldown_remaining: int
    cooldown_recovery_confirmed: bool
    current_state: MarketState
    candidate_streak: int
    low_confidence: bool


@dataclass(frozen=True)
class MarketRegimeDecision:
    state: MarketState
    max_exposure: float
    allow_new_risk: bool
    allow_swing: bool
    confidence: str
    week_cooldown_remaining: int
    month_cooldown_remaining: int
    reasons: tuple[ReasonCode, ...] = ()


@dataclass(frozen=True)
class PortfolioView:
    net_equity: float
    gross_exposure: float
    portfolio_risk: float
    position_count: int
    industry_weights: dict[str, float] = field(default_factory=dict)
    theme_weights: dict[str, float] = field(default_factory=dict)
    ledger_weights: dict[LedgerKind, float] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyEvaluationRequest:
    as_of: AsOf
    strategy: StrategyVersion
    manifest_hash: str
    market: MarketRegimeInput
    portfolio: PortfolioView
    securities: tuple["SecurityEvaluationInput", ...]


@dataclass(frozen=True)
class StrategyEvaluation:
    as_of_time: datetime
    strategy_version: str
    manifest_hash: str
    market: MarketRegimeDecision
    securities: tuple["SecurityEvaluation", ...]
```

Forward declarations `SecurityEvaluationInput` and `SecurityEvaluation` are completed in Task 6 in this
same file. No feature may define a second market-state, ledger or reason-code enum.
Cooldown semantics are fixed: `-1` means inactive, a positive value is the remaining mandatory trading-day
hold, and `0` means the minimum duration elapsed but recovery is not yet confirmed. Plan 01's input builder
sets `cooldown_recovery_confirmed=true` only when index > MA20, breadth >= 45%, and no same-level trigger
occurred in the latest three trading days.

```python
# backend/app/core/clock.py
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(tz=ZoneInfo("Asia/Shanghai"))
```

```python
# backend/app/core/strategy/market_regime.py
from backend.app.core.strategy.reason_codes import ReasonCode
from backend.app.core.strategy.types import (
    MarketRegimeDecision,
    MarketRegimeInput,
    MarketState,
)


def _raw_state(value: MarketRegimeInput) -> MarketState:
    if (
        value.index_close > value.index_ma60
        and value.index_ma20 > value.index_ma20_5d_ago
        and value.breadth >= 0.55
    ):
        return MarketState.STRONG
    if value.index_close < value.index_ma60 and value.breadth < 0.40:
        return MarketState.WEAK
    return MarketState.NEUTRAL


def evaluate_market_regime(value: MarketRegimeInput) -> MarketRegimeDecision:
    candidate = _raw_state(value)
    state = candidate if candidate == value.current_state or value.candidate_streak >= 2 else value.current_state
    if state is MarketState.STRONG:
        maximum = 0.90 if value.breadth >= 0.65 and value.index_close > value.index_ma20 else 0.80
        maximum = 0.70 if value.breadth < 0.50 else maximum
    elif state is MarketState.NEUTRAL:
        maximum = 0.60 if value.breadth >= 0.50 else 0.50
    else:
        maximum = 0.0 if value.breadth < 0.30 else 0.20

    reasons: list[ReasonCode] = []
    if value.low_confidence:
        maximum = {MarketState.STRONG: 0.70, MarketState.NEUTRAL: 0.40, MarketState.WEAK: 0.0}[state]
        reasons.append(ReasonCode.MARKET_LOW_CONFIDENCE)
    if value.breadth > 0.80 and value.index_return_20d > 0.12:
        maximum = max(0.0, maximum - 0.15)
        reasons.append(ReasonCode.MARKET_OVERHEATED)

    stop_new = (
        value.index_return_1d < -0.04
        or value.limit_down_count > 500
        or value.portfolio_open_drawdown >= 0.03
    )
    week_remaining = max(
        value.week_cooldown_remaining,
        5 if value.portfolio_week_drawdown >= 0.06 else -1,
    )
    month_remaining = max(
        value.month_cooldown_remaining,
        10 if value.portfolio_month_drawdown >= 0.10 else -1,
    )
    week_active = week_remaining > 0 or (
        week_remaining == 0 and not value.cooldown_recovery_confirmed
    )
    month_active = month_remaining > 0 or (
        month_remaining == 0 and not value.cooldown_recovery_confirmed
    )
    if week_active:
        maximum = min(maximum, 0.40)
        stop_new = True
    if month_active:
        maximum = min(maximum, 0.20)
        stop_new = True
    if stop_new:
        reasons.append(ReasonCode.SYSTEMIC_RISK_OVERLAY)
    if state is MarketState.WEAK:
        reasons.append(ReasonCode.MARKET_WEAK)

    return MarketRegimeDecision(
        state=state,
        max_exposure=maximum,
        allow_new_risk=state is not MarketState.WEAK and not stop_new,
        allow_swing=state is MarketState.STRONG and not stop_new,
        confidence="low" if value.low_confidence else "normal",
        week_cooldown_remaining=week_remaining,
        month_cooldown_remaining=month_remaining,
        reasons=tuple(reasons),
    )
```

```python
# backend/app/ports/strategy.py
from typing import Protocol

from backend.app.core.strategy.types import StrategyEvaluation, StrategyEvaluationRequest


class StrategyDecisionPort(Protocol):
    def evaluate(self, request: StrategyEvaluationRequest) -> StrategyEvaluation: ...
```

- [ ] **Step 4: 运行 golden tests、Ruff 和 mypy**

Run: `python -m pytest backend/tests/core/strategy/test_market_regime.py -q && python -m ruff check backend/app/core/strategy backend/app/ports && python -m mypy backend/app/core/strategy backend/app/ports`
Expected: `6 passed`，Ruff 和 mypy 退出 0。

- [ ] **Step 5: 提交市场状态契约**

```bash
git add backend/app/core/strategy backend/app/ports backend/tests/core/strategy
git commit -m "feat: centralize V2.12 market regime decisions"
```

### Task 5: 实现唯一 P、F、R、T、V、S 因子核心

**Files:**
- Create: `backend/app/core/strategy/factors.py`
- Modify: `backend/app/core/strategy/types.py`
- Test: `backend/tests/core/strategy/test_factors.py`

- [ ] **Step 1: 写手算因子 golden tests**

```python
# backend/tests/core/strategy/test_factors.py
import pytest

from backend.app.core.strategy.factors import (
    composite_score,
    financial_score,
    policy_score,
    relative_strength_score,
    trend_score,
    volume_score,
)
from backend.app.core.strategy.types import FinancialLight, PolicyEvidence, PolicyStage


def test_policy_decay_and_composite_are_hand_calculable() -> None:
    evidence = PolicyEvidence(
        strength=80.0,
        relevance=100.0,
        age_days=0,
        stage=PolicyStage.EXECUTION,
        evidence_confidence=1.0,
        data_completeness=1.0,
    )
    assert policy_score((evidence,)) == pytest.approx(80.0)
    assert composite_score(80.0, 70.0, 60.0, 50.0, 40.0) == pytest.approx(61.0)


def test_financial_red_light_and_industry_proxy_fail_closed() -> None:
    assert financial_score(80.0, 60.0, FinancialLight.YELLOW) == pytest.approx(65.0)
    assert financial_score(80.0, 60.0, FinancialLight.RED) is None
    assert relative_strength_score(80.0, 60.0, industry_proxy=True) == pytest.approx(63.0)


def test_trend_and_volume_follow_v212_weights() -> None:
    assert trend_score(True, True, True, True, ma20_atr_distance=1.0) == 100.0
    assert trend_score(True, True, True, True, ma20_atr_distance=2.6) == 80.0
    assert volume_score(80.0, 60.0, 40.0) == pytest.approx(66.0)
```

- [ ] **Step 2: 运行测试并确认函数缺失**

Run: `python -m pytest backend/tests/core/strategy/test_factors.py -q`
Expected: FAIL，包含 `No module named 'backend.app.core.strategy.factors'`。

- [ ] **Step 3: 实现纯函数和输入类型**

Append these types to `types.py`:

```python
class PolicyStage(StrEnum):
    PLANNING = "planning"
    PILOT = "pilot"
    EXECUTION = "execution"
    MATURE = "mature"
    EXIT = "exit"


class FinancialLight(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


@dataclass(frozen=True)
class PolicyEvidence:
    strength: float
    relevance: float
    age_days: int
    stage: PolicyStage
    evidence_confidence: float
    data_completeness: float


@dataclass(frozen=True)
class FactorScores:
    p: float
    f: float
    r: float
    t: float
    v: float
    s: float
    percentile: float
```

```python
# backend/app/core/strategy/factors.py
from math import exp

from backend.app.core.strategy.types import FinancialLight, PolicyEvidence, PolicyStage

HALF_LIFE = {
    PolicyStage.PLANNING: (20, 0.60),
    PolicyStage.PILOT: (40, 0.80),
    PolicyStage.EXECUTION: (60, 1.00),
    PolicyStage.MATURE: (30, 0.70),
}


def policy_score(evidence: tuple[PolicyEvidence, ...]) -> float | None:
    if not evidence or any(item.stage is PolicyStage.EXIT for item in evidence):
        return None
    weighted: list[tuple[float, float]] = []
    for item in evidence:
        half_life, stage_factor = HALF_LIFE[item.stage]
        raw = 50.0 + (item.strength - 50.0) * item.relevance / 100.0
        decayed = 50.0 + (raw - 50.0) * exp(-item.age_days / half_life)
        score = 50.0 + (decayed - 50.0) * stage_factor * item.evidence_confidence * item.data_completeness
        weight = item.evidence_confidence * item.data_completeness * exp(-item.age_days / half_life)
        weighted.append((score, weight))
    denominator = sum(weight for _, weight in weighted)
    return 50.0 if denominator == 0 else sum(score * weight for score, weight in weighted) / denominator


def financial_score(
    numeric_score: float,
    financial_text_score: float,
    light: FinancialLight,
) -> float | None:
    if light is FinancialLight.RED:
        return None
    score = 0.70 * numeric_score + 0.30 * financial_text_score
    return min(score, 65.0) if light is FinancialLight.YELLOW else score


def relative_strength_score(
    rs20_percentile: float,
    rs60_percentile: float,
    *,
    industry_proxy: bool,
) -> float:
    score = 0.50 * rs20_percentile + 0.50 * rs60_percentile
    return score * 0.90 if industry_proxy else score


def trend_score(
    above_ma20: bool,
    above_ma60: bool,
    rising_ma20: bool,
    breakout_or_valid_pullback: bool,
    *,
    ma20_atr_distance: float,
) -> float:
    score = 25.0 * sum((above_ma20, above_ma60, rising_ma20, breakout_or_valid_pullback))
    return max(0.0, score - 20.0) if ma20_atr_distance > 2.5 else score


def volume_score(
    breakout_volume_percentile: float,
    obv_slope_percentile: float,
    turnover_percentile: float,
) -> float:
    return (
        0.50 * breakout_volume_percentile
        + 0.30 * obv_slope_percentile
        + 0.20 * turnover_percentile
    )


def composite_score(p: float, f: float, r: float, t: float, v: float) -> float:
    return 0.20 * p + 0.20 * f + 0.25 * r + 0.20 * t + 0.15 * v


def percentile_rank(values: tuple[float, ...], value: float) -> float:
    if not values:
        raise ValueError("cross section cannot be empty")
    below = sum(item < value for item in values)
    equal = sum(item == value for item in values)
    return 100.0 * (below + 0.5 * equal) / len(values)
```

- [ ] **Step 4: 运行 golden tests 和属性边界检查**

Run: `python -m pytest backend/tests/core/strategy/test_factors.py -q && python -m mypy backend/app/core/strategy`
Expected: `3 passed`，mypy 退出 0；所有评分保持在 0—100。

- [ ] **Step 5: 提交共享因子核心**

```bash
git add backend/app/core/strategy backend/tests/core/strategy
git commit -m "feat: implement one authoritative V2.12 factor model"
```

### Task 6: 实现风险仓位、组合约束和 V212StrategyEngine facade

**Files:**
- Create: `backend/app/core/strategy/risk.py`
- Create: `backend/app/core/strategy/constraints.py`
- Create: `backend/app/core/strategy/service.py`
- Modify: `backend/app/core/strategy/types.py`
- Test: `backend/tests/core/strategy/test_risk_constraints.py`
- Test: `backend/tests/core/strategy/test_service.py`

- [ ] **Step 1: 写失败的风险和约束 tests**

```python
# backend/tests/core/strategy/test_risk_constraints.py
import pytest

from backend.app.core.strategy.constraints import check_constraints
from backend.app.core.strategy.risk import size_position
from backend.app.core.strategy.types import (
    ConstraintInput,
    LedgerKind,
    PortfolioView,
    PositionSizingInput,
)


def test_position_size_uses_half_percent_risk_and_hundred_share_lot() -> None:
    result = size_position(
        PositionSizingInput(
            net_equity=150_000,
            planned_price=20.0,
            pullback_low=18.5,
            atr14=1.0,
            average_turnover20=10_000_000,
            ledger=LedgerKind.CORE,
        )
    )
    assert result.initial_stop == pytest.approx(18.3)
    assert result.quantity == 400
    assert result.notional == pytest.approx(8_000)


def test_industry_and_total_risk_block_order() -> None:
    portfolio = PortfolioView(
        net_equity=100_000,
        gross_exposure=0.50,
        portfolio_risk=0.029,
        position_count=3,
        industry_weights={"电子": 0.24},
        theme_weights={},
        ledger_weights={LedgerKind.CORE: 0.30},
    )
    decision = check_constraints(
        ConstraintInput(
            portfolio=portfolio,
            market_max_exposure=0.60,
            ledger=LedgerKind.CORE,
            industry="电子",
            theme="AI",
            order_notional=5_000,
            order_risk=500,
            is_broad_etf=False,
        )
    )
    assert decision.allowed is False
    assert {item.value for item in decision.reasons} == {
        "INDUSTRY_WEIGHT_LIMIT",
        "PORTFOLIO_RISK_LIMIT",
    }
```

- [ ] **Step 2: 运行测试并确认风险模块缺失**

Run: `python -m pytest backend/tests/core/strategy/test_risk_constraints.py -q`
Expected: FAIL，包含 `No module named 'backend.app.core.strategy.constraints'`。

- [ ] **Step 3: 实现仓位、约束、facade 输入输出**

Append exact dataclasses to `types.py`:

```python
@dataclass(frozen=True)
class PositionSizingInput:
    net_equity: float
    planned_price: float
    pullback_low: float
    atr14: float
    average_turnover20: float
    ledger: LedgerKind


@dataclass(frozen=True)
class PositionSizingDecision:
    quantity: int
    initial_stop: float
    stop_distance: float
    notional: float
    order_risk: float
    reasons: tuple[ReasonCode, ...] = ()


@dataclass(frozen=True)
class ConstraintInput:
    portfolio: PortfolioView
    market_max_exposure: float
    ledger: LedgerKind
    industry: str
    theme: str | None
    order_notional: float
    order_risk: float
    is_broad_etf: bool


@dataclass(frozen=True)
class ConstraintDecision:
    allowed: bool
    reasons: tuple[ReasonCode, ...]


@dataclass(frozen=True)
class SecurityEvaluationInput:
    security_id: str
    name: str
    industry: str
    theme: str | None
    ledger: LedgerKind
    policy_evidence: tuple[PolicyEvidence, ...]
    financial_numeric_score: float
    financial_text_score: float
    financial_light: FinancialLight
    policy_direction: str
    rs20_percentile: float
    rs60_percentile: float
    industry_proxy: bool
    above_ma20: bool
    above_ma60: bool
    rising_ma20: bool
    breakout_or_valid_pullback: bool
    ma20_atr_distance: float
    breakout_volume_percentile: float
    obv_slope_percentile: float
    turnover_percentile: float
    planned_price: float
    close: float
    ma20: float
    ma60: float
    pullback_low: float
    atr14: float
    average_turnover20: float
    hard_filter_passed: bool
    policy_sources_available: bool
    llm_factor_valid: bool
    breakout_confirmed: bool
    pullback_confirmed: bool
    strengthened_confirmed: bool
    days_since_breakout: int
    held: bool
    r_multiple: float | None
    rank_percentile: float
    red_light: bool
    hard_stop: bool
    market_reduction: bool
    book_exit: bool
    rank_exit: bool
    stop_raise_required: bool
    quality_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class SecurityEvaluation:
    security_id: str
    name: str
    industry: str
    theme: str | None
    factors: FactorScores | None
    market_state: MarketState
    hard_filter_passed: bool
    policy_sources_available: bool
    llm_factor_valid: bool
    financial_light: FinancialLight
    policy_direction: str
    breakout_confirmed: bool
    pullback_confirmed: bool
    strengthened_confirmed: bool
    days_since_breakout: int
    held: bool
    close: float
    ma20: float
    ma60: float
    atr14: float
    r_multiple: float | None
    rank_percentile: float
    red_light: bool
    hard_stop: bool
    market_reduction: bool
    book_exit: bool
    rank_exit: bool
    stop_raise_required: bool
    sizing: PositionSizingDecision | None
    constraint: ConstraintDecision
    quality_codes: tuple[str, ...]
    reasons: tuple[ReasonCode, ...]
```

```python
# backend/app/core/strategy/risk.py
from math import floor

from backend.app.core.strategy.reason_codes import ReasonCode
from backend.app.core.strategy.types import (
    LedgerKind,
    PositionSizingDecision,
    PositionSizingInput,
)


def size_position(value: PositionSizingInput) -> PositionSizingDecision:
    structural_stop = value.pullback_low - 0.2 * value.atr14
    noise_stop = value.planned_price - 1.2 * value.atr14
    initial_stop = min(structural_stop, noise_stop)
    distance = value.planned_price - initial_stop
    if distance <= 0 or distance > 2.5 * value.atr14:
        return PositionSizingDecision(
            0, initial_stop, distance, 0.0, 0.0, (ReasonCode.STOP_TOO_WIDE,)
        )
    theoretical = floor((value.net_equity * 0.005 / distance) / 100) * 100
    weight_limit = 0.15 if value.ledger is LedgerKind.CORE else 0.12
    by_weight = floor((value.net_equity * weight_limit / value.planned_price) / 100) * 100
    by_liquidity = floor(
        (value.average_turnover20 * 0.002 / value.planned_price) / 100
    ) * 100
    quantity = max(0, min(theoretical, by_weight, by_liquidity))
    notional = quantity * value.planned_price
    if notional < 5_000:
        return PositionSizingDecision(
            0,
            initial_stop,
            distance,
            0.0,
            0.0,
            (ReasonCode.ORDER_BELOW_MIN_NOTIONAL,),
        )
    return PositionSizingDecision(
        quantity, initial_stop, distance, notional, quantity * distance
    )
```

```python
# backend/app/core/strategy/constraints.py
from backend.app.core.strategy.reason_codes import ReasonCode
from backend.app.core.strategy.types import ConstraintDecision, ConstraintInput, LedgerKind


def check_constraints(value: ConstraintInput) -> ConstraintDecision:
    portfolio = value.portfolio
    weight = value.order_notional / portfolio.net_equity
    risk = value.order_risk / portfolio.net_equity
    reasons: list[ReasonCode] = []
    if portfolio.position_count >= 6:
        reasons.append(ReasonCode.POSITION_COUNT_LIMIT)
    security_limit = 0.15 if value.ledger is LedgerKind.CORE else 0.12
    if weight > security_limit:
        reasons.append(ReasonCode.SECURITY_WEIGHT_LIMIT)
    if not value.is_broad_etf and portfolio.industry_weights.get(value.industry, 0.0) + weight > 0.25:
        reasons.append(ReasonCode.INDUSTRY_WEIGHT_LIMIT)
    if value.theme and portfolio.theme_weights.get(value.theme, 0.0) + weight > 0.30:
        reasons.append(ReasonCode.THEME_WEIGHT_LIMIT)
    if value.ledger is LedgerKind.CORE and portfolio.ledger_weights.get(value.ledger, 0.0) + weight > 0.50:
        reasons.append(ReasonCode.LEDGER_WEIGHT_LIMIT)
    if portfolio.gross_exposure + weight > value.market_max_exposure:
        reasons.append(ReasonCode.MARKET_EXPOSURE_LIMIT)
    if portfolio.portfolio_risk + risk > 0.03:
        reasons.append(ReasonCode.PORTFOLIO_RISK_LIMIT)
    return ConstraintDecision(allowed=not reasons, reasons=tuple(reasons))
```

`service.py` defines `class V212StrategyEngine(StrategyDecisionPort)`. Its `evaluate` must:

1. call `evaluate_market_regime` once;
2. call only Task 5 factor functions for every security;
3. fail closed when hard filter, policy source, LLM or F is invalid;
4. compute all S values, then `percentile_rank` on that same-day cross section;
5. call `size_position` and `check_constraints`;
6. return securities sorted by `(-S, security_id)` for deterministic ties;
7. copy `request.as_of.as_of_time`, `request.strategy.version` and `manifest_hash` unchanged.

The service must not import FastAPI, SQLAlchemy, provider SDKs or feature packages.

- [ ] **Step 4: 写 facade test 并运行全部共享核心测试**

Add `backend/tests/core/strategy/test_service.py` with a deterministic fixture and these executable
assertions (the helper supplies the remaining typed fields with fixed values):

```python
def test_engine_sorts_by_score_and_fails_closed_for_missing_policy() -> None:
    request = fake_strategy_request(
        securities=(fake_security("A", rs20=90.0, rs60=90.0),
                    fake_security("B", rs20=60.0, rs60=60.0)),
    )
    engine = V212StrategyEngine()
    first = engine.evaluate(request)
    second = engine.evaluate(request)
    assert first == second
    assert [item.security_id for item in first.securities] == ["A", "B"]
    assert first.securities[0].rank_percentile > first.securities[1].rank_percentile
    assert first.strategy_version == request.strategy.version
    assert first.as_of_time == request.as_of.as_of_time
    assert first.manifest_hash == request.manifest_hash


def test_engine_marks_missing_policy_without_sizing() -> None:
    request = fake_strategy_request(
        securities=(fake_security("A", policy_available=False),),
    )
    result = V212StrategyEngine().evaluate(request)
    assert result.securities[0].quality_codes == ("POLICY_UNAVAILABLE",)
    assert result.securities[0].sizing is None
```

`fake_security` and `fake_strategy_request` construct `SecurityEvaluationInput` and
`StrategyEvaluationRequest` with explicit `AsOf`, `StrategyVersion`, `MarketRegimeInput` and
`PortfolioView` values; no random values or current time are permitted. This verifies hand-computed S
ordering, cross-sectional percentiles, fail-closed policy behavior, metadata preservation, and repeatable
dataclass equality.

Run the new test before implementation:

```bash
python -m pytest backend/tests/core/strategy/test_service.py -q
```

Expected: FAIL with `ModuleNotFoundError` or missing `V212StrategyEngine`.

After implementing the facade, run the full shared core command below.

Run: `python -m pytest backend/tests/core/strategy -q && python -m ruff check backend/app/core/strategy backend/app/ports && python -m mypy backend/app/core/strategy backend/app/ports`
Expected: 所有 tests PASS；Ruff 和 mypy 退出 0。

- [ ] **Step 5: 提交唯一共享策略 facade**

```bash
git add backend/app/core/strategy backend/app/ports backend/tests/core/strategy
git commit -m "feat: centralize V2.12 sizing and portfolio constraints"
```

### Task 7: 建立 SQLAlchemy 基线和 Alembic 迁移链

**Files:**
- Create: `alembic.ini`
- Create: `backend/migrations/env.py`
- Create: `backend/migrations/script.py.mako`
- Create: `backend/migrations/versions/20260716_0001_run_tables.py`
- Create: `backend/app/infrastructure/__init__.py`
- Create: `backend/app/infrastructure/persistence/__init__.py`
- Create: `backend/app/infrastructure/persistence/database.py`
- Create: `backend/app/infrastructure/persistence/models.py`
- Test: `backend/tests/infrastructure/persistence/test_migrations.py`

- [ ] **Step 1: 写失败的 PostgreSQL 迁移测试**

```python
# backend/tests/infrastructure/persistence/test_migrations.py
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import Engine


def test_migration_creates_run_tables(postgres_engine: Engine, monkeypatch: object) -> None:
    monkeypatch.setenv("DA_DATABASE_URL", str(postgres_engine.url))
    config = Config("alembic.ini")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    assert {"runs", "run_events", "run_artifacts", "alembic_version"} <= set(
        inspect(postgres_engine).get_table_names()
    )
```

- [ ] **Step 2: 启动测试库并确认迁移配置缺失**

Run: `docker compose up -d postgres-test && python -m pytest backend/tests/infrastructure/persistence/test_migrations.py -q -m postgres`
Expected: FAIL，包含 `No 'script_location' key found`。

- [ ] **Step 3: 实现 ORM 基线并生成精确 revision**

```python
# backend/app/infrastructure/persistence/database.py
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def build_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
```

```python
# backend/app/infrastructure/persistence/models.py
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RunRow(Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("kind", "idempotency_key", name="uq_runs_kind_idempotency"),
        Index("ix_runs_claim", "status", "submitted_at"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)


class RunEventRow(Base):
    __tablename__ = "run_events"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class RunArtifactRow(Base):
    __tablename__ = "run_artifacts"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(64))
    relative_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    media_type: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

Set `script_location = backend/migrations` and `prepend_sys_path = .` in `alembic.ini`. In
`env.py` set `target_metadata = Base.metadata` and load the URL from `Settings`. Then run:

```bash
DA_DATABASE_URL=postgresql+psycopg://da:da@127.0.0.1:55433/da_test \
  alembic revision --autogenerate --rev-id 20260716_0001 -m "create run tables"
```

Rename the generated file to `20260716_0001_run_tables.py`. It must contain only the three ORM tables,
`uq_runs_kind_idempotency`, `ix_runs_claim`, both foreign keys and their indexes; `downgrade()` drops
artifacts, events and runs in that order.

- [ ] **Step 4: 验证 upgrade—downgrade—upgrade**

Run: `python -m pytest backend/tests/infrastructure/persistence/test_migrations.py -q -m postgres`
Expected: `1 passed`，数据库最终位于 `20260716_0001`。

- [ ] **Step 5: 提交持久化基线**

```bash
git add alembic.ini backend/migrations backend/app/infrastructure backend/tests/infrastructure
git commit -m "feat: persist run state through a versioned PostgreSQL schema"
```

### Task 8: 建立共享、校验哈希且受根目录保护的产物仓库

**Files:**
- Create: `backend/app/ports/artifacts.py`
- Create: `backend/app/ports/uow.py`
- Create: `backend/app/infrastructure/persistence/artifact_paths.py`
- Create: `backend/app/features/runs/artifacts.py`
- Test: `backend/tests/features/runs/test_artifacts.py`

- [ ] **Step 1: 写失败的保存、读取和 traversal test**

```python
# backend/tests/features/runs/test_artifacts.py
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.features.runs.artifacts import SqlArtifactRepository
from backend.app.infrastructure.persistence.models import Base, RunRow
from backend.app.infrastructure.persistence.artifact_paths import UnsafeArtifactPath


def test_json_artifact_round_trips_with_hash(
    postgres_engine: Engine,
    tmp_path: Path,
) -> None:
    Base.metadata.drop_all(postgres_engine)
    Base.metadata.create_all(postgres_engine)
    sessions = sessionmaker(postgres_engine, expire_on_commit=False)
    with sessions.begin() as session:
        run = RunRow(
            kind="backtest",
            status="running",
            request_payload={},
            submitted_at=datetime(2026, 7, 16, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        session.add(run)
        session.flush()
        run_id = run.id
    repository = SqlArtifactRepository(sessions, tmp_path)
    with sessions.begin() as uow:
        ref = repository.save_json(uow, run_id, "metrics.json", {"data_grade": "research"})

    with repository.open(run_id, ref.artifact_id) as source:
        assert source.read() == b'{"data_grade":"research"}'
    assert len(ref.sha256) == 64


def test_artifact_name_cannot_escape_root(
    postgres_engine: Engine,
    tmp_path: Path,
) -> None:
    repository = SqlArtifactRepository(sessionmaker(postgres_engine), tmp_path)
    with sessionmaker(postgres_engine).begin() as uow, pytest.raises(UnsafeArtifactPath):
        repository.save_json(uow, uuid4(), "../../.env", {})


def test_result_and_artifact_share_one_unit_of_work(
    postgres_engine: Engine,
    tmp_path: Path,
) -> None:
    """A handler commits its result row and artifact metadata atomically."""
    Base.metadata.drop_all(postgres_engine)
    Base.metadata.create_all(postgres_engine)
    sessions = sessionmaker(postgres_engine, expire_on_commit=False)
    repository = SqlArtifactRepository(sessions, tmp_path)
    run_id = uuid4()
    with sessions.begin() as uow:
        uow.add(RunRow(id=run_id, kind="backtest", status="running", request_payload={},
                       submitted_at=datetime(2026, 7, 16, tzinfo=ZoneInfo("Asia/Shanghai"))))
        repository.save_json(uow, run_id, "metrics.json", {"ok": True})
    with sessions() as session:
        assert session.get(RunRow, run_id) is not None


def test_uow_failure_rolls_back_result_and_artifact_metadata(
    postgres_engine: Engine,
    tmp_path: Path,
) -> None:
    Base.metadata.drop_all(postgres_engine)
    Base.metadata.create_all(postgres_engine)
    sessions = sessionmaker(postgres_engine, expire_on_commit=False)
    repository = SqlArtifactRepository(sessions, tmp_path)
    run_id = uuid4()
    with pytest.raises(RuntimeError):
        with sessions.begin() as uow:
            uow.add(RunRow(id=run_id, kind="backtest", status="running", request_payload={},
                           submitted_at=datetime(2026, 7, 16, tzinfo=ZoneInfo("Asia/Shanghai"))))
            repository.save_json(uow, run_id, "metrics.json", {"ok": True})
            raise RuntimeError("handler failure")
    with sessions() as session:
        assert session.get(RunRow, run_id) is None
```

- [ ] **Step 2: 运行 test 并确认共享 repository 缺失**

Run: `python -m pytest backend/tests/features/runs/test_artifacts.py -q -m postgres`
Expected: FAIL，包含 `No module named 'backend.app.features.runs.artifacts'`。

- [ ] **Step 3: 实现 port、path guard 和 repository**

```python
# backend/app/ports/artifacts.py
from dataclasses import dataclass
from typing import BinaryIO, Protocol
from uuid import UUID

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: UUID
    run_id: UUID
    name: str
    sha256: str
    media_type: str


class PersistenceUnitOfWork(Protocol):
    """The transaction-scoped session shared by result and artifact repositories."""

    def add(self, instance: object) -> None: ...

    def flush(self) -> None: ...


class ArtifactRepository(Protocol):
    def save_json(
        self,
        uow: PersistenceUnitOfWork,
        run_id: UUID,
        name: str,
        payload: object,
    ) -> ArtifactRef: ...
    def open(self, run_id: UUID, artifact_id: UUID) -> BinaryIO: ...
```

```python
# backend/app/infrastructure/persistence/artifact_paths.py
from pathlib import Path


class UnsafeArtifactPath(ValueError):
    pass


def resolve_artifact(root: Path, relative_path: str) -> Path:
    if Path(relative_path).is_absolute():
        raise UnsafeArtifactPath("absolute artifact path")
    resolved_root = root.resolve()
    resolved = (resolved_root / relative_path).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise UnsafeArtifactPath("artifact path escapes root")
    return resolved
```

```python
# backend/app/features/runs/artifacts.py
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, sessionmaker

from backend.app.infrastructure.persistence.artifact_paths import (
    UnsafeArtifactPath,
    resolve_artifact,
)
from backend.app.infrastructure.persistence.models import RunArtifactRow
from backend.app.ports.artifacts import ArtifactRef


class SqlArtifactRepository:
    def __init__(self, sessions: sessionmaker[Session], root: Path) -> None:
        self._sessions = sessions
        self._root = root

    def save_json(
        self,
        uow: Session,
        run_id: UUID,
        name: str,
        payload: object,
    ) -> ArtifactRef:
        if Path(name).name != name:
            raise UnsafeArtifactPath("artifact name must be a basename")
        artifact_id = uuid4()
        relative = f"{run_id}/{artifact_id}-{name}"
        path = resolve_artifact(self._root, relative)
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        digest = sha256(raw).hexdigest()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(raw)
        temporary.replace(path)
        uow.add(
            RunArtifactRow(
                id=artifact_id,
                run_id=run_id,
                kind="json",
                relative_path=relative,
                sha256=digest,
                media_type="application/json",
                created_at=datetime.now(tz=ZoneInfo("Asia/Shanghai")),
            )
        )
        uow.flush()
        return ArtifactRef(artifact_id, run_id, name, digest, "application/json")

    def open(self, run_id: UUID, artifact_id: UUID) -> BinaryIO:
        with self._sessions() as session:
            row = session.get(RunArtifactRow, artifact_id)
            if row is None or row.run_id != run_id:
                raise KeyError(str(artifact_id))
            path = resolve_artifact(self._root, row.relative_path)
            raw = path.read_bytes()
            if sha256(raw).hexdigest() != row.sha256:
                raise OSError("artifact hash mismatch")
        return path.open("rb")
```

- [ ] **Step 4: 验证产物 tests 与类型契约**

Run: `python -m pytest backend/tests/features/runs/test_artifacts.py -q -m postgres && python -m mypy backend/app/ports/artifacts.py backend/app/features/runs/artifacts.py`
Expected: `2 passed`，mypy 退出 0；数据库只保存相对路径和哈希。

- [ ] **Step 5: 提交共享产物仓库**

```bash
git add backend/app/ports/artifacts.py backend/app/infrastructure/persistence/artifact_paths.py backend/app/features/runs/artifacts.py backend/tests/features/runs/test_artifacts.py
git commit -m "feat: protect shared run artifacts with rooted paths and hashes"
```

### Task 9: 实现幂等提交、SKIP LOCKED 领取和状态机

**Files:**
- Create: `backend/app/features/__init__.py`
- Create: `backend/app/features/runs/__init__.py`
- Create: `backend/app/features/runs/repository.py`
- Test: `backend/tests/features/runs/test_repository.py`

- [ ] **Step 1: 写并发领取和幂等失败测试**

```python
# backend/tests/features/runs/test_repository.py
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from backend.app.contracts.runs import RunKind, RunStatus
from backend.app.features.runs.repository import InvalidRunTransition, RunRepository
from backend.app.infrastructure.persistence.models import Base

NOW = datetime(2026, 7, 16, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))


@pytest.mark.postgres
def test_submit_is_idempotent_and_claim_is_exclusive(postgres_engine: Engine) -> None:
    Base.metadata.drop_all(postgres_engine)
    Base.metadata.create_all(postgres_engine)
    factory = sessionmaker(postgres_engine, expire_on_commit=False)
    with factory.begin() as session:
        first = RunRepository(session).submit(RunKind.BACKTEST, {}, "same", NOW)
    with factory.begin() as session:
        second = RunRepository(session).submit(RunKind.BACKTEST, {}, "same", NOW)
    assert first.id == second.id

    def claim() -> str | None:
        with factory.begin() as session:
            row = RunRepository(session).claim_next(NOW)
            return str(row.id) if row else None

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: claim(), range(2)))
    assert [item for item in claims if item] == [str(first.id)]


@pytest.mark.postgres
def test_terminal_run_rejects_backward_transition(postgres_engine: Engine) -> None:
    factory = sessionmaker(postgres_engine, expire_on_commit=False)
    with factory.begin() as session:
        run = RunRepository(session).submit(RunKind.BACKTEST, {}, "terminal", NOW)
        RunRepository(session).transition(run.id, RunStatus.CANCELLED, NOW)
    with factory.begin() as session, pytest.raises(InvalidRunTransition):
        RunRepository(session).transition(run.id, RunStatus.RUNNING, NOW)
```

- [ ] **Step 2: 运行测试并确认 repository 缺失**

Run: `python -m pytest backend/tests/features/runs/test_repository.py -q -m postgres`
Expected: FAIL，包含 `No module named 'backend.app.features.runs.repository'`。

- [ ] **Step 3: 实现原子 repository**

```python
# backend/app/features/runs/repository.py
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.contracts.runs import RunKind, RunStatus
from backend.app.infrastructure.persistence.models import RunEventRow, RunRow


class InvalidRunTransition(RuntimeError):
    pass


ALLOWED = {
    RunStatus.QUEUED: {RunStatus.RUNNING, RunStatus.CANCELLED},
    RunStatus.RUNNING: {
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.QUEUED,
    },
    RunStatus.SUCCEEDED: set(),
    RunStatus.FAILED: set(),
    RunStatus.CANCELLED: set(),
}


class RunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def submit(
        self,
        kind: RunKind,
        payload: dict[str, object],
        key: str | None,
        now: datetime,
    ) -> RunRow:
        if key:
            existing = self._session.scalar(
                select(RunRow).where(RunRow.kind == kind.value, RunRow.idempotency_key == key)
            )
            if existing:
                return existing
        row = RunRow(
            kind=kind.value,
            status=RunStatus.QUEUED.value,
            request_payload=payload,
            idempotency_key=key,
            submitted_at=now,
        )
        savepoint = self._session.begin_nested()
        try:
            self._session.add(row)
            self._session.flush()
            savepoint.commit()
        except IntegrityError:
            savepoint.rollback()
            if key is None:
                raise
            existing = self._session.scalar(
                select(RunRow).where(
                    RunRow.kind == kind.value,
                    RunRow.idempotency_key == key,
                )
            )
            if existing is None:
                raise
            return existing
        self._event(row.id, "submitted", now)
        return row

    def claim_next(self, now: datetime) -> RunRow | None:
        row = self._session.scalar(
            select(RunRow)
            .where(RunRow.status == RunStatus.QUEUED.value)
            .order_by(RunRow.submitted_at, RunRow.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if row is None:
            return None
        row.status = RunStatus.RUNNING.value
        row.started_at = row.started_at or now
        row.heartbeat_at = now
        self._event(row.id, "claimed", now)
        self._session.flush()
        return row

    def transition(self, run_id: UUID, target: RunStatus, now: datetime) -> RunRow:
        row = self._session.get(RunRow, run_id, with_for_update=True)
        if row is None:
            raise KeyError(str(run_id))
        current = RunStatus(row.status)
        if target not in ALLOWED[current]:
            raise InvalidRunTransition(f"{current.value} -> {target.value}")
        row.status = target.value
        if target in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}:
            row.finished_at = now
        self._event(run_id, target.value, now)
        self._session.flush()
        return row

    def heartbeat(self, run_id: UUID, stage: str, progress: int, now: datetime) -> None:
        self._session.execute(
            update(RunRow)
            .where(RunRow.id == run_id, RunRow.status == RunStatus.RUNNING.value)
            .values(heartbeat_at=now, stage=stage, progress=progress)
        )

    def requeue_stale(self, cutoff: datetime, now: datetime) -> tuple[UUID, ...]:
        ids = tuple(
            self._session.scalars(
                update(RunRow)
                .where(
                    RunRow.status == RunStatus.RUNNING.value,
                    RunRow.heartbeat_at < cutoff,
                )
                .values(
                    status=RunStatus.QUEUED.value,
                    retry_count=RunRow.retry_count + 1,
                    stage=None,
                    progress=0,
                )
                .returning(RunRow.id)
            )
        )
        for run_id in ids:
            self._event(run_id, "requeued_after_stale_heartbeat", now)
        return ids

    def _event(self, run_id: UUID, event_type: str, now: datetime) -> None:
        self._session.add(
            RunEventRow(run_id=run_id, occurred_at=now, event_type=event_type, payload={})
        )
```

The database unique constraint remains the final idempotency guard; the pre-select is only the fast path.

- [ ] **Step 4: 重跑并发测试十次**

Run: `for i in {1..10}; do python -m pytest backend/tests/features/runs/test_repository.py -q -m postgres || exit 1; done`
Expected: 每次 `2 passed`，相同 key 只有一条记录。

- [ ] **Step 5: 提交持久队列 repository**

```bash
git add backend/app/features backend/tests/features
git commit -m "feat: make run submission and claiming durable and idempotent"
```

### Task 10: 实现 handler registry、worker 心跳与恢复

**Files:**
- Create: `backend/app/infrastructure/tasks/__init__.py`
- Create: `backend/app/infrastructure/tasks/handlers.py`
- Create: `backend/app/infrastructure/tasks/worker.py`
- Test: `backend/tests/infrastructure/tasks/test_worker.py`

- [ ] **Step 1: 写失败的 worker dispatch tests**

```python
# backend/tests/infrastructure/tasks/test_worker.py
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from backend.app.contracts.runs import RunKind, RunStatus
from backend.app.infrastructure.tasks.handlers import HandlerRegistry
from backend.app.infrastructure.tasks.worker import Worker

NOW = datetime(2026, 7, 16, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))


class FakeRuns:
    def __init__(self, kind: str) -> None:
        self.run = type("Run", (), {"id": uuid4(), "kind": kind, "request_payload": {"n": 3}})()
        self.transitions: list[RunStatus] = []

    def claim_next(self, now: datetime) -> object:
        return self.run

    def transition(self, run_id: object, status: RunStatus, now: datetime) -> object:
        self.transitions.append(status)
        return self.run

    def heartbeat(self, run_id: object, stage: str, progress: int, now: datetime) -> None:
        pass


def test_registered_handler_succeeds() -> None:
    runs = FakeRuns(RunKind.BACKTEST.value)
    handlers = HandlerRegistry()
    handlers.register(RunKind.BACKTEST, lambda context: context.payload["n"])
    assert Worker(runs, handlers, lambda: NOW).run_once() is True
    assert runs.transitions == [RunStatus.SUCCEEDED]


def test_unknown_kind_fails() -> None:
    runs = FakeRuns("unknown")
    Worker(runs, HandlerRegistry(), lambda: NOW).run_once()
    assert runs.transitions == [RunStatus.FAILED]
```

- [ ] **Step 2: 运行测试并确认 tasks 模块缺失**

Run: `python -m pytest backend/tests/infrastructure/tasks/test_worker.py -q`
Expected: FAIL，包含 `No module named 'backend.app.infrastructure.tasks'`。

- [ ] **Step 3: 实现窄任务接口和一次循环**

```python
# backend/app/infrastructure/tasks/handlers.py
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from backend.app.contracts.runs import RunKind


@dataclass(frozen=True)
class JobContext:
    run_id: UUID
    payload: dict[str, object]
    heartbeat: Callable[[str, int], None]


JobHandler = Callable[[JobContext], object]


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[RunKind, JobHandler] = {}

    def register(self, kind: RunKind, handler: JobHandler) -> None:
        if kind in self._handlers:
            raise ValueError(f"duplicate handler: {kind.value}")
        self._handlers[kind] = handler

    def resolve(self, kind: RunKind) -> JobHandler:
        try:
            return self._handlers[kind]
        except KeyError as exc:
            raise LookupError(f"unregistered handler: {kind.value}") from exc
```

```python
# backend/app/infrastructure/tasks/worker.py
from collections.abc import Callable
from datetime import datetime
import time

from backend.app.contracts.runs import RunKind, RunStatus
from backend.app.infrastructure.tasks.handlers import HandlerRegistry, JobContext


class Worker:
    def __init__(self, runs: object, handlers: HandlerRegistry, clock: Callable[[], datetime]) -> None:
        self._runs = runs
        self._handlers = handlers
        self._clock = clock

    def run_once(self) -> bool:
        run = self._runs.claim_next(self._clock())
        if run is None:
            return False
        try:
            handler = self._handlers.resolve(RunKind(run.kind))
            handler(
                JobContext(
                    run.id,
                    run.request_payload,
                    lambda stage, progress: self._runs.heartbeat(
                        run.id, stage, progress, self._clock()
                    ),
                )
            )
        except Exception:
            self._runs.transition(run.id, RunStatus.FAILED, self._clock())
            return True
        self._runs.transition(run.id, RunStatus.SUCCEEDED, self._clock())
        return True


def run() -> None:
    from backend.app.bootstrap.application import build_worker

    worker = build_worker()
    while True:
        if not worker.run_once():
            time.sleep(0.5)
```

- [ ] **Step 4: 验证成功、失败和 stale 恢复**

Run: `python -m pytest backend/tests/infrastructure/tasks/test_worker.py backend/tests/features/runs/test_repository.py -q`
Expected: 全部 PASS；异常日志不包含 `request_payload`。

- [ ] **Step 5: 提交 worker**

```bash
git add backend/app/infrastructure/tasks backend/tests/infrastructure/tasks
git commit -m "feat: dispatch durable jobs through a narrow handler registry"
```

### Task 11: 建立可注入 feature 注册、健康检查和运行中心 API

**Files:**
- Create: `backend/app/bootstrap/feature_registry.py`
- Create: `backend/app/bootstrap/default_features.py`
- Create: `backend/app/bootstrap/application.py`
- Create: `backend/app/ports/runs.py`
- Create: `backend/app/features/runs/service.py`
- Create: `backend/app/features/runs/router.py`
- Create: `backend/app/features/runs/module.py`
- Create: `backend/app/main.py`
- Test: `backend/tests/api/test_foundation_api.py`

- [ ] **Step 1: 写失败的注册和错误 envelope tests**

```python
# backend/tests/api/test_foundation_api.py
from fastapi import APIRouter
from fastapi.testclient import TestClient

from backend.app.bootstrap.application import create_app
from backend.app.bootstrap.feature_registry import FeatureModule


def test_router_is_included_without_changing_main() -> None:
    router = APIRouter()

    @router.get("/probe")
    def probe() -> dict[str, bool]:
        return {"registered": True}

    client = TestClient(create_app((FeatureModule("probe", router, ()),)))
    assert client.get("/api/v1/probe").json() == {"registered": True}


def test_health_and_error_have_request_id() -> None:
    client = TestClient(create_app(()))
    assert client.get("/api/v1/health/live").json() == {"status": "ok"}
    missing = client.get("/api/v1/runs/missing")
    assert missing.status_code == 404
    assert set(missing.json()) == {"code", "message", "request_id", "details"}
    assert missing.headers["x-request-id"] == missing.json()["request_id"]
```

- [ ] **Step 2: 运行测试并确认应用工厂缺失**

Run: `python -m pytest backend/tests/api/test_foundation_api.py -q`
Expected: FAIL，包含 `No module named 'backend.app.bootstrap.application'`。

- [ ] **Step 3: 实现注册对象、显式依赖和应用工厂**

```python
# backend/app/bootstrap/feature_registry.py
from dataclasses import dataclass

from fastapi import APIRouter

from backend.app.contracts.runs import RunKind
from backend.app.infrastructure.tasks.handlers import JobHandler


@dataclass(frozen=True)
class FeatureModule:
    name: str
    router: APIRouter
    job_handlers: tuple[tuple[RunKind, JobHandler], ...]
```

```python
# backend/app/bootstrap/application.py
from collections.abc import Sequence
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.bootstrap.feature_registry import FeatureModule
from backend.app.bootstrap.settings import Settings


def create_app(
    features: Sequence[FeatureModule],
    settings: Settings | None = None,
) -> FastAPI:
    resolved = settings or Settings()
    app = FastAPI(title="DA Platform API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type", "Idempotency-Key", "X-Request-ID"],
    )

    @app.middleware("http")
    async def add_request_id(request: Request, call_next: object) -> object:
        value = request.headers.get("x-request-id", str(uuid4()))
        request.state.request_id = value
        response = await call_next(request)
        response.headers["x-request-id"] = value
        return response

    @app.exception_handler(KeyError)
    async def not_found(request: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "code": "NOT_FOUND",
                "message": "resource not found",
                "request_id": request.state.request_id,
                "details": {},
            },
        )

    api = APIRouter(prefix="/api/v1")

    @api.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    for feature in features:
        api.include_router(feature.router)
    app.include_router(api)
    return app
```

`runs/service.py` defines `RunsService.list(cursor, limit)`, `get(run_id)` and `artifacts(run_id)`,
maps ORM rows to `Page[RunDetail]`, and never exposes `request_payload` or internal stack text. It also
implements this shared submit port:

```python
# backend/app/ports/runs.py
from datetime import datetime
from typing import Protocol

from backend.app.contracts.runs import RunKind, RunRef


class RunSubmitter(Protocol):
    def submit(
        self,
        kind: RunKind,
        payload: dict[str, object],
        idempotency_key: str | None,
        submitted_at: datetime,
    ) -> RunRef: ...
```

`RunsService.submit` opens one transaction, calls `RunRepository.submit`, and maps the row to a
`RunRef` whose self link is `/api/v1/runs/{run_id}`.
`runs/router.py` exposes `GET /runs`, `GET /runs/{run_id}` and
`GET /runs/{run_id}/artifacts`. `runs/module.py` exposes
`build_runs_feature(service: RunsService) -> FeatureModule`; it builds the router with a closure around the
injected service and supplies no job handlers.

`default_features.py` must expose
`build_default_features(dependencies: ApplicationDependencies) -> tuple[FeatureModule, ...]` and initially
return only `build_runs_feature(dependencies.runs_service)`. `ApplicationDependencies` contains Settings,
session factory, `RunsService` and `V212StrategyEngine`. `build_worker()` builds a `HandlerRegistry` from
the already-built modules; it does not import feature internals.

```python
# backend/app/main.py
import uvicorn

from backend.app.bootstrap.application import build_application
from backend.app.bootstrap.settings import Settings

app = build_application()


def run() -> None:
    settings = Settings()
    uvicorn.run(app, host=settings.bind_host, port=settings.bind_port)
```

- [ ] **Step 4: 验证 API、CORS 和所有业务 path 前缀**

Run: `python -m pytest backend/tests/api/test_foundation_api.py -q`
Expected: 全部 PASS；OpenAPI 业务 paths 全以 `/api/v1/` 开头。

- [ ] **Step 5: 提交应用壳**

```bash
git add backend/app/bootstrap backend/app/features/runs backend/app/main.py backend/tests/api
git commit -m "feat: expose durable runs through an injectable API shell"
```

### Task 12: 建立可注册 React/Vite Web 壳

**Files:**
- Create: `web/package.json`
- Create: `web/tsconfig.json`
- Create: `web/vite.config.ts`
- Create: `web/index.html`
- Create: `web/src/main.tsx`
- Create: `web/src/app/App.tsx`
- Create: `web/src/app/featureRegistry.ts`
- Create: `web/src/app/defaultFeatures.tsx`
- Create: `web/src/app/styles.css`
- Create: `web/src/features/runs/RunsPage.tsx`
- Create: `web/src/features/runs/index.tsx`
- Create: `web/src/test/setup.ts`
- Test: `web/src/app/App.test.tsx`

- [ ] **Step 1: 写失败的动态导航 test**

```tsx
// web/src/app/App.test.tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it } from "vitest";

import { App } from "./App";
import type { FeatureDefinition } from "./featureRegistry";

it("builds navigation and routes from feature definitions", () => {
  const features: FeatureDefinition[] = [
    { id: "probe", path: "/probe", label: "探针", element: <div>功能已注册</div> },
  ];
  render(
    <MemoryRouter initialEntries={["/probe"]}>
      <App features={features} />
    </MemoryRouter>,
  );
  expect(screen.getByRole("link", { name: "探针" })).toBeInTheDocument();
  expect(screen.getByText("功能已注册")).toBeInTheDocument();
});
```

- [ ] **Step 2: 安装依赖并确认 App 缺失**

Run: `cd web && npm install && npm test -- --run src/app/App.test.tsx`
Expected: FAIL，包含 `Failed to resolve import "./App"`。

- [ ] **Step 3: 实现 Web feature contract 与应用壳**

```json
// web/package.json
{
  "name": "da-platform-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "typecheck": "tsc -b --pretty false",
    "test": "vitest",
    "generate:api": "openapi-typescript ../contracts/openapi.json -o src/generated/schema.d.ts"
  },
  "dependencies": {
    "openapi-fetch": "^0.13.4",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.2"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.6.3",
    "@testing-library/react": "^16.1.0",
    "@types/node": "^22.7.4",
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "jsdom": "^25.0.1",
    "openapi-typescript": "^7.4.2",
    "typescript": "^5.6.2",
    "vite": "^5.4.8",
    "vitest": "^2.1.2"
  }
}
```

```tsx
// web/src/app/featureRegistry.ts
import type { ReactNode } from "react";

export interface FeatureDefinition {
  id: string;
  path: string;
  label: string;
  element: ReactNode;
}
```

```json
// web/tsconfig.json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "allowJs": false,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "forceConsistentCasingInFileNames": true,
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "baseUrl": ".",
    "paths": {"@/*": ["src/*"]}
  },
  "include": ["src", "vite.config.ts", "playwright.config.ts"]
}
```

```typescript
// web/vite.config.ts
import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {"@": fileURLToPath(new URL("./src", import.meta.url))},
  },
  server: {
    host: "127.0.0.1",
    proxy: {"/api": "http://127.0.0.1:8000"},
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});
```

```tsx
// web/src/app/App.tsx
import { NavLink, Navigate, Route, Routes } from "react-router-dom";

import type { FeatureDefinition } from "./featureRegistry";
import "./styles.css";

export function App({ features }: { features: readonly FeatureDefinition[] }) {
  const first = features[0]?.path ?? "/unavailable";
  return (
    <div className="shell">
      <aside>
        <h1>四维盾剑 DA</h1>
        <nav>
          {features.map((feature) => (
            <NavLink key={feature.id} to={feature.path}>{feature.label}</NavLink>
          ))}
        </nav>
      </aside>
      <main>
        <Routes>
          <Route path="/" element={<Navigate to={first} replace />} />
          {features.map((feature) => (
            <Route key={feature.id} path={feature.path} element={feature.element} />
          ))}
          <Route path="*" element={<h2>页面不存在</h2>} />
        </Routes>
      </main>
    </div>
  );
}
```

`features/runs/index.tsx` exports `runsFeature: FeatureDefinition` with id `runs`, path `/runs`,
label `运行中心` and `<RunsPage />`. `defaultFeatures.tsx` exports
`defaultFeatures = [runsFeature] as const`. `main.tsx` renders `App` in `BrowserRouter`.
`RunsPage` renders heading, empty state and refresh button without mock results. Vite proxies `/api` to
`http://127.0.0.1:8000`; Vitest uses jsdom and imports `@testing-library/jest-dom/vitest`.

- [ ] **Step 4: 运行前端单测、typecheck 和 build**

Run: `cd web && npm test -- --run && npm run typecheck && npm run build`
Expected: tests PASS，TypeScript 零错误，`web/dist/index.html` 存在。

- [ ] **Step 5: 提交 Web 壳**

```bash
git add web
git commit -m "feat: provide a feature-registered web application shell"
```

### Task 13: 导出 OpenAPI、生成 TypeScript 并冻结示例

**Files:**
- Create: `tools/__init__.py`
- Create: `tools/export_openapi.py`
- Create: `tools/check_openapi.py`
- Create: `contracts/openapi.json`
- Create: `contracts/examples/run-ref.json`
- Create: `contracts/examples/error-response.json`
- Create: `contracts/examples/page-runs.json`
- Create: `web/src/generated/schema.d.ts`
- Create: `web/src/shared/api/client.ts`
- Test: `backend/tests/contracts/test_openapi_export.py`

- [ ] **Step 1: 写失败的 canonical export test**

```python
# backend/tests/contracts/test_openapi_export.py
import json
from pathlib import Path

from tools.export_openapi import render_openapi


def test_checked_in_openapi_is_canonical() -> None:
    checked = Path("contracts/openapi.json").read_text(encoding="utf-8")
    assert checked == render_openapi()
    document = json.loads(checked)
    assert "/api/v1/health/live" in document["paths"]
    assert "/api/v1/runs/{run_id}" in document["paths"]
```

- [ ] **Step 2: 运行测试并确认工具缺失**

Run: `python -m pytest backend/tests/contracts/test_openapi_export.py -q`
Expected: FAIL，包含 `No module named 'tools.export_openapi'`。

- [ ] **Step 3: 实现确定性导出和客户端**

```python
# tools/export_openapi.py
import json

from backend.app.bootstrap.application import build_application


def render_openapi() -> str:
    return json.dumps(
        build_application().openapi(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def main() -> None:
    with open("contracts/openapi.json", "w", encoding="utf-8") as target:
        target.write(render_openapi())


if __name__ == "__main__":
    main()
```

```python
# tools/check_openapi.py
from pathlib import Path

from tools.export_openapi import render_openapi


def main() -> None:
    if Path("contracts/openapi.json").read_text(encoding="utf-8") != render_openapi():
        raise SystemExit("contracts/openapi.json is stale; run python -m tools.export_openapi")


if __name__ == "__main__":
    main()
```

```typescript
// web/src/shared/api/client.ts
import createClient from "openapi-fetch";
import type { paths } from "../../generated/schema";

export const apiClient = createClient<paths>({ baseUrl: "/api/v1" });
```

Run:

```bash
python -m tools.export_openapi
cd web
npm run generate:api
```

Expected: OpenAPI export exits 0, generated TypeScript exits 0, and the generated files are unchanged
when the command is repeated.

Write exact example payloads:

```json
{"run_id":"00000000-0000-0000-0000-000000000001","kind":"backtest","status":"queued","submitted_at":"2026-07-16T09:30:00+08:00","links":{"self":"/api/v1/runs/00000000-0000-0000-0000-000000000001","artifacts":null,"result":null}}
```

```json
{"code":"NOT_FOUND","message":"resource not found","request_id":"req-1","details":{}}
```

```json
{"items":[],"next_cursor":null}
```

- [ ] **Step 4: 验证后端与生成文件无差异**

Run: `python -m pytest backend/tests/contracts -q && python -m tools.check_openapi && cd web && npm run generate:api && git diff --exit-code -- ../contracts/openapi.json src/generated/schema.d.ts`
Expected:
- pytest 输出 `N passed` 且退出码为 0；
- `python -m tools.check_openapi` 退出码为 0；
- `npm run generate:api` 退出码为 0；
- `git diff --exit-code` 无输出且退出码为 0；
- `contracts/openapi.json` 与 `web/src/generated/schema.d.ts` 没有未提交差异。

- [ ] **Step 5: 提交跨端契约**

```bash
git add tools contracts web/src/generated web/src/shared backend/tests/contracts
git commit -m "feat: generate the web client from the authoritative API contract"
```

### Task 14: 固化 CI 顺序和波次 0 验收

**Files:**
- Create: `Makefile`
- Create: `.github/workflows/ci.yml`
- Create: `docs/development.md`
- Test: `backend/tests/test_independent_paths.py`

- [ ] **Step 1: 写 runtime 独立性扫描 test**

```python
# backend/tests/test_independent_paths.py
from pathlib import Path


def test_runtime_files_do_not_reference_la() -> None:
    roots = (Path("backend"), Path("web/src"), Path("strategies/manifest.json"))
    forbidden = ("/Users/bujiatang/workspace/LA", "../LA/")
    matches: list[str] = []
    for root in roots:
        paths = [root] if root.is_file() else list(root.rglob("*"))
        for path in paths:
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="ignore")
                matches.extend(f"{path}: {value}" for value in forbidden if value in text)
    assert matches == []


def test_repository_contains_no_symlinks() -> None:
    assert [str(path) for path in Path(".").rglob("*") if path.is_symlink()] == []
```

- [ ] **Step 2: 运行扫描并确认 CI 尚不存在**

Run: `python -m pytest backend/tests/test_independent_paths.py -q && test -f .github/workflows/ci.yml`
Expected: `2 passed`，整个命令因 CI 文件缺失退出 1。

- [ ] **Step 3: 写固定验证命令和 CI**

```make
.PHONY: lint test test-postgres contract web verify
lint:
	python -m ruff check backend tools
	python -m ruff format --check backend tools
	python -m mypy backend tools
test:
	python -m pytest -m "not postgres" --cov=backend.app
test-postgres:
	TEST_DATABASE_URL=postgresql+psycopg://da:da@127.0.0.1:55433/da_test \
		python -m pytest -m postgres
contract:
	python -m tools.check_openapi
	cd web && npm run generate:api
	git diff --exit-code -- contracts/openapi.json web/src/generated/schema.d.ts
web:
	cd web && npm run typecheck
	cd web && npm test -- --run
	cd web && npm run build
verify: lint test test-postgres contract web
```

`ci.yml` runs on push and pull request, uses Python 3.11, Node 20 and PostgreSQL 16, installs
`.[dev]` and `npm ci`, then runs in this exact order:

```yaml
- run: python -m ruff check backend tools
- run: python -m ruff format --check backend tools
- run: python -m mypy backend tools
- run: python -m pytest -m "not postgres"
- run: python -m pytest -m postgres
  env:
    TEST_DATABASE_URL: postgresql+psycopg://da:da@127.0.0.1:5432/da_test
- run: python -m tools.check_openapi
- run: npm run generate:api
  working-directory: web
- run: git diff --exit-code -- contracts/openapi.json web/src/generated/schema.d.ts
- run: npm run typecheck
  working-directory: web
- run: npm test -- --run
  working-directory: web
- run: npm run build
  working-directory: web
```

`docs/development.md` documents only DA-local startup: PostgreSQL, `alembic upgrade head`, `da-api`,
`da-worker`, Vite and `make verify`。它明确 feature Agent 导出 build function，由协调 Agent
修改全局注册文件。

- [ ] **Step 4: 执行波次 0 全量验收**

Run: `make verify`
Expected: Ruff、mypy、pytest unit、PostgreSQL integration、OpenAPI check、TypeScript generation、
`git diff --exit-code`（退出码 0 且无输出）、Vitest、TypeScript 和 Vite build 全部退出 0；测试报告显示
所有用例通过。

- [ ] **Step 5: 提交 CI 与文档**

```bash
git add Makefile .github docs/development.md backend/tests/test_independent_paths.py
git commit -m "ci: enforce independent and contract-synchronized DA builds"
```

## 完成门槛

- `make verify` 全绿；run 状态跨 API/worker 重启保留。
- `V212StrategyEngine` 是 P/F/R/T/V/S、市场状态、风险仓位和组合约束的唯一实现。
- `contracts/openapi.json` 是前端类型的唯一来源，Web 不手写后端 DTO。
- 后续 feature 只导出 build function，不改全局入口、迁移链或 generated 文件。
- runtime、测试和默认配置不存在 LA 绝对路径、软链接或跨项目 import。
- V2.12 登记哈希固定为
  `a88acc752be00783b9462368d57e647d0033563467e3ed5c364c7a501ca5a026`。
