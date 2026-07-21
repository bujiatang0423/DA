# PIT Research Warehouse and Legacy Opening Balance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 00 已冻结 V2.12 的基础上建立统一时点快照端口、研究级数据适配与血缘，并把 LA 持仓以可审计的 `legacy_opening_balance` 一次性只读导入。

**Architecture:** DA 只消费 `PointInTimeWarehouse.snapshot()`，研究供应商先转换成统一时点记录，再由同一个快照组装器执行时间门禁和生成 manifest。Legacy 导入分为“检查—原始字节冻结—持久化—生成启动日 opening lots”，保留异常原值且绝不生成导入日前成交或收益。

**Tech Stack:** Python 3.11、dataclasses、Protocol、SQLAlchemy 2、Alembic、PostgreSQL、pytest、pytest-postgresql（沿用 00-foundation-contracts 建立的工具链）

---

## 依赖、所有权与交付边界

- 阻塞依赖：先完成 `2026-07-16-00-foundation-contracts.md`，其中必须已存在
  `backend/app/contracts/grades.py` 的 `DataGrade`、`strategies/manifest.json`、
  `backend/app/core/strategy/registry.py`、`backend/app/infrastructure/persistence/models.py`
  的 `Base`、Alembic revision `20260716_0001` 和可运行的 `python -m pytest`。
- 00 是策略冻结、共享 contracts 和 `backend/app/core/strategy/**` 的唯一所有者。本计划只消费
  `StrategyRegistry.from_manifest(...).load("v2.12")`，不复制策略、不另建 registry。01 只提供
  唯一的确定性输入构建器；最终状态机、风险、仓位、P/F/R/T/V/S 合成与交易决定仍由 00
  的 `V212StrategyEngine` 独占。
- 本计划独占：`backend/app/core/market/**`、`backend/app/ports/point_in_time.py`、
  `backend/app/infrastructure/market/**`、`backend/app/features/legacy_import/**`、
  `backend/app/core/portfolio/models.py`、`backend/app/ports/portfolio.py` 及对应测试。
- 迁移文件 `backend/migrations/versions/20260716_0002_pit_legacy.py` 只能由协调 Agent 创建；
  其他 Agent 不修改 `down_revision`、`backend/app/main.py`、根路由或 OpenAPI。
- LA 仅在执行显式导入命令时作为用户给出的只读源目录。DA 的启动、测试、Web 和 worker
  不读取 LA，不创建软链接，不注入跨项目 `PYTHONPATH`。
- 本计划完成后可并行启动 02、03 和 04；05 必须等 04 的研究回测闭环完成。

## 文件职责图

```text
backend/app/core/market/pit_models.py   # 时点记录、质量、快照和 scope 的稳定类型
backend/app/core/market/snapshot.py     # available_at 门禁、分组和 manifest 哈希
backend/app/ports/point_in_time.py      # 唯一快照读取端口及研究源端口
backend/app/infrastructure/market/
├── research_source.py                  # 把研究供应商行转换为 research 记录
├── research_warehouse.py               # 聚合研究源并返回统一快照
├── build.py                            # build_point_in_time_warehouse 组合入口
└── lineage_repository.py               # 批次、源产物和输入 manifest 持久化
backend/app/core/portfolio/models.py    # DA 组合快照与 legacy opening lot 语义
backend/app/ports/portfolio.py          # PortfolioReader/OpeningBalanceWriter 端口
backend/app/features/legacy_import/
├── models.py                           # 导入文件、行、质量标签和报告类型
├── inspect.py                          # 索引/文件/checksum/buy_date 质量检查
├── service.py                          # 原始字节冻结、幂等导入和 opening balance
├── repository.py                       # PostgreSQL 导入仓储
└── cli.py                              # 唯一允许显式接受 LA 路径的命令
backend/app/infrastructure/persistence/
├── pit_rows.py                         # 血缘 ORM 表
└── legacy_rows.py                      # legacy 与 opening positions ORM 表
```

### Task 1: 冻结统一 PIT 类型、端口和未来时间门禁

**Files:**
- Create: `backend/app/core/market/pit_models.py`
- Create: `backend/app/core/market/snapshot.py`
- Create: `backend/app/ports/point_in_time.py`
- Create: `backend/tests/core/market/test_snapshot.py`

- [ ] **Step 1: 写快照分组、哈希确定性和未来记录拒绝测试**

```python
# backend/tests/core/market/test_snapshot.py
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.contracts.grades import DataGrade
from backend.app.core.market.pit_models import (
    DataKind,
    LineageRef,
    SnapshotScope,
    TemporalRecord,
)
from backend.app.core.market.snapshot import FutureDataError, assemble_snapshot


AS_OF = datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc)


def record(record_id: str, entity_id: str, available_at: datetime) -> TemporalRecord:
    return TemporalRecord(
        record_id=record_id,
        kind=DataKind.DAILY_BAR_RAW,
        entity_id=entity_id,
        event_time=AS_OF - timedelta(minutes=30),
        observed_at=available_at,
        available_at=available_at,
        source_artifact_hash="a" * 64,
        payload={"close": "10.00"},
    )


def test_snapshot_groups_market_and_security_records_deterministically() -> None:
    lineage = (LineageRef("batch-1", "fixture", "a" * 64),)
    first = assemble_snapshot(
        as_of_time=AS_OF,
        scope=SnapshotScope(("000001.SZ",), required_kinds=(DataKind.DAILY_BAR_RAW,)),
        data_grade=DataGrade.RESEARCH,
        records=(record("2", "000001.SZ", AS_OF), record("1", "MARKET:CSI_ALL", AS_OF)),
        lineage=lineage,
        quality_issues=(),
    )
    second = assemble_snapshot(
        as_of_time=AS_OF,
        scope=first.scope,
        data_grade=DataGrade.RESEARCH,
        records=tuple(
            reversed(
                (
                    record("2", "000001.SZ", AS_OF),
                    record("1", "MARKET:CSI_ALL", AS_OF),
                )
            )
        ),
        lineage=lineage,
        quality_issues=(),
    )

    assert len(first.market_inputs) == 1
    assert first.security_observations[0].security_id == "000001.SZ"
    assert first.manifest_hash == second.manifest_hash


def test_snapshot_rejects_data_available_after_as_of() -> None:
    with pytest.raises(FutureDataError, match="future record: poison"):
        assemble_snapshot(
            as_of_time=AS_OF,
            scope=SnapshotScope(("000001.SZ",)),
            data_grade=DataGrade.RESEARCH,
            records=(record("poison", "000001.SZ", AS_OF + timedelta(seconds=1)),),
            lineage=(),
            quality_issues=(),
        )
```

- [ ] **Step 2: 运行测试，确认缺少 PIT 类型**

Run: `python -m pytest backend/tests/core/market/test_snapshot.py -q`

Expected: FAIL，错误包含 `No module named 'backend.app.core.market.pit_models'`。

- [ ] **Step 3: 创建稳定类型和窄端口**

```python
# backend/app/core/market/pit_models.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Mapping

from backend.app.contracts.grades import DataGrade


class DataKind(StrEnum):
    SECURITY_MASTER = "security_master"
    SECURITY_STATUS = "security_status"
    TRADING_CALENDAR = "trading_calendar"
    REALTIME_QUOTE = "realtime_quote"
    DAILY_BAR_RAW = "daily_bar_raw"
    INDEX_DAILY_BAR = "index_daily_bar"
    CORPORATE_ACTION = "corporate_action"
    ADJUSTMENT_FACTOR = "adjustment_factor"
    INDUSTRY_MEMBERSHIP = "industry_membership"
    THEME_MEMBERSHIP = "theme_membership"
    FINANCIAL_DISCLOSURE = "financial_disclosure"
    FINANCIAL_FACT = "financial_fact"
    POLICY_DOCUMENT = "policy_document"
    LLM_FACTOR = "llm_factor"
    FEE_SCHEDULE = "fee_schedule"


class QualitySeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class SnapshotScope:
    security_ids: tuple[str, ...] = ()
    required_kinds: tuple[DataKind, ...] = ()
    history_start: datetime | None = None

    @classmethod
    def candidate_recommendation(cls) -> "SnapshotScope":
        return cls(
            required_kinds=(
                DataKind.SECURITY_MASTER,
                DataKind.SECURITY_STATUS,
                DataKind.TRADING_CALENDAR,
                DataKind.REALTIME_QUOTE,
                DataKind.DAILY_BAR_RAW,
                DataKind.INDEX_DAILY_BAR,
                DataKind.ADJUSTMENT_FACTOR,
                DataKind.INDUSTRY_MEMBERSHIP,
                DataKind.THEME_MEMBERSHIP,
                DataKind.FINANCIAL_DISCLOSURE,
                DataKind.FINANCIAL_FACT,
                DataKind.POLICY_DOCUMENT,
                DataKind.LLM_FACTOR,
                DataKind.FEE_SCHEDULE,
            )
        )

    @classmethod
    def holding_analysis(cls, security_ids: tuple[str, ...]) -> "SnapshotScope":
        scope = cls.candidate_recommendation()
        return cls(security_ids, scope.required_kinds)

    @classmethod
    def backtest(
        cls,
        security_ids: tuple[str, ...],
        history_start: datetime,
    ) -> "SnapshotScope":
        return cls(
            security_ids,
            (
                DataKind.SECURITY_MASTER,
                DataKind.SECURITY_STATUS,
                DataKind.TRADING_CALENDAR,
                DataKind.DAILY_BAR_RAW,
                DataKind.INDEX_DAILY_BAR,
                DataKind.CORPORATE_ACTION,
                DataKind.ADJUSTMENT_FACTOR,
                DataKind.INDUSTRY_MEMBERSHIP,
                DataKind.THEME_MEMBERSHIP,
                DataKind.FINANCIAL_DISCLOSURE,
                DataKind.FINANCIAL_FACT,
                DataKind.POLICY_DOCUMENT,
                DataKind.LLM_FACTOR,
                DataKind.FEE_SCHEDULE,
            ),
            history_start,
        )


@dataclass(frozen=True)
class TemporalRecord:
    record_id: str
    kind: DataKind
    entity_id: str
    event_time: datetime
    observed_at: datetime
    available_at: datetime
    source_artifact_hash: str
    payload: Mapping[str, object]


@dataclass(frozen=True)
class LineageRef:
    batch_id: str
    provider: str
    source_artifact_hash: str


@dataclass(frozen=True)
class QualityIssue:
    code: str
    severity: QualitySeverity
    dataset: str
    entity_id: str | None
    detail: str


@dataclass(frozen=True)
class SnapshotQuality:
    issues: tuple[QualityIssue, ...]

    @property
    def has_errors(self) -> bool:
        return any(issue.severity is QualitySeverity.ERROR for issue in self.issues)


@dataclass(frozen=True)
class SecurityObservation:
    security_id: str
    records: tuple[TemporalRecord, ...]

    def records_of(self, kind: DataKind) -> tuple[TemporalRecord, ...]:
        return tuple(record for record in self.records if record.kind is kind)


@dataclass(frozen=True)
class PointInTimeSnapshot:
    as_of_time: datetime
    scope: SnapshotScope
    data_grade: DataGrade
    market_inputs: tuple[TemporalRecord, ...]
    security_observations: tuple[SecurityObservation, ...]
    quality: SnapshotQuality
    lineage: tuple[LineageRef, ...]
    manifest_hash: str
```

```python
# backend/app/ports/point_in_time.py
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from backend.app.core.market.pit_models import PointInTimeSnapshot, SnapshotScope


class PointInTimeWarehouse(Protocol):
    def snapshot(
        self,
        *,
        as_of_time: datetime,
        scope: SnapshotScope,
    ) -> PointInTimeSnapshot: ...
```

- [ ] **Step 4: 实现唯一快照组装器**

```python
# backend/app/core/market/snapshot.py
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from backend.app.contracts.grades import DataGrade
from backend.app.core.market.pit_models import (
    LineageRef,
    PointInTimeSnapshot,
    QualityIssue,
    SecurityObservation,
    SnapshotQuality,
    SnapshotScope,
    TemporalRecord,
)


class FutureDataError(ValueError):
    pass


def _canonical_record(record: TemporalRecord) -> dict[str, object]:
    return {
        "record_id": record.record_id,
        "kind": record.kind.value,
        "entity_id": record.entity_id,
        "event_time": record.event_time.isoformat(),
        "observed_at": record.observed_at.isoformat(),
        "available_at": record.available_at.isoformat(),
        "source_artifact_hash": record.source_artifact_hash,
        "payload": record.payload,
    }


def assemble_snapshot(
    *,
    as_of_time: datetime,
    scope: SnapshotScope,
    data_grade: DataGrade,
    records: tuple[TemporalRecord, ...],
    lineage: tuple[LineageRef, ...],
    quality_issues: tuple[QualityIssue, ...],
) -> PointInTimeSnapshot:
    if as_of_time.tzinfo is None:
        raise ValueError("as_of_time must be timezone-aware")
    ordered = tuple(
        sorted(records, key=lambda item: (item.entity_id, item.kind.value, item.record_id))
    )
    for record in ordered:
        if record.available_at.tzinfo is None:
            raise ValueError(f"available_at must be timezone-aware: {record.record_id}")
        if record.available_at > as_of_time:
            raise FutureDataError(f"future record: {record.record_id}")
    market = tuple(record for record in ordered if record.entity_id.startswith("MARKET:"))
    securities = tuple(
        SecurityObservation(
            security_id,
            tuple(record for record in ordered if record.entity_id == security_id),
        )
        for security_id in sorted(
            {
                record.entity_id
                for record in ordered
                if not record.entity_id.startswith("MARKET:")
            }
        )
    )
    manifest_payload = {
        "as_of_time": as_of_time.isoformat(),
        "scope": {
            "security_ids": scope.security_ids,
            "required_kinds": [kind.value for kind in scope.required_kinds],
            "history_start": scope.history_start.isoformat() if scope.history_start else None,
        },
        "data_grade": data_grade.value,
        "records": [_canonical_record(record) for record in ordered],
        "lineage": [
            ref.__dict__
            for ref in sorted(lineage, key=lambda item: item.source_artifact_hash)
        ],
    }
    canonical = json.dumps(
        manifest_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return PointInTimeSnapshot(
        as_of_time=as_of_time,
        scope=scope,
        data_grade=data_grade,
        market_inputs=market,
        security_observations=securities,
        quality=SnapshotQuality(quality_issues),
        lineage=lineage,
        manifest_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )
```

- [ ] **Step 5: 运行测试并提交**

Run: `python -m pytest backend/tests/core/market/test_snapshot.py -q`

Expected: `2 passed`。

```bash
git add backend/app/core/market backend/app/ports/point_in_time.py backend/tests/core/market
git commit -m "feat: centralize point-in-time snapshot boundaries"
```

### Task 2: 建立 research source 契约和聚合仓库

**Files:**
- Create: `backend/app/infrastructure/market/research_source.py`
- Create: `backend/app/infrastructure/market/research_warehouse.py`
- Create: `backend/tests/infrastructure/market/test_research_warehouse.py`

- [ ] **Step 1: 写 research 降级标签和源聚合测试**

```python
# backend/tests/infrastructure/market/test_research_warehouse.py
from datetime import datetime, timezone

from backend.app.contracts.grades import DataGrade
from backend.app.core.market.pit_models import DataKind, LineageRef, SnapshotScope, TemporalRecord
from backend.app.infrastructure.market.research_source import ResearchBatch
from backend.app.infrastructure.market.research_warehouse import ResearchPointInTimeWarehouse


AS_OF = datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc)


class FakeResearchSource:
    provider = "fake"

    def fetch(self, *, as_of_time: datetime, scope: SnapshotScope) -> ResearchBatch:
        record = TemporalRecord(
            "bar-1",
            DataKind.DAILY_BAR_RAW,
            scope.security_ids[0],
            AS_OF,
            AS_OF,
            AS_OF,
            "b" * 64,
            {"open": "10", "close": "11", "volume": "1000"},
        )
        return ResearchBatch((record,), (LineageRef("batch-1", self.provider, "b" * 64),))


def test_research_warehouse_never_claims_pit_verified() -> None:
    warehouse = ResearchPointInTimeWarehouse((FakeResearchSource(),))

    snapshot = warehouse.snapshot(
        as_of_time=AS_OF,
        scope=SnapshotScope(("000001.SZ",), (DataKind.DAILY_BAR_RAW,)),
    )

    assert snapshot.data_grade is DataGrade.RESEARCH
    assert snapshot.quality.issues[0].code == "RECONSTRUCTED_HISTORY"
    assert snapshot.lineage[0].provider == "fake"
```

- [ ] **Step 2: 运行测试，确认 research 仓库尚不存在**

Run: `python -m pytest backend/tests/infrastructure/market/test_research_warehouse.py -q`

Expected: FAIL，错误包含 `No module named 'backend.app.infrastructure.market.research_source'`。

- [ ] **Step 3: 实现供应商无关的 research source 契约**

```python
# backend/app/infrastructure/market/research_source.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from backend.app.core.market.pit_models import LineageRef, SnapshotScope, TemporalRecord


@dataclass(frozen=True)
class ResearchBatch:
    records: tuple[TemporalRecord, ...]
    lineage: tuple[LineageRef, ...]


class ResearchSource(Protocol):
    provider: str

    def fetch(self, *, as_of_time: datetime, scope: SnapshotScope) -> ResearchBatch: ...
```

- [ ] **Step 4: 实现聚合、缺失检查和永久 research 标记**

```python
# backend/app/infrastructure/market/research_warehouse.py
from __future__ import annotations

from datetime import datetime

from backend.app.contracts.grades import DataGrade
from backend.app.core.market.pit_models import (
    PointInTimeSnapshot,
    QualityIssue,
    QualitySeverity,
    SnapshotScope,
)
from backend.app.core.market.snapshot import assemble_snapshot
from backend.app.infrastructure.market.research_source import ResearchSource


class ResearchPointInTimeWarehouse:
    def __init__(self, sources: tuple[ResearchSource, ...]) -> None:
        self._sources = sources

    def snapshot(
        self,
        *,
        as_of_time: datetime,
        scope: SnapshotScope,
    ) -> PointInTimeSnapshot:
        batches = tuple(
            source.fetch(as_of_time=as_of_time, scope=scope)
            for source in self._sources
        )
        records = tuple(record for batch in batches for record in batch.records)
        lineage = tuple(ref for batch in batches for ref in batch.lineage)
        present = {record.kind for record in records}
        issues = [
            QualityIssue(
                "RECONSTRUCTED_HISTORY",
                QualitySeverity.WARNING,
                "snapshot",
                None,
                "供应商当前重建历史；available_at 是研究代理口径，不能用于正式历史验证",
            )
        ]
        for missing in sorted(set(scope.required_kinds) - present, key=lambda kind: kind.value):
            issues.append(
                QualityIssue(
                    "REQUIRED_DATASET_MISSING",
                    QualitySeverity.ERROR,
                    missing.value,
                    None,
                    f"required dataset missing: {missing.value}",
                )
            )
        return assemble_snapshot(
            as_of_time=as_of_time,
            scope=scope,
            data_grade=DataGrade.RESEARCH,
            records=records,
            lineage=lineage,
            quality_issues=tuple(issues),
        )
```

- [ ] **Step 5: 运行测试并提交**

Run: `python -m pytest backend/tests/infrastructure/market/test_research_warehouse.py -q`

Expected: `1 passed`。

```bash
git add backend/app/infrastructure/market/research_source.py backend/app/infrastructure/market/research_warehouse.py backend/tests/infrastructure/market/test_research_warehouse.py
git commit -m "feat: label reconstructed provider history as research data"
```

### Task 3: 将市场 Provider 输出适配为时点记录并持久化血缘

**Files:**
- Create: `backend/app/infrastructure/market/provider_source.py`
- Create: `backend/app/infrastructure/market/research_providers.py`
- Create: `backend/app/infrastructure/market/build.py`
- Create: `backend/app/infrastructure/market/lineage_repository.py`
- Create: `backend/app/infrastructure/persistence/pit_rows.py`
- Create: `backend/migrations/versions/20260716_0002_pit_legacy.py`
- Create: `backend/tests/infrastructure/market/test_provider_source_contract.py`
- Create: `backend/tests/integration/test_lineage_repository.py`

- [ ] **Step 1: 写 Provider 共同契约测试，固定未复权价格和研究可用时间代理**

```python
# backend/tests/infrastructure/market/test_provider_source_contract.py
from datetime import date, datetime, time, timezone
from decimal import Decimal

import pytest

from backend.app.core.market.pit_models import DataKind, SnapshotScope
from backend.app.infrastructure.market.provider_source import ProviderBar, ProviderResearchSource


class FakeDailyBarProvider:
    provider_name = "fake-bars"

    def daily_bars(self, security_id: str, start: date, end: date) -> tuple[ProviderBar, ...]:
        return (
            ProviderBar(
                security_id,
                end,
                Decimal("10"),
                Decimal("11"),
                Decimal("9"),
                Decimal("10.5"),
                1000,
            ),
        )


@pytest.mark.parametrize("provider_name", ["akshare", "baostock", "sina", "fake-bars"])
def test_each_research_provider_uses_the_same_record_contract(provider_name: str) -> None:
    provider = FakeDailyBarProvider()
    provider.provider_name = provider_name
    source = ProviderResearchSource(provider, timezone.utc)
    as_of = datetime(2024, 1, 2, 16, 0, tzinfo=timezone.utc)

    batch = source.fetch(
        as_of_time=as_of,
        scope=SnapshotScope(("000001.SZ",), (DataKind.DAILY_BAR_RAW,)),
    )

    record = batch.records[0]
    assert record.kind is DataKind.DAILY_BAR_RAW
    assert record.payload["price_adjustment"] == "none"
    assert record.available_at == datetime.combine(date(2024, 1, 2), time(15, 30), timezone.utc)
    assert batch.lineage[0].provider == provider_name
```

- [ ] **Step 2: 实现纯适配层；AkShare/BaoStock/Sina 迁移代码只能实现此 Provider 协议**

```python
# backend/app/infrastructure/market/provider_source.py
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from decimal import Decimal
from typing import Protocol

from backend.app.core.market.pit_models import DataKind, LineageRef, SnapshotScope, TemporalRecord
from backend.app.infrastructure.market.research_source import ResearchBatch


@dataclass(frozen=True)
class ProviderBar:
    security_id: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


class DailyBarProvider(Protocol):
    provider_name: str

    def daily_bars(self, security_id: str, start: date, end: date) -> tuple[ProviderBar, ...]: ...


class ProviderResearchSource:
    def __init__(self, provider: DailyBarProvider, strategy_timezone: tzinfo) -> None:
        self.provider = provider
        self._timezone = strategy_timezone

    def fetch(self, *, as_of_time: datetime, scope: SnapshotScope) -> ResearchBatch:
        start = (scope.history_start or as_of_time - timedelta(days=400)).date()
        rows = tuple(
            bar
            for security_id in scope.security_ids
            for bar in self.provider.daily_bars(security_id, start, as_of_time.date())
        )
        raw = json.dumps(
            [{**bar.__dict__, "trade_date": bar.trade_date.isoformat()} for bar in rows],
            sort_keys=True,
            default=str,
        ).encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        batch_id = f"{self.provider.provider_name}-{digest[:16]}"
        records = tuple(
            TemporalRecord(
                record_id=(
                    f"{self.provider.provider_name}:{bar.security_id}:"
                    f"{bar.trade_date.isoformat()}"
                ),
                kind=DataKind.DAILY_BAR_RAW,
                entity_id=bar.security_id,
                event_time=datetime.combine(bar.trade_date, time(15, 0), self._timezone),
                observed_at=as_of_time,
                available_at=datetime.combine(bar.trade_date, time(15, 30), self._timezone),
                source_artifact_hash=digest,
                payload={
                    "open": str(bar.open),
                    "high": str(bar.high),
                    "low": str(bar.low),
                    "close": str(bar.close),
                    "volume": bar.volume,
                    "price_adjustment": "none",
                },
            )
            for bar in rows
        )
        return ResearchBatch(records, (LineageRef(batch_id, self.provider.provider_name, digest),))
```

同一 Step 创建可由 Settings 直接组合的 concrete providers；两者都请求未复权日线，
`FallbackDailyBarProvider` 只在 primary 返回空时调用 fallback，避免同一行情重复进入快照：

```python
# backend/app/infrastructure/market/research_providers.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from backend.app.infrastructure.market.provider_source import ProviderBar


def _symbol(security_id: str) -> str:
    return security_id.split(".", 1)[0]


@dataclass
class AkShareDailyBarProvider:
    module: Any
    provider_name: str = "akshare"

    def daily_bars(self, security_id: str, start: date, end: date) -> tuple[ProviderBar, ...]:
        frame = self.module.stock_zh_a_hist(
            symbol=_symbol(security_id),
            period="daily",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust="",
        )
        return tuple(
            ProviderBar(
                security_id,
                date.fromisoformat(str(row["日期"])[:10]),
                Decimal(str(row["开盘"])),
                Decimal(str(row["最高"])),
                Decimal(str(row["最低"])),
                Decimal(str(row["收盘"])),
                int(row["成交量"]),
            )
            for _, row in frame.iterrows()
        )


@dataclass
class BaoStockDailyBarProvider:
    module: Any
    provider_name: str = "baostock"

    def daily_bars(self, security_id: str, start: date, end: date) -> tuple[ProviderBar, ...]:
        exchange = security_id.split(".", 1)[1].lower()
        code = f"{exchange}.{_symbol(security_id)}"
        self.module.login()
        try:
            result = self.module.query_history_k_data_plus(
                code,
                "date,open,high,low,close,volume",
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                frequency="d",
                adjustflag="3",
            )
            rows = []
            while result.error_code == "0" and result.next():
                rows.append(dict(zip(result.fields, result.get_row_data())))
        finally:
            self.module.logout()
        return tuple(
            ProviderBar(
                security_id,
                date.fromisoformat(row["date"]),
                Decimal(row["open"]),
                Decimal(row["high"]),
                Decimal(row["low"]),
                Decimal(row["close"]),
                int(row["volume"]),
            )
            for row in rows
            if row["close"]
        )


@dataclass
class FallbackDailyBarProvider:
    primary: Any
    fallback: Any
    provider_name: str = "akshare_with_baostock_fallback"

    def daily_bars(self, security_id: str, start: date, end: date) -> tuple[ProviderBar, ...]:
        primary_rows = self.primary.daily_bars(security_id, start, end)
        return primary_rows or self.fallback.daily_bars(security_id, start, end)
```

- [ ] **Step 3: 写 PostgreSQL 血缘仓储集成测试**

```python
# backend/tests/integration/test_lineage_repository.py
from datetime import datetime, timezone

from backend.app.infrastructure.market.lineage_repository import (
    LineageRepository,
    SourceArtifactInput,
)


def test_source_artifact_is_idempotent_by_sha256(db_session) -> None:
    repository = LineageRepository(db_session)
    item = SourceArtifactInput(
        "akshare",
        "daily_bar_raw",
        "a" * 64,
        datetime.now(timezone.utc),
        "memory://fixture",
    )

    first = repository.register_source(item)
    second = repository.register_source(item)
    db_session.commit()

    assert first == second
    assert repository.count_sources() == 1
```

在 `backend/app/infrastructure/market/build.py` 同步创建唯一研究仓库 factory：

```python
from backend.app.infrastructure.market.research_source import ResearchSource
from backend.app.infrastructure.market.research_warehouse import ResearchPointInTimeWarehouse
from backend.app.ports.point_in_time import PointInTimeWarehouse


def build_point_in_time_warehouse(
    *,
    research_sources: tuple[ResearchSource, ...],
) -> PointInTimeWarehouse:
    return ResearchPointInTimeWarehouse(research_sources)
```

- [ ] **Step 4: 创建血缘 ORM、仓储和协调 Agent 独占迁移**

```python
# backend/app/infrastructure/persistence/pit_rows.py
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.infrastructure.persistence.models import Base


class IngestBatchRow(Base):
    __tablename__ = "ingest_batches"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceArtifactRow(Base):
    __tablename__ = "source_artifacts"
    __table_args__ = (UniqueConstraint("sha256", name="uq_source_artifacts_sha256"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset: Mapped[str] = mapped_column(String(64), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_uri: Mapped[str] = mapped_column(String(512), nullable=False)


class StrategyInputManifestRow(Base):
    __tablename__ = "strategy_input_manifests"
    manifest_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    as_of_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_grade: Mapped[str] = mapped_column(String(32), nullable=False)
    artifact_count: Mapped[int] = mapped_column(Integer, nullable=False)
```

```python
# backend/app/infrastructure/market/lineage_repository.py
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.infrastructure.persistence.pit_rows import SourceArtifactRow


@dataclass(frozen=True)
class SourceArtifactInput:
    provider: str
    dataset: str
    sha256: str
    observed_at: datetime
    source_uri: str


class LineageRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def register_source(self, item: SourceArtifactInput) -> int:
        existing = self._session.scalar(
            select(SourceArtifactRow).where(SourceArtifactRow.sha256 == item.sha256)
        )
        if existing is not None:
            return existing.id
        row = SourceArtifactRow(**item.__dict__)
        self._session.add(row)
        self._session.flush()
        return row.id

    def count_sources(self) -> int:
        return int(self._session.scalar(select(func.count()).select_from(SourceArtifactRow)) or 0)
```

协调 Agent 创建 `20260716_0002_pit_legacy.py`，`down_revision = "20260716_0001"`；本任务
先为上述三张表生成 `op.create_table` 和 `uq_source_artifacts_sha256`，Task 8 再在同一迁移文件
补齐 legacy 表，期间其他 Agent 不接触该迁移文件。

- [ ] **Step 5: 运行 provider、迁移和仓储测试并提交**

Run:

```bash
python -m pytest backend/tests/infrastructure/market/test_provider_source_contract.py backend/tests/integration/test_lineage_repository.py -q
alembic upgrade head
alembic downgrade 20260716_0001
alembic upgrade head
```

Expected: pytest `5 passed`；两次 upgrade 成功；downgrade 回到 `20260716_0001`。

```bash
git add backend/app/infrastructure/market backend/app/infrastructure/persistence/pit_rows.py backend/migrations/versions/20260716_0002_pit_legacy.py backend/tests/infrastructure/market backend/tests/integration/test_lineage_repository.py
git commit -m "feat: persist provider lineage for reproducible research snapshots"
```

### Task 4: 迁移完整 research adapters 和受限结构化 LLM 端口

**Files:**
- Create: `backend/app/ports/research_data.py`
- Create: `backend/app/ports/policy.py`
- Create: `backend/app/ports/llm_factor.py`
- Create: `backend/app/infrastructure/market/research_adapters.py`
- Create: `backend/app/infrastructure/policy/official_policy.py`
- Create: `backend/app/infrastructure/llm/deepseek_factor.py`
- Create: `docs/migrations/la-code-reuse-manifest.json`
- Create: `backend/tests/contracts/test_research_adapter_contract.py`
- Create: `backend/tests/infrastructure/llm/test_deepseek_factor.py`
- Create: `backend/tests/integration/test_research_evidence_source.py`

- [ ] **Step 1: 写 Fake 共同契约和 LLM 越权/证据越界测试**

迁移代码前先创建并校验 provenance manifest；`source_dirty=true` 表示源仓盘点时有不相关
未提交修改，因此每个文件必须以自己的 SHA-256 为准，不能只信 commit：

```json
{
  "source_repository": "/Users/bujiatang/workspace/LA",
  "source_commit": "43d8b8cb5305b09c4c9deef38e7f074a39717445",
  "source_dirty": true,
  "entries": [
    {"source_path":"shield_sword/indicators.py","source_sha256":"fab131f376a7b7fb9e8b19a8312d8659ef0bf789c403a58aaf717959aedc5bdc","target":"backend/app/core/market/strategy_inputs.py","method":"extract"},
    {"source_path":"shield_sword/providers/akshare_provider.py","source_sha256":"1c235d256b4bb74d7bd4bf7df05a266f421f01f7b668e638ac696a95cd3a977f","target":"backend/app/infrastructure/market/research_adapters.py","method":"adapt"},
    {"source_path":"shield_sword/providers/baostock_provider.py","source_sha256":"aeb16ed9e475ddf10fffff9b854820e77e364692ed488c13cbde9c10efc47ede","target":"backend/app/infrastructure/market/research_adapters.py","method":"adapt"},
    {"source_path":"shield_sword/providers/sina_realtime_provider.py","source_sha256":"781f86590feb1181bc2d91d1a3c690814288f6059f47fe2b629ce7b7671e64d9","target":"backend/app/infrastructure/market/research_adapters.py","method":"adapt"},
    {"source_path":"shield_sword/providers/policy_provider.py","source_sha256":"838479e3a477b1e827bf1c0b9a96cdc58d29285dc36a48aad715f581cfffbe89","target":"backend/app/infrastructure/policy/official_policy.py","method":"adapt"},
    {"source_path":"shield_sword/providers/deepseek_provider.py","source_sha256":"80c638e80f04a180560f3d1d8a1c7a2b08cde40b9a10504a2d3406698414b8e3","target":"backend/app/infrastructure/llm/deepseek_factor.py","method":"adapt"},
    {"source_path":"shield_sword/theme_mapping.py","source_sha256":"db07d88aa17f3d637159d30cd40712abf5685af10442b43ebc076c959ca3f787","target":"backend/app/core/market/theme_mapping.py","method":"extract"},
    {"source_path":"shield_sword/financial_reports.py","source_sha256":"7d2e473f7d60af5716774004b1af3afc73a506939027ffc1148d0f9f1a8df092","target":"backend/app/core/market/financial_templates.py","method":"rewrite"},
    {"source_path":"shield_sword/market_data/models.py","source_sha256":"bc037f108e99f6d47f09e5de4991e64ebde4c6bfac5740b3501349898e58dfc2","target":"backend/app/core/market/pit_models.py","method":"rewrite"},
    {"source_path":"shield_sword/market_data/quality.py","source_sha256":"b1954b374b98c9a9a138985c0678dc36194ee06d7e5b9b45ace0bb82fce7ccf9","target":"backend/app/core/market/pit_models.py","method":"adapt"},
    {"source_path":"shield_sword/position_adjuster.py","source_sha256":"fa05e760e01b949a0e4fd41e930b8e70f3c5af86f307ae83cdc2ab60020e74fd","target":"backend/app/core/portfolio/models.py","method":"extract"},
    {"source_path":"shield_sword/execution_state.py","source_sha256":"19ed3198e91c1eb99102cd773846b52ae2bb1d29a99f9c74cc6fc13c654703f5","target":"backend/app/features/backtests/execution.py","method":"rewrite"}
  ]
}
```

Run:

```bash
shasum -a 256 \
  /Users/bujiatang/workspace/LA/shield_sword/indicators.py \
  /Users/bujiatang/workspace/LA/shield_sword/providers/akshare_provider.py \
  /Users/bujiatang/workspace/LA/shield_sword/providers/baostock_provider.py \
  /Users/bujiatang/workspace/LA/shield_sword/providers/sina_realtime_provider.py \
  /Users/bujiatang/workspace/LA/shield_sword/providers/policy_provider.py \
  /Users/bujiatang/workspace/LA/shield_sword/providers/deepseek_provider.py \
  /Users/bujiatang/workspace/LA/shield_sword/theme_mapping.py \
  /Users/bujiatang/workspace/LA/shield_sword/financial_reports.py \
  /Users/bujiatang/workspace/LA/shield_sword/market_data/models.py \
  /Users/bujiatang/workspace/LA/shield_sword/market_data/quality.py \
  /Users/bujiatang/workspace/LA/shield_sword/position_adjuster.py \
  /Users/bujiatang/workspace/LA/shield_sword/execution_state.py
```

Expected: 12 个 hash 逐项等于 manifest；任一不一致立即停止迁移，重新审阅源 diff 并更新
`source_commit`、dirty 状态、hash 和处理方式，不从已变化文件盲复制。

```python
# backend/tests/contracts/test_research_adapter_contract.py
from datetime import date, datetime

import pytest

from backend.app.ports.research_data import ResearchMarketDataPort


@pytest.mark.parametrize(
    "provider_fixture",
    [
        "fake_research_provider",
        "akshare_provider",
        "baostock_provider",
        "fallback_research_provider",
    ],
)
def test_market_adapters_share_unadjusted_as_of_contract(
    provider_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    provider: ResearchMarketDataPort = request.getfixturevalue(provider_fixture)
    as_of = datetime.fromisoformat("2024-01-02T15:30:00+08:00")

    assert provider.trade_calendar(date(2024, 1, 1), date(2024, 1, 2))[-1].is_open
    assert all(item.available_at <= as_of for item in provider.universe(as_of))
    assert all(item.price_adjustment == "none" for item in provider.daily_bars("000001.SZ", as_of))


def test_sina_is_quote_only_and_preserves_observation_time(sina_quote_provider) -> None:
    as_of = datetime.fromisoformat("2024-01-02T10:30:00+08:00")

    quotes = sina_quote_provider.quotes(("000001.SZ",), as_of)

    assert quotes[0].security_id == "000001.SZ"
    assert quotes[0].observed_at <= as_of
```

```python
# backend/tests/infrastructure/llm/test_deepseek_factor.py
from datetime import datetime

import pytest

from backend.app.infrastructure.llm.deepseek_factor import LlmFactorValidationError, validate_factor


AS_OF = datetime.fromisoformat("2024-01-02T15:30:00+08:00")


def test_llm_rejects_action_and_quantity_even_when_json_is_valid(valid_factor_json) -> None:
    valid_factor_json["action"] = "buy"
    valid_factor_json["quantity"] = 1000

    with pytest.raises(LlmFactorValidationError, match="forbidden output fields"):
        validate_factor(valid_factor_json, as_of_time=AS_OF, allowed_evidence={"doc-1"})


def test_llm_rejects_future_or_unknown_evidence(valid_factor_json) -> None:
    valid_factor_json["evidence"][0]["published_at"] = "2024-01-03T09:00:00+08:00"

    with pytest.raises(LlmFactorValidationError, match="evidence is unavailable"):
        validate_factor(valid_factor_json, as_of_time=AS_OF, allowed_evidence={"doc-1"})


def test_llm_rejects_unknown_enum_and_missing_quote(valid_factor_json) -> None:
    valid_factor_json["financial_light"] = "amber"
    valid_factor_json["evidence"][0]["quote"] = ""

    with pytest.raises(LlmFactorValidationError):
        validate_factor(valid_factor_json, as_of_time=AS_OF, allowed_evidence={"doc-1"})
```

- [ ] **Step 2: 冻结窄 ports；所有方法显式接收时点**

```python
# backend/app/ports/research_data.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class CalendarDay:
    trade_date: date
    is_open: bool
    available_at: datetime
    source_hash: str


@dataclass(frozen=True)
class UniverseSecurity:
    security_id: str
    name: str
    listed_on: date
    is_st: bool
    is_suspended: bool
    industry_id: str | None
    theme_ids: tuple[str, ...]
    available_at: datetime
    source_hash: str


@dataclass(frozen=True)
class ResearchBar:
    security_id: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    amount: Decimal
    price_adjustment: str
    adjustment_factor: Decimal
    available_at: datetime
    source_hash: str


@dataclass(frozen=True)
class ResearchQuote:
    security_id: str
    price: Decimal
    observed_at: datetime
    source_hash: str


@dataclass(frozen=True)
class ResearchFeeSchedule:
    record_id: str
    effective_from: date
    effective_to: date | None
    exchange: str
    asset_type: str
    commission_rate: Decimal
    minimum_commission: Decimal
    stamp_tax_sell_rate: Decimal
    transfer_rate: Decimal
    available_at: datetime
    source_hash: str


@dataclass(frozen=True)
class FinancialMaterial:
    security_id: str
    report_period: date
    published_at: datetime
    facts: dict[str, Decimal | str | None]
    source_hash: str


class ResearchMarketDataPort(Protocol):
    def trade_calendar(self, start: date, end: date) -> tuple[CalendarDay, ...]: ...
    def universe(self, as_of_time: datetime) -> tuple[UniverseSecurity, ...]: ...
    def quotes(self, security_ids: tuple[str, ...], as_of_time: datetime) -> tuple[ResearchQuote, ...]: ...
    def daily_bars(self, security_id: str, as_of_time: datetime) -> tuple[ResearchBar, ...]: ...
    def financials(self, security_id: str, as_of_time: datetime) -> tuple[FinancialMaterial, ...]: ...
    def fee_schedules(self, as_of_time: datetime) -> tuple[ResearchFeeSchedule, ...]: ...
```

```python
# backend/app/ports/policy.py
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class PolicyMaterial:
    source_id: str
    published_at: datetime
    first_observed_at: datetime
    evidence_grade: str
    content_hash: str
    text: str


class PolicyPort(Protocol):
    def materials(self, *, as_of_time: datetime) -> tuple[PolicyMaterial, ...]: ...
```

```python
# backend/app/ports/llm_factor.py
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from backend.app.ports.policy import PolicyMaterial
from backend.app.ports.research_data import FinancialMaterial


@dataclass(frozen=True)
class StructuredLlmFactor:
    as_of_time: datetime
    security_id: str
    model_id: str
    prompt_hash: str
    input_hash: str
    output_hash: str
    payload: dict[str, object]


class LlmFactorPort(Protocol):
    def extract(
        self,
        *,
        as_of_time: datetime,
        security_id: str,
        policy_materials: tuple[PolicyMaterial, ...],
        financial_materials: tuple[FinancialMaterial, ...],
    ) -> StructuredLlmFactor: ...
```

- [ ] **Step 3: 运行测试并确认 ports、adapters 和校验器尚未存在**

Run:

```bash
python -m pytest backend/tests/contracts/test_research_adapter_contract.py backend/tests/infrastructure/llm/test_deepseek_factor.py backend/tests/integration/test_research_evidence_source.py -q
```

Expected: FAIL，至少包含 `No module named 'backend.app.ports.research_data'`；禁止在看到该
RED 结果前创建 local fixture adapter。

- [ ] **Step 4: 迁移 adapters，保留 fallback 但统一转换为 `TemporalRecord`**

`research_adapters.py` 创建确定性的本地 `FixtureResearchAdapter` 和必要的字段转换适配器；
从 LA 迁移时逐个方法保留其重试和字段转换测试，
但必须作以下确定性改动：AkShare `adjust=""`；BaoStock `adjustflag="3"`；Sina 只用于
`observed_at` 对应的实时 quote；财报使用实际公告时间，缺公告时间的行只能带
`RESEARCH_RECONSTRUCTED_AVAILABILITY` 质量码。`OfficialPolicyAdapter` 只接受 A 级官方原文或
能回溯 A 级原文的 B 级材料，并令 `available_at=max(published_at, first_observed_at)`。

迁移后的 adapter 不再暴露 LA 的 `MarketRecord`；先用下面的窄桥接器把已验证的 raw client
转换成 DA DTO。`ReferenceResearchPort` 负责共同的日历、证券主数据、财报公告和历史费率，
避免 AkShare/BaoStock 两份实现对这些字段作不同猜测：

```python
# backend/app/infrastructure/market/research_adapters.py
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from backend.app.ports.research_data import (
    CalendarDay,
    FinancialMaterial,
    ResearchBar,
    ResearchFeeSchedule,
    ResearchMarketDataPort,
    ResearchQuote,
    UniverseSecurity,
)


@dataclass(frozen=True)
class RawBar:
    security_id: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    amount: Decimal
    available_at: datetime
    raw_payload: dict[str, object]


class RawBarClient(Protocol):
    provider_name: str

    def load_unadjusted(
        self,
        security_id: str,
        start: date,
        end: date,
    ) -> tuple[RawBar, ...]: ...


class ResearchQuotePort(Protocol):
    def quotes(
        self,
        security_ids: tuple[str, ...],
        as_of_time: datetime,
    ) -> tuple[ResearchQuote, ...]: ...


class ReferenceResearchPort(Protocol):
    def trade_calendar(self, start: date, end: date) -> tuple[CalendarDay, ...]: ...
    def universe(self, as_of_time: datetime) -> tuple[UniverseSecurity, ...]: ...
    def financials(
        self,
        security_id: str,
        as_of_time: datetime,
    ) -> tuple[FinancialMaterial, ...]: ...
    def fee_schedules(
        self,
        as_of_time: datetime,
    ) -> tuple[ResearchFeeSchedule, ...]: ...


def _sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ProviderResearchAdapter(ResearchMarketDataPort):
    def __init__(
        self,
        bars: RawBarClient,
        quotes: ResearchQuotePort,
        reference: ReferenceResearchPort,
        *,
        lookback_days: int = 550,
    ) -> None:
        self._bars = bars
        self._quotes = quotes
        self._reference = reference
        self._lookback_days = lookback_days

    def trade_calendar(self, start: date, end: date) -> tuple[CalendarDay, ...]:
        return self._reference.trade_calendar(start, end)

    def universe(self, as_of_time: datetime) -> tuple[UniverseSecurity, ...]:
        return self._reference.universe(as_of_time)

    def quotes(
        self,
        security_ids: tuple[str, ...],
        as_of_time: datetime,
    ) -> tuple[ResearchQuote, ...]:
        return self._quotes.quotes(security_ids, as_of_time)

    def daily_bars(
        self,
        security_id: str,
        as_of_time: datetime,
    ) -> tuple[ResearchBar, ...]:
        start = as_of_time.date() - timedelta(days=self._lookback_days)
        rows = self._bars.load_unadjusted(security_id, start, as_of_time.date())
        return tuple(
            ResearchBar(
                security_id=row.security_id,
                trade_date=row.trade_date,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
                amount=row.amount,
                price_adjustment="none",
                adjustment_factor=Decimal("1"),
                available_at=row.available_at,
                source_hash=_sha256(
                    {"provider": self._bars.provider_name, "row": asdict(row)}
                ),
            )
            for row in rows
            if row.available_at <= as_of_time
        )

    def financials(
        self,
        security_id: str,
        as_of_time: datetime,
    ) -> tuple[FinancialMaterial, ...]:
        return self._reference.financials(security_id, as_of_time)

    def fee_schedules(
        self,
        as_of_time: datetime,
    ) -> tuple[ResearchFeeSchedule, ...]:
        return self._reference.fee_schedules(as_of_time)


class AkShareResearchAdapter(ProviderResearchAdapter):
    pass


class BaoStockResearchAdapter(ProviderResearchAdapter):
    pass


class FallbackResearchAdapter(ProviderResearchAdapter):
    def __init__(
        self,
        primary: RawBarClient,
        fallback: RawBarClient,
        quotes: ResearchQuotePort,
        reference: ReferenceResearchPort,
    ) -> None:
        super().__init__(_FallbackRawBars(primary, fallback), quotes, reference)


class _FallbackRawBars:
    provider_name = "akshare_with_baostock_fallback"

    def __init__(self, primary: RawBarClient, fallback: RawBarClient) -> None:
        self._primary = primary
        self._fallback = fallback

    def load_unadjusted(
        self,
        security_id: str,
        start: date,
        end: date,
    ) -> tuple[RawBar, ...]:
        rows = self._primary.load_unadjusted(security_id, start, end)
        return rows or self._fallback.load_unadjusted(security_id, start, end)
```

`AkShareRawBarClient.load_unadjusted()` 必须直接调用迁移后的
`stock_zh_a_hist(..., adjust="")`；`BaoStockRawBarClient.load_unadjusted()` 必须直接调用
`query_history_k_data_plus(..., frequency="d", adjustflag="3")`。二者把 API 原始行完整放入
`RawBar.raw_payload` 后再交给上面的统一 DTO 转换；测试对 fake SDK 断言这两个确切参数，禁止
通过默认值取得复权价格。`SinaQuoteAdapter` 只实现 `ResearchQuotePort`，并拒绝
`observed_at > as_of_time` 的行。

```python
# backend/app/infrastructure/policy/official_policy.py
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from backend.app.ports.policy import PolicyMaterial


@dataclass(frozen=True)
class RawPolicyDocument:
    source_id: str
    published_at: datetime
    first_observed_at: datetime
    evidence_grade: str
    official_source_id: str | None
    content_hash: str
    text: str


class OfficialPolicyClient(Protocol):
    def fetch(self, *, as_of_time: datetime) -> tuple[RawPolicyDocument, ...]: ...


class OfficialPolicyAdapter:
    def __init__(self, client: OfficialPolicyClient) -> None:
        self._client = client

    def materials(self, *, as_of_time: datetime) -> tuple[PolicyMaterial, ...]:
        result: list[PolicyMaterial] = []
        for item in self._client.fetch(as_of_time=as_of_time):
            available_at = max(item.published_at, item.first_observed_at)
            traceable = item.evidence_grade == "A" or (
                item.evidence_grade == "B" and item.official_source_id is not None
            )
            if not traceable or available_at > as_of_time:
                continue
            result.append(
                PolicyMaterial(
                    source_id=item.source_id,
                    published_at=item.published_at,
                    first_observed_at=item.first_observed_at,
                    evidence_grade=item.evidence_grade,
                    content_hash=item.content_hash,
                    text=item.text,
                )
            )
        return tuple(result)
```

- [ ] **Step 5: 实现 DeepSeek JSON、hash、范围和证据校验**

```python
# backend/app/infrastructure/llm/deepseek_factor.py
from __future__ import annotations

import hashlib
import json
from datetime import datetime


FORBIDDEN_FIELDS = frozenset({"action", "quantity", "position", "buy", "sell"})
ENUMS = {
    "policy_direction": {"supportive", "neutral", "restrictive", "unknown"},
    "implementation_stage": {"planning", "pilot", "execution", "mature", "exit", "unknown"},
    "financial_light": {"green", "yellow", "red", "unknown"},
}


class LlmFactorValidationError(ValueError):
    pass


def validate_factor(
    payload: dict[str, object],
    *,
    as_of_time: datetime,
    allowed_evidence: set[str],
) -> dict[str, object]:
    forbidden = FORBIDDEN_FIELDS.intersection(payload)
    if forbidden:
        raise LlmFactorValidationError("forbidden output fields")
    for field, allowed in ENUMS.items():
        if payload.get(field) not in allowed:
            raise LlmFactorValidationError(f"invalid enum: {field}")
    for field in ("policy_strength", "policy_relevance", "financial_text_score"):
        value = payload.get(field)
        if not isinstance(value, (int, float)) or not 0 <= value <= 100:
            raise LlmFactorValidationError(f"invalid score: {field}")
    for field in ("llm_confidence", "evidence_confidence", "data_completeness"):
        value = payload.get(field)
        if not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise LlmFactorValidationError(f"invalid confidence: {field}")
    if not isinstance(payload.get("red_flags"), list):
        raise LlmFactorValidationError("red_flags must be a list")
    evidence = payload.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise LlmFactorValidationError("evidence is required")
    for item in evidence:
        if not isinstance(item, dict):
            raise LlmFactorValidationError("invalid evidence")
        if not str(item.get("quote", "")).strip():
            raise LlmFactorValidationError("evidence quote is required")
        published_at = datetime.fromisoformat(str(item["published_at"]))
        if item.get("source_id") not in allowed_evidence or published_at > as_of_time:
            raise LlmFactorValidationError("evidence is unavailable")
    return payload


def content_hash(payload: object) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

```python
# backend/app/infrastructure/llm/deepseek_factor.py（续）
from typing import Protocol

from backend.app.ports.llm_factor import StructuredLlmFactor
from backend.app.ports.policy import PolicyMaterial
from backend.app.ports.research_data import FinancialMaterial


class JsonCompletionClient(Protocol):
    def complete_json(
        self,
        *,
        model: str,
        system_prompt: str,
        payload: dict[str, object],
        temperature: float,
    ) -> dict[str, object]: ...


class DeepSeekStructuredFactorAdapter:
    def __init__(
        self,
        client: JsonCompletionClient,
        *,
        model_id: str,
        system_prompt: str,
        temperature: float = 0.0,
    ) -> None:
        self._client = client
        self._model_id = model_id
        self._system_prompt = system_prompt
        self._temperature = temperature

    def extract(
        self,
        *,
        as_of_time: datetime,
        security_id: str,
        policy_materials: tuple[PolicyMaterial, ...],
        financial_materials: tuple[FinancialMaterial, ...],
    ) -> StructuredLlmFactor:
        request_payload: dict[str, object] = {
            "as_of_time": as_of_time.isoformat(),
            "security_id": security_id,
            "policy_materials": [
                {
                    "source_id": item.source_id,
                    "published_at": item.published_at.isoformat(),
                    "first_observed_at": item.first_observed_at.isoformat(),
                    "evidence_grade": item.evidence_grade,
                    "content_hash": item.content_hash,
                    "text": item.text,
                }
                for item in policy_materials
            ],
            "financial_materials": [
                {
                    "security_id": item.security_id,
                    "report_period": item.report_period.isoformat(),
                    "published_at": item.published_at.isoformat(),
                    "facts": item.facts,
                    "source_hash": item.source_hash,
                }
                for item in financial_materials
            ],
        }
        prompt_hash = content_hash(self._system_prompt)
        input_hash = content_hash(request_payload)
        raw = self._client.complete_json(
            model=self._model_id,
            system_prompt=self._system_prompt,
            payload=request_payload,
            temperature=self._temperature,
        )
        allowed_evidence = {item.source_id for item in policy_materials} | {
            item.source_hash for item in financial_materials
        }
        payload = validate_factor(
            raw,
            as_of_time=as_of_time,
            allowed_evidence=allowed_evidence,
        )
        output_hash = content_hash(
            {
                "model_id": self._model_id,
                "prompt_hash": prompt_hash,
                "input_hash": input_hash,
                "payload": payload,
            }
        )
        return StructuredLlmFactor(
            as_of_time=as_of_time,
            security_id=security_id,
            model_id=self._model_id,
            prompt_hash=prompt_hash,
            input_hash=input_hash,
            output_hash=output_hash,
            payload=payload,
        )
```

普通日志只记录 output hash、run id 和错误码。`validate_factor()` 抛错时 adapter 必须原样失败，
不得把原始 prompt、政策正文、财报正文或账户信息写入日志，也不得产生可开仓因子。

- [ ] **Step 6: 把三类证据转换成 concrete source 并注册唯一聚合源**

在 `research_adapters.py` 以三个窄转换器
`MarketEvidenceSource`、`PolicyEvidenceSource`、`LlmEvidenceSource` 分别把 port DTO 转成
`TemporalRecord`，再用下列 concrete source 聚合；它是 local composition 注册的对象：

```python
from dataclasses import asdict
from datetime import datetime, time, timedelta

from backend.app.core.market.pit_models import (
    DataKind,
    LineageRef,
    SnapshotScope,
    TemporalRecord,
)
from backend.app.infrastructure.market.research_source import ResearchBatch
from backend.app.ports.research_data import ResearchMarketDataPort


class MarketEvidenceSource:
    provider = "research_market"

    def __init__(
        self,
        market: ResearchMarketDataPort,
        benchmark_ids: tuple[str, ...],
    ) -> None:
        self._market = market
        self._benchmark_ids = benchmark_ids

    def fetch(self, *, as_of_time: datetime, scope: SnapshotScope) -> ResearchBatch:
        start = (scope.history_start or as_of_time - timedelta(days=400)).date()
        calendar = self._market.trade_calendar(start, as_of_time.date())
        universe = self._market.universe(as_of_time)
        security_ids = scope.security_ids or tuple(item.security_id for item in universe)
        records: list[TemporalRecord] = []
        for day in calendar:
            records.append(
                self._record(
                    DataKind.TRADING_CALENDAR,
                    "MARKET:CN",
                    day.trade_date.isoformat(),
                    datetime.combine(day.trade_date, time(15, 30), day.available_at.tzinfo),
                    day.available_at,
                    day.source_hash,
                    asdict(day),
                )
            )
        by_id = {item.security_id: item for item in universe}
        for security_id in security_ids:
            item = by_id[security_id]
            for kind, suffix, payload in (
                (DataKind.SECURITY_MASTER, "master", asdict(item)),
                (
                    DataKind.SECURITY_STATUS,
                    "status",
                    {"is_st": item.is_st, "is_suspended": item.is_suspended},
                ),
                (
                    DataKind.INDUSTRY_MEMBERSHIP,
                    "industry",
                    {"industry_id": item.industry_id},
                ),
                (
                    DataKind.THEME_MEMBERSHIP,
                    "themes",
                    {"theme_ids": item.theme_ids},
                ),
            ):
                records.append(
                    self._record(
                        kind,
                        security_id,
                        suffix,
                        as_of_time,
                        item.available_at,
                        item.source_hash,
                        payload,
                    )
                )
            for bar in self._market.daily_bars(security_id, as_of_time):
                event_time = datetime.combine(
                    bar.trade_date,
                    time(15, 0),
                    bar.available_at.tzinfo,
                )
                raw_payload = asdict(bar) | {"price_adjustment": "none"}
                records.append(
                    self._record(
                        DataKind.DAILY_BAR_RAW,
                        security_id,
                        bar.trade_date.isoformat(),
                        event_time,
                        bar.available_at,
                        bar.source_hash,
                        raw_payload,
                    )
                )
                records.append(
                    self._record(
                        DataKind.ADJUSTMENT_FACTOR,
                        security_id,
                        bar.trade_date.isoformat(),
                        event_time,
                        bar.available_at,
                        bar.source_hash,
                        {"factor": str(bar.adjustment_factor)},
                    )
                )
            for material in self._market.financials(security_id, as_of_time):
                records.append(
                    self._record(
                        DataKind.FINANCIAL_DISCLOSURE,
                        security_id,
                        material.report_period.isoformat(),
                        material.published_at,
                        material.published_at,
                        material.source_hash,
                        asdict(material),
                    )
                )
                for metric, value in material.facts.items():
                    records.append(
                        self._record(
                            DataKind.FINANCIAL_FACT,
                            security_id,
                            f"{material.report_period.isoformat()}:{metric}",
                            material.published_at,
                            material.published_at,
                            material.source_hash,
                            {"metric": metric, "value": value},
                        )
                    )
        for index_id in self._benchmark_ids:
            for bar in self._market.daily_bars(index_id, as_of_time):
                event_time = datetime.combine(
                    bar.trade_date,
                    time(15, 0),
                    bar.available_at.tzinfo,
                )
                records.append(
                    self._record(
                        DataKind.INDEX_DAILY_BAR,
                        f"MARKET:{index_id}",
                        bar.trade_date.isoformat(),
                        event_time,
                        bar.available_at,
                        bar.source_hash,
                        asdict(bar) | {"price_adjustment": "none"},
                    )
                )
        for quote in self._market.quotes(security_ids, as_of_time):
            records.append(
                self._record(
                    DataKind.REALTIME_QUOTE,
                    quote.security_id,
                    quote.observed_at.isoformat(),
                    quote.observed_at,
                    quote.observed_at,
                    quote.source_hash,
                    asdict(quote),
                )
            )
        for fee in self._market.fee_schedules(as_of_time):
            records.append(
                self._record(
                    DataKind.FEE_SCHEDULE,
                    "MARKET:FEE",
                    fee.record_id,
                    as_of_time,
                    fee.available_at,
                    fee.source_hash,
                    asdict(fee),
                )
            )
        hashes = sorted({record.source_artifact_hash for record in records})
        lineage = tuple(
            LineageRef(f"research-{digest[:16]}", self.provider, digest)
            for digest in hashes
        )
        return ResearchBatch(tuple(records), lineage)

    @staticmethod
    def _record(
        kind: DataKind,
        entity_id: str,
        suffix: str,
        event_time: datetime,
        available_at: datetime,
        source_hash: str,
        payload: dict[str, object],
    ) -> TemporalRecord:
        return TemporalRecord(
            f"{kind.value}:{entity_id}:{suffix}",
            kind,
            entity_id,
            event_time,
            available_at,
            available_at,
            source_hash,
            payload,
        )
```

`benchmark_ids` 的 production 默认值为中证全指 `000985.CSI` 和降级基准上证综指
`000001.SH`。指数行只能写 `INDEX_DAILY_BAR`，不能混入个股 `DAILY_BAR_RAW`。

```python
# backend/app/infrastructure/market/research_adapters.py（续）
from backend.app.infrastructure.market.research_source import ResearchBatch
from backend.app.ports.llm_factor import LlmFactorPort
from backend.app.ports.policy import PolicyPort


def lineage_for(
    provider: str,
    records: tuple[TemporalRecord, ...],
) -> tuple[LineageRef, ...]:
    return tuple(
        LineageRef(f"{provider}-{digest[:16]}", provider, digest)
        for digest in sorted({record.source_artifact_hash for record in records})
    )


class PolicyEvidenceSource:
    provider = "official_policy"

    def __init__(self, policy: PolicyPort) -> None:
        self._policy = policy

    def fetch(self, *, as_of_time: datetime, scope: SnapshotScope) -> ResearchBatch:
        del scope
        records = tuple(
            MarketEvidenceSource._record(
                DataKind.POLICY_DOCUMENT,
                "MARKET:POLICY",
                item.source_id,
                item.published_at,
                max(item.published_at, item.first_observed_at),
                item.content_hash,
                {
                    "source_id": item.source_id,
                    "published_at": item.published_at.isoformat(),
                    "first_observed_at": item.first_observed_at.isoformat(),
                    "evidence_grade": item.evidence_grade,
                    "text": item.text,
                },
            )
            for item in self._policy.materials(as_of_time=as_of_time)
            if max(item.published_at, item.first_observed_at) <= as_of_time
        )
        return ResearchBatch(records, lineage_for(self.provider, records))


class LlmEvidenceSource:
    provider = "structured_llm_factor"

    def __init__(
        self,
        llm: LlmFactorPort,
        policy: PolicyPort,
        market: ResearchMarketDataPort,
    ) -> None:
        self._llm = llm
        self._policy = policy
        self._market = market

    def fetch(self, *, as_of_time: datetime, scope: SnapshotScope) -> ResearchBatch:
        policy_materials = tuple(
            item
            for item in self._policy.materials(as_of_time=as_of_time)
            if max(item.published_at, item.first_observed_at) <= as_of_time
        )
        security_ids = scope.security_ids or tuple(
            item.security_id for item in self._market.universe(as_of_time)
        )
        records: list[TemporalRecord] = []
        for security_id in security_ids:
            financial_materials = tuple(
                item
                for item in self._market.financials(security_id, as_of_time)
                if item.published_at <= as_of_time
            )
            factor = self._llm.extract(
                as_of_time=as_of_time,
                security_id=security_id,
                policy_materials=policy_materials,
                financial_materials=financial_materials,
            )
            if factor.as_of_time != as_of_time or factor.security_id != security_id:
                raise ValueError("LLM factor identity mismatch")
            records.append(
                MarketEvidenceSource._record(
                    DataKind.LLM_FACTOR,
                    security_id,
                    factor.output_hash,
                    factor.as_of_time,
                    factor.as_of_time,
                    factor.output_hash,
                    {
                        "model_id": factor.model_id,
                        "prompt_hash": factor.prompt_hash,
                        "input_hash": factor.input_hash,
                        "output_hash": factor.output_hash,
                        "factor": factor.payload,
                    },
                )
            )
        result = tuple(records)
        return ResearchBatch(result, lineage_for(self.provider, result))
```

`LlmEvidenceSource` 不捕获 `LlmFactorValidationError`。无效、未来或证据不完整的输出必须使
本次 snapshot 构建失败，不得伪造 neutral factor 继续开仓。

```python
from datetime import datetime

from backend.app.core.market.pit_models import SnapshotScope
from backend.app.infrastructure.market.research_source import ResearchBatch, ResearchSource


class ResearchEvidenceSource:
    provider = "research_evidence"

    def __init__(self, sources: tuple[ResearchSource, ...]) -> None:
        self._sources = sources

    def fetch(self, *, as_of_time: datetime, scope: SnapshotScope) -> ResearchBatch:
        batches = tuple(
            source.fetch(as_of_time=as_of_time, scope=scope)
            for source in self._sources
        )
        records = tuple(record for batch in batches for record in batch.records)
        present = {record.kind for record in records}
        missing = set(scope.required_kinds) - present
        if missing:
            names = ",".join(sorted(kind.value for kind in missing))
            raise ValueError(f"research evidence source missing: {names}")
        return ResearchBatch(
            records,
            tuple(ref for batch in batches for ref in batch.lineage),
        )
```

```python
# backend/app/infrastructure/market/build.py（替换 Task 3 的临时 factory）
from backend.app.infrastructure.market.research_adapters import (
    LlmEvidenceSource,
    MarketEvidenceSource,
    PolicyEvidenceSource,
    ResearchEvidenceSource,
)
from backend.app.infrastructure.market.research_warehouse import ResearchPointInTimeWarehouse
from backend.app.ports.llm_factor import LlmFactorPort
from backend.app.ports.point_in_time import PointInTimeWarehouse
from backend.app.ports.policy import PolicyPort
from backend.app.ports.research_data import ResearchMarketDataPort


def build_point_in_time_warehouse(
    *,
    market: ResearchMarketDataPort,
    policy: PolicyPort,
    llm: LlmFactorPort,
    benchmark_ids: tuple[str, ...] = ("000985.CSI", "000001.SH"),
) -> PointInTimeWarehouse:
    source = ResearchEvidenceSource(
        (
            MarketEvidenceSource(market, benchmark_ids),
            PolicyEvidenceSource(policy),
            LlmEvidenceSource(llm, policy, market),
        )
    )
    return ResearchPointInTimeWarehouse((source,))
```

```python
# backend/tests/integration/test_research_evidence_source.py
from datetime import datetime

from backend.app.core.market.pit_models import DataKind, SnapshotScope
from backend.app.infrastructure.market.research_adapters import ResearchEvidenceSource


def test_candidate_scope_contains_complete_hybrid_evidence(
    fake_market_evidence_source,
    fake_policy_evidence_source,
    fake_llm_evidence_source,
) -> None:
    source = ResearchEvidenceSource(
        (
            fake_market_evidence_source,
            fake_policy_evidence_source,
            fake_llm_evidence_source,
        )
    )
    scope = SnapshotScope.candidate_recommendation()

    batch = source.fetch(
        as_of_time=datetime.fromisoformat("2024-01-02T15:30:00+08:00"),
        scope=scope,
    )

    assert {record.kind for record in batch.records} == set(scope.required_kinds)
    assert DataKind.POLICY_DOCUMENT in scope.required_kinds
    assert DataKind.FINANCIAL_DISCLOSURE in scope.required_kinds
    assert DataKind.LLM_FACTOR in scope.required_kinds


def test_local_factory_registers_one_complete_evidence_source(
    fake_market_port,
    fake_policy_port,
    fake_llm_port,
) -> None:
    from backend.app.infrastructure.market.build import build_point_in_time_warehouse

    warehouse = build_point_in_time_warehouse(
        market=fake_market_port,
        policy=fake_policy_port,
        llm=fake_llm_port,
    )

    assert [source.provider for source in warehouse.sources] == ["research_evidence"]
```

- [ ] **Step 7: 运行共同契约、LLM 和聚合证据测试**

Run:

```bash
python -m pytest backend/tests/contracts/test_research_adapter_contract.py backend/tests/infrastructure/llm/test_deepseek_factor.py backend/tests/integration/test_research_evidence_source.py -q
```

Expected: 所有 Fake/生产 adapter contract PASS；越权字段、未来证据、未知证据和 hash 不匹配均失败。

- [ ] **Step 8: 提交 research adapters**

```bash
git add docs/migrations/la-code-reuse-manifest.json backend/app/ports backend/app/infrastructure/market/research_adapters.py backend/app/infrastructure/policy backend/app/infrastructure/llm backend/tests/contracts backend/tests/infrastructure/llm backend/tests/integration/test_research_evidence_source.py
git commit -m "feat: migrate research evidence through narrow as-of adapters"
```

### Task 5: 建立唯一 StrategyInputBuilder 和 golden tests

**Files:**
- Create: `backend/app/core/market/strategy_inputs.py`
- Create: `backend/tests/core/market/test_strategy_inputs.py`
- Create: `backend/tests/fixtures/strategy_inputs/v212_golden.json`

- [ ] **Step 1: 写指标、市场宽度、横截面、财报模板和 fail-closed golden test**

```python
# backend/tests/core/market/test_strategy_inputs.py
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from backend.app.core.market.strategy_inputs import StrategyInputBuilder, StrategyInputError


FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "strategy_inputs"


def test_v212_strategy_inputs_match_hand_calculated_golden(
    snapshot_fixture,
    portfolio_fixture,
) -> None:
    expected = json.loads((FIXTURE / "v212_golden.json").read_text(encoding="utf-8"))

    request = StrategyInputBuilder().build(
        snapshot=snapshot_fixture,
        portfolio=portfolio_fixture,
        strategy_version="v2.12",
    )

    actual = json.loads(json.dumps(asdict(request), ensure_ascii=False, default=str))
    assert actual == expected


def test_missing_market_breadth_fails_closed(
    snapshot_without_breadth,
    portfolio_fixture,
) -> None:
    with pytest.raises(StrategyInputError, match="market breadth missing"):
        StrategyInputBuilder().build(
            snapshot=snapshot_without_breadth,
            portfolio=portfolio_fixture,
            strategy_version="v2.12",
        )


def test_missing_two_template_fields_blocks_new_position(
    snapshot_missing_financials,
    portfolio_fixture,
) -> None:
    request = StrategyInputBuilder().build(
        snapshot=snapshot_missing_financials,
        portfolio=portfolio_fixture,
        strategy_version="v2.12",
    )

    assert request.securities[0].hard_filter_passed is False
    assert "FINANCIAL_TEMPLATE_INCOMPLETE" in request.securities[0].quality_codes
```

- [ ] **Step 2: 实现纯计算函数与精确公式**

`strategy_inputs.py` 实现并分别带返回注解：`ma(values, window)`、`atr14(bars)`、
`mavol20(bars)`、`obv_slope20(bars)`、`winsorized_percentile(values, lower=.01, upper=.99)`。
公式固定为 V2.12：市场宽度是可交易 A 股中 `close > MA20` 的比例；
`RS20=stock_return20-industry_return20`、`RS60=stock_return60-benchmark_return60`；
`R=.5*pct(RS20)+.5*pct(RS60)`；
`V=.5*volume_ratio_percentile+.3*obv_slope_percentile+.2*amount_percentile`，量比大于
2.5 按 2.5 截断。技术输入缺 60 个有效交易日、行情日期不一致或市场宽度缺失时失败关闭。

- [ ] **Step 3: 实现股票池硬过滤和财报数值模板**

同一 builder 按时点记录执行：非 ST/退市整理、上市 120 交易日、20 日至少 18 根有效行情、
20 日均额不低于 5000 万、20 日停牌不超过 2 日、收盘不低于 2 元、非一字板、订单参与率
不超过 0.2%、未来两交易日无已知定期报告预约。财报行业模板权重精确使用 V2.12 第 9.2 节；
各连续指标在当日行业横截面 1%/99% 缩尾后算百分位。对应模板缺两个及以上关键字段时
`hard_filter_passed=False` 并写入 `FINANCIAL_TEMPLATE_INCOMPLETE` quality code，不能临时退回
普通工业模板。

- [ ] **Step 4: 只构造 00 的请求，不产生交易动作**

```python
# public seam in backend/app/core/market/strategy_inputs.py
from backend.app.core.market.pit_models import PointInTimeSnapshot
from backend.app.core.portfolio.models import PortfolioSnapshot
from backend.app.core.strategy.types import StrategyEvaluationRequest


class StrategyInputBuilder:
    def build(
        self,
        *,
        snapshot: PointInTimeSnapshot,
        portfolio: PortfolioSnapshot,
        strategy_version: str,
    ) -> StrategyEvaluationRequest:
        if snapshot.quality.has_errors:
            raise StrategyInputError("snapshot quality contains errors")
        return self._build_evaluation_request(
            snapshot=snapshot,
            portfolio=portfolio,
            strategy_version=strategy_version,
        )
```

`_build_evaluation_request` 只写 market state inputs、证券观测、指标、横截面、财报数值分、
LLM 结构化因子、质量码和 manifest hash；不得创建 action、order 或 quantity。02/03/04 只能调用
此 builder 后把请求交给 `V212StrategyEngine.evaluate()`，不能复制计算函数。

- [ ] **Step 5: 运行 golden、Fake 和 00 core 回归并提交**

Run:

```bash
python -m pytest backend/tests/core/market/test_strategy_inputs.py backend/tests/core/strategy -q
python -m mypy backend/app/core/market/strategy_inputs.py
```

Expected: golden 完全相等；三个 fail-closed 测试 PASS；mypy 输出 `Success: no issues found`。

```bash
git add backend/app/core/market/strategy_inputs.py backend/tests/core/market/test_strategy_inputs.py backend/tests/fixtures/strategy_inputs
git commit -m "feat: share one deterministic V2.12 strategy input builder"
```

### Task 6: 检查 LA legacy 文件而不修复原值

**Files:**
- Create: `backend/app/features/legacy_import/models.py`
- Create: `backend/app/features/legacy_import/inspect.py`
- Create: `backend/tests/features/legacy_import/test_inspect.py`

- [ ] **Step 1: 写四类已知质量异常测试**

```python
# backend/tests/features/legacy_import/test_inspect.py
import hashlib
import json
from pathlib import Path

from backend.app.features.legacy_import.inspect import inspect_source
from backend.app.features.legacy_import.models import LegacyQualityTag


HEADER = (
    "ts_code,symbol,name,asset_type,industry,quantity,cost_price,buy_date,"
    "highest_price_since_buy,notes\n"
)


def write(path: Path, body: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = body.encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def test_inspection_reports_known_anomalies_without_changing_source(tmp_path: Path) -> None:
    holdings = tmp_path / "data" / "holdings"
    history = holdings / "历史持仓"
    current = HEADER + "000001.SZ,000001,平安银行,stock,银行,100,10,2024-01-01,,,\n"
    write(holdings / "持仓.csv", current)
    indexed_hash = write(
        history / "2024-01-02_1200_持仓.csv",
        HEADER + "000001.SZ,000001,平安银行,stock,银行,100,10,2024-01-03,,,\n",
    )
    write(history / "2024-01-04_1200_持仓.csv", current)
    (history / "index.json").write_text(
        json.dumps(
            [
                {"archive": "/stale/2024-01-02_1200_持仓.csv", "sha256": "0" * 64},
                {"archive": "/stale/missing.csv", "sha256": indexed_hash},
            ]
        ),
        encoding="utf-8",
    )
    before = {path: path.read_bytes() for path in holdings.rglob("*") if path.is_file()}

    report = inspect_source(tmp_path)

    assert LegacyQualityTag.CHECKSUM_MISMATCH in report.tags
    assert LegacyQualityTag.MISSING_ARCHIVE in report.tags
    assert LegacyQualityTag.UNINDEXED_FILE in report.tags
    assert LegacyQualityTag.BUY_DATE_AFTER_SNAPSHOT in report.tags
    assert before == {path: path.read_bytes() for path in holdings.rglob("*") if path.is_file()}
```

- [ ] **Step 2: 运行测试，确认 inspector 缺失**

Run: `python -m pytest backend/tests/features/legacy_import/test_inspect.py -q`

Expected: FAIL，错误包含 `No module named 'backend.app.features.legacy_import.inspect'`。

- [ ] **Step 3: 创建导入模型和精确质量标签**

```python
# backend/app/features/legacy_import/models.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path


class LegacyQualityTag(StrEnum):
    MISSING_ARCHIVE = "missing_archive"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    UNINDEXED_FILE = "unindexed_file"
    BUY_DATE_AFTER_SNAPSHOT = "buy_date_after_snapshot"


@dataclass(frozen=True)
class LegacyFileInspection:
    path: Path
    sha256: str
    snapshot_at: datetime | None
    tags: tuple[LegacyQualityTag, ...]


@dataclass(frozen=True)
class LegacyInspectionReport:
    source_root: Path
    files: tuple[LegacyFileInspection, ...]
    tags: tuple[LegacyQualityTag, ...]


@dataclass(frozen=True)
class LegacyPositionRow:
    security_id: str
    name: str
    asset_type: str
    industry: str
    quantity: int
    inherited_unit_cost: Decimal
    imported_buy_date: date | None
    highest_price_since_buy: Decimal | None
    notes: str
    source_row_number: int
```

- [ ] **Step 4: 实现按 basename 对齐陈旧绝对索引、checksum 和日期检查**

```python
# backend/app/features/legacy_import/inspect.py
from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.app.features.legacy_import.models import (
    LegacyFileInspection,
    LegacyInspectionReport,
    LegacyQualityTag,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot_at(path: Path) -> datetime | None:
    try:
        return datetime.strptime(path.name[:15], "%Y-%m-%d_%H%M").replace(
            tzinfo=ZoneInfo("Asia/Shanghai")
        )
    except ValueError:
        return None


def _contains_future_buy_date(path: Path, snapshot_at: datetime | None) -> bool:
    if snapshot_at is None:
        return False
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            value = (row.get("buy_date") or "").strip()
            if value and date.fromisoformat(value) > snapshot_at.date():
                return True
    return False


def inspect_source(source_root: Path) -> LegacyInspectionReport:
    root = source_root.resolve()
    holdings = root / "data" / "holdings"
    history = holdings / "历史持仓"
    index_path = history / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else []
    actual_by_name = {path.name: path for path in history.glob("*.csv")}
    indexed_names = {Path(str(entry.get("archive", ""))).name for entry in index}
    inspections: list[LegacyFileInspection] = []
    aggregate: set[LegacyQualityTag] = set()
    for entry in index:
        name = Path(str(entry.get("archive", ""))).name
        path = actual_by_name.get(name)
        if path is None:
            aggregate.add(LegacyQualityTag.MISSING_ARCHIVE)
            continue
        tags: set[LegacyQualityTag] = set()
        digest = _sha256(path)
        if digest != entry.get("sha256"):
            tags.add(LegacyQualityTag.CHECKSUM_MISMATCH)
        snapshot_at = _snapshot_at(path)
        if _contains_future_buy_date(path, snapshot_at):
            tags.add(LegacyQualityTag.BUY_DATE_AFTER_SNAPSHOT)
        inspections.append(LegacyFileInspection(path, digest, snapshot_at, tuple(sorted(tags))))
        aggregate.update(tags)
    for name, path in actual_by_name.items():
        if name not in indexed_names:
            tag = LegacyQualityTag.UNINDEXED_FILE
            inspections.append(
                LegacyFileInspection(path, _sha256(path), _snapshot_at(path), (tag,))
            )
            aggregate.add(tag)
    current = holdings / "持仓.csv"
    if current.exists():
        inspections.append(LegacyFileInspection(current, _sha256(current), None, ()))
    return LegacyInspectionReport(
        root,
        tuple(sorted(inspections, key=lambda item: str(item.path))),
        tuple(sorted(aggregate)),
    )
```

- [ ] **Step 5: 运行测试并提交**

Run: `python -m pytest backend/tests/features/legacy_import/test_inspect.py -q`

Expected: `1 passed`。

```bash
git add backend/app/features/legacy_import/models.py backend/app/features/legacy_import/inspect.py backend/tests/features/legacy_import/test_inspect.py
git commit -m "feat: surface legacy holding quality defects without rewriting history"
```

### Task 7: 冻结带乐观锁和审计事件的组合读写端口

**Files:**
- Create: `backend/app/core/portfolio/models.py`
- Create: `backend/app/core/portfolio/writer.py`
- Create: `backend/app/ports/portfolio.py`
- Create: `backend/app/infrastructure/persistence/portfolio_rows.py`
- Create: `backend/app/infrastructure/persistence/portfolio_repository.py`
- Create: `backend/tests/core/portfolio/test_opening_balance_contract.py`
- Create: `backend/tests/core/portfolio/test_writer.py`
- Create: `backend/tests/integration/test_portfolio_repository.py`

- [ ] **Step 1: 写 legacy lot 不伪装策略分类或历史成交的契约测试**

```python
# backend/tests/core/portfolio/test_opening_balance_contract.py
from datetime import datetime, timezone
from decimal import Decimal

from backend.app.core.portfolio.models import (
    OpeningPosition,
    PortfolioLot,
    PortfolioSnapshot,
    PositionOrigin,
    StrategyBook,
)


def test_legacy_opening_position_has_no_trade_or_strategy_book() -> None:
    position = OpeningPosition(
        security_id="000001.SZ",
        quantity=100,
        inherited_unit_cost=Decimal("10.00"),
        effective_at=datetime(2026, 7, 17, 9, 0, tzinfo=timezone.utc),
        source_row_hash="a" * 64,
    )

    assert position.origin is PositionOrigin.LEGACY_OPENING_BALANCE
    assert position.strategy_book is None
    assert position.entry_score is None
    assert position.initial_risk_per_share is None


def test_snapshot_aggregates_add_lots_without_recomputing_entry_state() -> None:
    effective_at = datetime(2026, 7, 17, 9, 31, tzinfo=timezone.utc)
    first = PortfolioLot(
        "lot-1", "000001.SZ", 100, 100, Decimal("10"), effective_at,
        PositionOrigin.RECORDED_TRADE, StrategyBook.CORE, Decimal("75"), Decimal("1"),
        Decimal("9"), Decimal("12"), 0,
    )
    added = PortfolioLot(
        "lot-2", "000001.SZ", 50, 0, Decimal("12"), effective_at,
        PositionOrigin.RECORDED_TRADE, StrategyBook.CORE, Decimal("80"), Decimal("1"),
        Decimal("10"), Decimal("13"), 1,
    )
    snapshot = PortfolioSnapshot("main", effective_at, 2, Decimal("1000"), Decimal("3000"), (first, added))

    position = snapshot.positions[0]

    assert position.quantity == 150
    assert position.available_to_sell == 100
    assert position.average_cost == Decimal("10.66666666666666666666666667")
    assert position.entry_score == Decimal("75")
    assert position.effective_stop == Decimal("10")
    assert position.highest_close == Decimal("13")
    assert position.add_count == 1
```

- [ ] **Step 2: 运行测试，确认 portfolio 模型不存在**

Run: `python -m pytest backend/tests/core/portfolio/test_opening_balance_contract.py -q`

Expected: FAIL，错误包含 `No module named 'backend.app.core.portfolio.models'`。

- [ ] **Step 3: 实现 PortfolioReader 的跨计划稳定类型**

```python
# backend/app/core/portfolio/models.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class PositionOrigin(StrEnum):
    LEGACY_OPENING_BALANCE = "legacy_opening_balance"
    RECORDED_TRADE = "recorded_trade"
    SIMULATED_FILL = "simulated_fill"


class StrategyBook(StrEnum):
    CORE = "core"
    SWING = "swing"


class FillSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class OpeningPosition:
    security_id: str
    quantity: int
    inherited_unit_cost: Decimal
    effective_at: datetime
    source_row_hash: str
    origin: PositionOrigin = PositionOrigin.LEGACY_OPENING_BALANCE
    strategy_book: StrategyBook | None = None
    entry_score: Decimal | None = None
    initial_risk_per_share: Decimal | None = None


@dataclass(frozen=True)
class PortfolioLot:
    lot_id: str
    security_id: str
    quantity: int
    available_to_sell: int
    average_cost: Decimal
    effective_at: datetime
    origin: PositionOrigin
    strategy_book: StrategyBook | None
    entry_score: Decimal | None
    initial_risk_per_share: Decimal | None
    effective_stop: Decimal | None
    highest_close: Decimal | None
    add_count: int


@dataclass(frozen=True)
class PortfolioPosition:
    security_id: str
    strategy_book: StrategyBook | None
    origin: PositionOrigin
    quantity: int
    available_to_sell: int
    average_cost: Decimal
    effective_stop: Decimal | None
    highest_close: Decimal | None
    entry_score: Decimal | None
    initial_risk_per_share: Decimal | None
    add_count: int


@dataclass(frozen=True)
class PortfolioSnapshot:
    portfolio_id: str
    as_of_time: datetime
    version: int
    cash: Decimal
    equity: Decimal
    lots: tuple[PortfolioLot, ...]

    @property
    def positions(self) -> tuple[PortfolioPosition, ...]:
        return aggregate_positions(self.lots)


def aggregate_positions(lots: tuple[PortfolioLot, ...]) -> tuple[PortfolioPosition, ...]:
    groups: dict[tuple[str, StrategyBook | None, PositionOrigin], list[PortfolioLot]] = {}
    for lot in lots:
        groups.setdefault((lot.security_id, lot.strategy_book, lot.origin), []).append(lot)
    positions = []
    for (security_id, strategy_book, origin), group in sorted(groups.items(), key=lambda item: str(item[0])):
        quantity = sum(lot.quantity for lot in group)
        if quantity <= 0:
            continue
        first = min(group, key=lambda lot: lot.effective_at)
        positions.append(
            PortfolioPosition(
                security_id=security_id,
                strategy_book=strategy_book,
                origin=origin,
                quantity=quantity,
                available_to_sell=sum(lot.available_to_sell for lot in group),
                average_cost=sum(lot.average_cost * lot.quantity for lot in group) / quantity,
                effective_stop=max((lot.effective_stop for lot in group if lot.effective_stop is not None), default=None),
                highest_close=max((lot.highest_close for lot in group if lot.highest_close is not None), default=None),
                entry_score=first.entry_score,
                initial_risk_per_share=first.initial_risk_per_share,
                add_count=max(lot.add_count for lot in group),
            )
        )
    return tuple(positions)


@dataclass(frozen=True)
class ManualFillCommand:
    portfolio_id: str
    security_id: str
    side: FillSide
    quantity: int
    price: Decimal
    fee: Decimal
    filled_at: datetime
    strategy_book: StrategyBook | None


@dataclass(frozen=True)
class CorrectionSnapshot:
    portfolio_id: str
    as_of_time: datetime
    cash: Decimal
    equity: Decimal
    lots: tuple[PortfolioLot, ...]


@dataclass(frozen=True)
class PortfolioAuditEvent:
    portfolio_id: str
    event_type: str
    recorded_at: datetime
    expected_version: int
    reason: str
    payload_hash: str
```

```python
# backend/app/ports/portfolio.py
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from backend.app.core.portfolio.models import (
    CorrectionSnapshot,
    ManualFillCommand,
    OpeningPosition,
    PortfolioAuditEvent,
    PortfolioSnapshot,
)


class ConcurrentPortfolioUpdate(RuntimeError):
    pass


class PortfolioReader(Protocol):
    def snapshot(self, *, portfolio_id: str, as_of_time: datetime) -> PortfolioSnapshot: ...


class PortfolioEventStore(Protocol):
    def append(
        self,
        *,
        event: PortfolioAuditEvent,
        payload: object,
        expected_version: int,
    ) -> PortfolioSnapshot: ...


class PortfolioWriter(Protocol):
    def record_manual_fill(
        self,
        command: ManualFillCommand,
        expected_version: int,
    ) -> PortfolioSnapshot: ...

    def replace_positions_for_correction(
        self,
        snapshot: CorrectionSnapshot,
        expected_version: int,
        reason: str,
    ) -> PortfolioSnapshot: ...


class OpeningBalanceWriter(Protocol):
    def apply(
        self,
        *,
        batch_id: str,
        portfolio_id: str,
        effective_at: datetime,
        positions: tuple[OpeningPosition, ...],
    ) -> None: ...
```

- [ ] **Step 4: 写并发冲突、manual fill 审计和 correction 非成交测试**

```python
# backend/tests/core/portfolio/test_writer.py
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from backend.app.core.portfolio.models import CorrectionSnapshot, FillSide, ManualFillCommand, PortfolioSnapshot
from backend.app.core.portfolio.writer import AuditedPortfolioWriter
from backend.app.ports.portfolio import ConcurrentPortfolioUpdate


class MemoryEventStore:
    def __init__(self) -> None:
        self.version = 3
        self.events: list[tuple[object, object]] = []

    def append(self, *, event, payload, expected_version) -> PortfolioSnapshot:
        if expected_version != self.version:
            raise ConcurrentPortfolioUpdate("portfolio version conflict")
        self.events.append((event, payload))
        self.version += 1
        return PortfolioSnapshot(
            "main",
            datetime(2026, 7, 17, 15, 30, tzinfo=timezone.utc),
            self.version,
            Decimal("150000"),
            Decimal("150000"),
            (),
        )


def test_manual_fill_uses_expected_version_and_audit_event() -> None:
    store = MemoryEventStore()
    writer = AuditedPortfolioWriter(store)
    command = ManualFillCommand(
        "main", "000001.SZ", FillSide.BUY, 100, Decimal("10"), Decimal("5"),
        datetime(2026, 7, 17, 9, 31, tzinfo=timezone.utc), None,
    )

    writer.record_manual_fill(command, expected_version=3)

    event, payload = store.events[0]
    assert event.event_type == "manual_fill"
    assert event.expected_version == 3
    assert payload == command


def test_stale_writer_is_rejected_without_event() -> None:
    store = MemoryEventStore()
    writer = AuditedPortfolioWriter(store)
    command = ManualFillCommand(
        "main", "000001.SZ", FillSide.SELL, 100, Decimal("11"), Decimal("5"),
        datetime(2026, 7, 17, 9, 31, tzinfo=timezone.utc), None,
    )

    with pytest.raises(ConcurrentPortfolioUpdate, match="version conflict"):
        writer.record_manual_fill(command, expected_version=2)
    assert store.events == []


def test_correction_requires_reason_and_is_not_a_fill() -> None:
    store = MemoryEventStore()
    writer = AuditedPortfolioWriter(store)
    correction = CorrectionSnapshot(
        "main",
        datetime(2026, 7, 17, 15, 30, tzinfo=timezone.utc),
        Decimal("150000"),
        Decimal("150000"),
        (),
    )

    writer.replace_positions_for_correction(correction, expected_version=3, reason="核对券商结单后修正")

    event, _ = store.events[0]
    assert event.event_type == "position_correction"
    assert event.reason == "核对券商结单后修正"
```

- [ ] **Step 5: 实现只生成审计事件的领域 writer**

```python
# backend/app/core/portfolio/writer.py
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone

from backend.app.core.portfolio.models import (
    CorrectionSnapshot,
    ManualFillCommand,
    PortfolioAuditEvent,
    PortfolioSnapshot,
)
from backend.app.ports.portfolio import PortfolioEventStore


def _payload_hash(payload: object) -> str:
    body = json.dumps(asdict(payload), sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class AuditedPortfolioWriter:
    def __init__(self, store: PortfolioEventStore) -> None:
        self._store = store

    def record_manual_fill(
        self,
        command: ManualFillCommand,
        expected_version: int,
    ) -> PortfolioSnapshot:
        event = PortfolioAuditEvent(
            command.portfolio_id,
            "manual_fill",
            datetime.now(timezone.utc),
            expected_version,
            "用户录入真实成交",
            _payload_hash(command),
        )
        return self._store.append(event=event, payload=command, expected_version=expected_version)

    def replace_positions_for_correction(
        self,
        snapshot: CorrectionSnapshot,
        expected_version: int,
        reason: str,
    ) -> PortfolioSnapshot:
        if not reason.strip():
            raise ValueError("correction reason is required")
        event = PortfolioAuditEvent(
            snapshot.portfolio_id,
            "position_correction",
            datetime.now(timezone.utc),
            expected_version,
            reason.strip(),
            _payload_hash(snapshot),
        )
        return self._store.append(event=event, payload=snapshot, expected_version=expected_version)
```

`PortfolioEventStore` 是 01 交付给 03 的 persistence seam：数据库实现必须在同一事务中执行
`UPDATE portfolios SET version = version + 1 WHERE id = :id AND version = :expected_version`，
影响行数为 0 时抛出 `ConcurrentPortfolioUpdate`；随后写不可变审计事件。correction 事件只能重建
当前快照，不能写入 `fills`、`execution_attempts` 或早于 correction `as_of_time` 的成交。

协调 Agent 在 `backend/app/infrastructure/persistence/portfolio_rows.py` 创建以下 ORM seam，
并在 `20260716_0002_pit_legacy.py` 创建对应表；03 的 repository 只需实现事件到投影的转换：

```python
from datetime import datetime

from decimal import Decimal

from sqlalchemy import DateTime, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.infrastructure.persistence.models import Base


class PortfolioVersionRow(Base):
    __tablename__ = "portfolio_versions"
    portfolio_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PortfolioSnapshotProjectionRow(Base):
    __tablename__ = "portfolio_snapshot_projections"
    portfolio_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    as_of_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cash: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    equity: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)


class PortfolioLotProjectionRow(Base):
    __tablename__ = "portfolio_lot_projections"
    lot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    security_id: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    available_to_sell: Mapped[int] = mapped_column(Integer, nullable=False)
    average_cost: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    strategy_book: Mapped[str | None] = mapped_column(String(16))
    entry_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    initial_risk_per_share: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    effective_stop: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    highest_close: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    add_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PortfolioAuditEventRow(Base):
    __tablename__ = "portfolio_audit_events"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "resulting_version", name="uq_portfolio_event_version"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    expected_version: Mapped[int] = mapped_column(Integer, nullable=False)
    resulting_version: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
```

```python
# backend/app/infrastructure/persistence/portfolio_repository.py
import json
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.portfolio.models import (
    CorrectionSnapshot,
    FillSide,
    ManualFillCommand,
    PortfolioAuditEvent,
    PortfolioLot,
    PortfolioSnapshot,
    PositionOrigin,
    StrategyBook,
)
from backend.app.infrastructure.persistence.portfolio_rows import (
    PortfolioAuditEventRow,
    PortfolioLotProjectionRow,
    PortfolioSnapshotProjectionRow,
    PortfolioVersionRow,
)
from backend.app.ports.portfolio import ConcurrentPortfolioUpdate


class SqlPortfolioReader:
    def __init__(self, session: Session) -> None:
        self._session = session

    def snapshot(self, *, portfolio_id: str, as_of_time: datetime) -> PortfolioSnapshot:
        version = self._session.get(PortfolioVersionRow, portfolio_id)
        projection = self._session.get(PortfolioSnapshotProjectionRow, portfolio_id)
        if version is None or projection is None:
            raise LookupError(f"portfolio not found: {portfolio_id}")
        if projection.as_of_time > as_of_time:
            raise LookupError("portfolio projection is newer than requested as_of_time")
        rows = self._session.scalars(
            select(PortfolioLotProjectionRow).where(
                PortfolioLotProjectionRow.portfolio_id == portfolio_id,
                PortfolioLotProjectionRow.effective_at <= as_of_time,
                PortfolioLotProjectionRow.quantity > 0,
            )
        ).all()
        lots = tuple(
            PortfolioLot(
                row.lot_id,
                row.security_id,
                row.quantity,
                row.available_to_sell,
                row.average_cost,
                row.effective_at,
                PositionOrigin(row.origin),
                StrategyBook(row.strategy_book) if row.strategy_book else None,
                row.entry_score,
                row.initial_risk_per_share,
                row.effective_stop,
                row.highest_close,
                row.add_count,
            )
            for row in rows
        )
        return PortfolioSnapshot(
            portfolio_id,
            projection.as_of_time,
            version.version,
            projection.cash,
            projection.equity,
            lots,
        )


class SessionScopedPortfolioReader:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def snapshot(self, *, portfolio_id: str, as_of_time: datetime) -> PortfolioSnapshot:
        with self._session_factory() as session:
            return SqlPortfolioReader(session).snapshot(
                portfolio_id=portfolio_id,
                as_of_time=as_of_time,
            )


class SqlPortfolioEventStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def append(
        self,
        *,
        event: PortfolioAuditEvent,
        payload: object,
        expected_version: int,
    ) -> PortfolioSnapshot:
        with self._session_factory.begin() as session:
            result = session.execute(
                update(PortfolioVersionRow)
                .where(
                    PortfolioVersionRow.portfolio_id == event.portfolio_id,
                    PortfolioVersionRow.version == expected_version,
                )
                .values(version=expected_version + 1)
            )
            if result.rowcount != 1:
                raise ConcurrentPortfolioUpdate("portfolio version conflict")
            session.add(
                PortfolioAuditEventRow(
                    portfolio_id=event.portfolio_id,
                    event_type=event.event_type,
                    expected_version=expected_version,
                    resulting_version=expected_version + 1,
                    recorded_at=event.recorded_at,
                    reason=event.reason,
                    payload_hash=event.payload_hash,
                    payload_json=json.dumps(payload.__dict__, sort_keys=True, default=str),
                )
            )
            if isinstance(payload, ManualFillCommand):
                self._apply_manual_fill(session, payload, event.payload_hash)
                as_of_time = payload.filled_at
            elif isinstance(payload, CorrectionSnapshot):
                self._apply_correction(session, payload)
                as_of_time = payload.as_of_time
            else:
                raise TypeError(f"unsupported portfolio payload: {type(payload).__name__}")
            session.flush()
            snapshot = SqlPortfolioReader(session).snapshot(
                portfolio_id=event.portfolio_id,
                as_of_time=as_of_time,
            )
        return snapshot

    @staticmethod
    def _apply_manual_fill(
        session: Session,
        command: ManualFillCommand,
        payload_hash: str,
    ) -> None:
        projection = session.get(PortfolioSnapshotProjectionRow, command.portfolio_id)
        if projection is None:
            raise LookupError(f"portfolio not found: {command.portfolio_id}")
        notional = command.price * command.quantity
        if command.side is FillSide.BUY:
            required_cash = notional + command.fee
            if projection.cash < required_cash:
                raise ValueError("insufficient cash for manual fill")
            projection.cash -= required_cash
            projection.equity -= command.fee
            session.add(
                PortfolioLotProjectionRow(
                    lot_id=f"manual-{payload_hash[:24]}",
                    portfolio_id=command.portfolio_id,
                    security_id=command.security_id,
                    quantity=command.quantity,
                    available_to_sell=0,
                    average_cost=required_cash / command.quantity,
                    effective_at=command.filled_at,
                    origin=PositionOrigin.RECORDED_TRADE.value,
                    strategy_book=(
                        command.strategy_book.value if command.strategy_book else None
                    ),
                    entry_score=None,
                    initial_risk_per_share=None,
                    effective_stop=None,
                    highest_close=command.price,
                    add_count=0,
                )
            )
        else:
            rows = session.scalars(
                select(PortfolioLotProjectionRow)
                .where(
                    PortfolioLotProjectionRow.portfolio_id == command.portfolio_id,
                    PortfolioLotProjectionRow.security_id == command.security_id,
                    PortfolioLotProjectionRow.available_to_sell > 0,
                )
                .order_by(PortfolioLotProjectionRow.effective_at)
            ).all()
            remaining = command.quantity
            for row in rows:
                sold = min(remaining, row.available_to_sell, row.quantity)
                row.quantity -= sold
                row.available_to_sell -= sold
                remaining -= sold
                if remaining == 0:
                    break
            if remaining:
                raise ValueError("insufficient sellable quantity for manual fill")
            projection.cash += notional - command.fee
            projection.equity -= command.fee
        projection.as_of_time = command.filled_at

    @staticmethod
    def _apply_correction(session: Session, snapshot: CorrectionSnapshot) -> None:
        projection = session.get(PortfolioSnapshotProjectionRow, snapshot.portfolio_id)
        if projection is None:
            raise LookupError(f"portfolio not found: {snapshot.portfolio_id}")
        session.execute(
            delete(PortfolioLotProjectionRow).where(
                PortfolioLotProjectionRow.portfolio_id == snapshot.portfolio_id
            )
        )
        for lot in snapshot.lots:
            session.add(
                PortfolioLotProjectionRow(
                    lot_id=lot.lot_id,
                    portfolio_id=snapshot.portfolio_id,
                    security_id=lot.security_id,
                    quantity=lot.quantity,
                    available_to_sell=lot.available_to_sell,
                    average_cost=lot.average_cost,
                    effective_at=lot.effective_at,
                    origin=lot.origin.value,
                    strategy_book=lot.strategy_book.value if lot.strategy_book else None,
                    entry_score=lot.entry_score,
                    initial_risk_per_share=lot.initial_risk_per_share,
                    effective_stop=lot.effective_stop,
                    highest_close=lot.highest_close,
                    add_count=lot.add_count,
                )
            )
        projection.as_of_time = snapshot.as_of_time
        projection.cash = snapshot.cash
        projection.equity = snapshot.equity
```

```python
# backend/tests/integration/test_portfolio_repository.py
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from backend.app.core.portfolio.models import FillSide, ManualFillCommand
from backend.app.core.portfolio.writer import AuditedPortfolioWriter
from backend.app.infrastructure.persistence.portfolio_repository import SqlPortfolioEventStore
from backend.app.infrastructure.persistence.portfolio_rows import PortfolioAuditEventRow
from backend.app.ports.portfolio import ConcurrentPortfolioUpdate


def test_stale_database_write_rolls_back_without_second_audit_event(
    session_factory,
    seeded_portfolio,
) -> None:
    writer = AuditedPortfolioWriter(SqlPortfolioEventStore(session_factory))
    command = ManualFillCommand(
        "main",
        "000001.SZ",
        FillSide.BUY,
        100,
        Decimal("10"),
        Decimal("5"),
        datetime.fromisoformat("2026-07-17T09:31:00+08:00"),
        None,
    )

    writer.record_manual_fill(command, expected_version=0)
    with pytest.raises(ConcurrentPortfolioUpdate):
        writer.record_manual_fill(command, expected_version=0)

    with session_factory() as session:
        count = session.scalar(select(func.count()).select_from(PortfolioAuditEventRow))
    assert count == 1
```

- [ ] **Step 6: 运行测试和类型检查并提交**

Run:

```bash
python -m pytest backend/tests/core/portfolio backend/tests/integration/test_portfolio_repository.py -q
python -m mypy backend/app/core/portfolio backend/app/ports/portfolio.py
```

Expected: pytest `5 passed`；mypy 输出 `Success: no issues found`。

```bash
git add backend/app/core/portfolio backend/app/ports/portfolio.py backend/tests/core/portfolio
git commit -m "feat: audit portfolio writes with optimistic concurrency"
```

### Task 8: 幂等保存原始字节、质量报告和 opening positions

**Files:**
- Create: `backend/app/infrastructure/persistence/legacy_rows.py`
- Create: `backend/app/features/legacy_import/repository.py`
- Create: `backend/app/features/legacy_import/service.py`
- Create: `backend/app/features/legacy_import/build.py`
- Modify: `backend/migrations/versions/20260716_0002_pit_legacy.py`
- Create: `backend/tests/features/legacy_import/conftest.py`
- Create: `backend/tests/features/legacy_import/test_service.py`
- Create: `backend/tests/integration/test_legacy_repository.py`

- [ ] **Step 1: 写 effective_at、原始字节、幂等和零成交测试**

```python
# backend/tests/features/legacy_import/conftest.py
from pathlib import Path

import pytest


@pytest.fixture
def legacy_source(tmp_path: Path) -> Path:
    holdings = tmp_path / "la-source" / "data" / "holdings"
    history = holdings / "历史持仓"
    history.mkdir(parents=True)
    body = (
        "ts_code,symbol,name,asset_type,industry,quantity,cost_price,buy_date,highest_price_since_buy,notes\n"
        "000001.SZ,000001,平安银行,stock,银行,100,10.00,2024-01-01,,,\n"
    )
    (holdings / "持仓.csv").write_text(body, encoding="utf-8")
    (history / "2024-01-02_1200_持仓.csv").write_text(body, encoding="utf-8")
    return holdings.parents[1]
```

```python
# backend/tests/features/legacy_import/test_service.py
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.app.features.legacy_import.service import LegacyImportService


class MemoryRepository:
    def __init__(self) -> None:
        self.batches: dict[str, object] = {}
        self.openings: list[object] = []
        self.snapshots: list[object] = []
        self.fills: list[object] = []

    def save(self, batch, raw_files, positions, snapshots) -> bool:
        if batch.batch_id in self.batches:
            return False
        self.batches[batch.batch_id] = batch
        self.openings.extend(positions)
        self.snapshots.extend(snapshots)
        return True


def test_import_requires_aware_effective_at(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="effective_at must be timezone-aware"):
        LegacyImportService(tmp_path / "imports", MemoryRepository()).import_source(
            source_root=tmp_path,
            portfolio_id="main",
            effective_at=datetime(2026, 7, 17, 9, 0),
        )


def test_same_import_is_idempotent_and_never_creates_fills(legacy_source: Path, tmp_path: Path) -> None:
    repository = MemoryRepository()
    service = LegacyImportService(tmp_path / "imports", repository)
    effective_at = datetime(2026, 7, 17, 9, 0, tzinfo=timezone.utc)

    first = service.import_source(source_root=legacy_source, portfolio_id="main", effective_at=effective_at)
    second = service.import_source(source_root=legacy_source, portfolio_id="main", effective_at=effective_at)

    assert first.batch_id == second.batch_id
    assert len(repository.batches) == 1
    assert len(repository.snapshots) == 1
    assert repository.fills == []
    assert (tmp_path / "imports" / first.batch_id / "raw" / "current" / "持仓.csv").read_bytes() == (
        legacy_source / "data" / "holdings" / "持仓.csv"
    ).read_bytes()
```

- [ ] **Step 2: 创建 legacy ORM；表中不存在成交价格、成交时间或订单字段**

```python
# backend/app/infrastructure/persistence/legacy_rows.py
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.infrastructure.persistence.models import Base


class LegacyImportBatchRow(Base):
    __tablename__ = "legacy_import_batches"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_root: Mapped[str] = mapped_column(Text, nullable=False)
    source_git_state: Mapped[str] = mapped_column(String(128), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    portfolio_id: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    quality_report_json: Mapped[str] = mapped_column(Text, nullable=False)


class LegacyRawFileRow(Base):
    __tablename__ = "legacy_raw_files"
    __table_args__ = (UniqueConstraint("batch_id", "relative_path", name="uq_legacy_raw_batch_path"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("legacy_import_batches.id"), nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    quality_tags_json: Mapped[str] = mapped_column(Text, nullable=False)


class LegacyPositionSnapshotRow(Base):
    __tablename__ = "legacy_position_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("legacy_import_batches.id"), nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    security_id: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    inherited_unit_cost: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    imported_buy_date: Mapped[str | None] = mapped_column(String(10))
    source_file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_row_json: Mapped[str] = mapped_column(Text, nullable=False)


class OpeningPositionRow(Base):
    __tablename__ = "opening_positions"
    __table_args__ = (UniqueConstraint("batch_id", "security_id", name="uq_opening_batch_security"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("legacy_import_batches.id"), nullable=False)
    portfolio_id: Mapped[str] = mapped_column(String(64), nullable=False)
    security_id: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    inherited_unit_cost: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    source_row_hash: Mapped[str] = mapped_column(String(64), nullable=False)
```

- [ ] **Step 3: 实现导入服务的不可变复制、CSV 解析与批次 id**

```python
# backend/app/features/legacy_import/service.py
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from backend.app.core.portfolio.models import OpeningPosition
from backend.app.features.legacy_import.inspect import inspect_source


@dataclass(frozen=True)
class ImportedBatch:
    batch_id: str
    source_root: str
    source_git_state: str
    imported_at: datetime
    effective_at: datetime
    portfolio_id: str
    manifest_sha256: str
    quality_report_json: str


@dataclass(frozen=True)
class ImportedHistoricalPosition:
    snapshot_at: datetime
    security_id: str
    quantity: int
    inherited_unit_cost: Decimal
    imported_buy_date: str | None
    source_file_sha256: str
    raw_row_json: str


@dataclass(frozen=True)
class ImportedRawFile:
    relative_path: str
    sha256: str
    quality_tags_json: str


class LegacyRepository(Protocol):
    def save(
        self,
        batch: ImportedBatch,
        raw_files: tuple[ImportedRawFile, ...],
        positions: tuple[OpeningPosition, ...],
        historical_snapshots: tuple[ImportedHistoricalPosition, ...],
    ) -> bool: ...


def _git_state(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "not-a-git-worktree"


class LegacyImportService:
    def __init__(self, imports_root: Path, repository: LegacyRepository) -> None:
        self._imports_root = imports_root.resolve()
        self._repository = repository

    def import_source(self, *, source_root: Path, portfolio_id: str, effective_at: datetime) -> ImportedBatch:
        if effective_at.tzinfo is None:
            raise ValueError("effective_at must be timezone-aware")
        report = inspect_source(source_root)
        source_files = tuple(item for item in report.files if item.path.is_file())
        imported_raw_files: list[ImportedRawFile] = []
        manifest = {
            "portfolio_id": portfolio_id,
            "effective_at": effective_at.isoformat(),
            "files": [{"path": str(item.path.relative_to(report.source_root)), "sha256": item.sha256} for item in source_files],
        }
        canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        batch_id = digest[:24]
        raw_root = self._imports_root / batch_id / "raw"
        for item in source_files:
            relative = item.path.relative_to(report.source_root / "data" / "holdings")
            destination = raw_root / ("current" if relative.name == "持仓.csv" else "history") / relative.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() != item.sha256:
                raise RuntimeError(f"frozen raw file hash conflict: {destination}")
            if not destination.exists():
                shutil.copyfile(item.path, destination)
            imported_raw_files.append(
                ImportedRawFile(
                    relative_path=str(destination.relative_to(self._imports_root / batch_id)),
                    sha256=item.sha256,
                    quality_tags_json=json.dumps([tag.value for tag in item.tags], ensure_ascii=False),
                )
            )
        current = report.source_root / "data" / "holdings" / "持仓.csv"
        positions = self._parse_opening_positions(current, effective_at)
        historical_snapshots = tuple(
            row
            for item in report.files
            if item.snapshot_at is not None
            for row in self._parse_historical_snapshot(item.path, item.snapshot_at, item.sha256)
        )
        quality_json = json.dumps(
            {
                "tags": [tag.value for tag in report.tags],
                "files": [
                    {
                        "source_path": str(item.path),
                        "sha256": item.sha256,
                        "snapshot_at": item.snapshot_at.isoformat() if item.snapshot_at else None,
                        "tags": [tag.value for tag in item.tags],
                    }
                    for item in report.files
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        batch = ImportedBatch(
            batch_id,
            str(report.source_root),
            _git_state(report.source_root),
            datetime.now(timezone.utc),
            effective_at,
            portfolio_id,
            digest,
            quality_json,
        )
        self._repository.save(batch, tuple(imported_raw_files), positions, historical_snapshots)
        return batch

    @staticmethod
    def _parse_opening_positions(path: Path, effective_at: datetime) -> tuple[OpeningPosition, ...]:
        positions: list[OpeningPosition] = []
        with path.open(encoding="utf-8-sig", newline="") as stream:
            for line_number, row in enumerate(csv.DictReader(stream), start=2):
                canonical = json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8")
                positions.append(
                    OpeningPosition(
                        security_id=row["ts_code"].strip(),
                        quantity=int(row["quantity"]),
                        inherited_unit_cost=Decimal(row["cost_price"]),
                        effective_at=effective_at,
                        source_row_hash=hashlib.sha256(canonical + str(line_number).encode()).hexdigest(),
                    )
                )
        return tuple(positions)

    @staticmethod
    def _parse_historical_snapshot(
        path: Path,
        snapshot_at: datetime,
        source_file_sha256: str,
    ) -> tuple[ImportedHistoricalPosition, ...]:
        rows: list[ImportedHistoricalPosition] = []
        with path.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                rows.append(
                    ImportedHistoricalPosition(
                        snapshot_at=snapshot_at,
                        security_id=row["ts_code"].strip(),
                        quantity=int(row["quantity"]),
                        inherited_unit_cost=Decimal(row["cost_price"]),
                        imported_buy_date=(row.get("buy_date") or "").strip() or None,
                        source_file_sha256=source_file_sha256,
                        raw_row_json=json.dumps(row, ensure_ascii=False, sort_keys=True),
                    )
                )
        return tuple(rows)
```

- [ ] **Step 4: 实现 SQL 仓储并由协调 Agent 完成同一迁移**

```python
# backend/app/features/legacy_import/repository.py
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.portfolio.models import OpeningPosition
from backend.app.features.legacy_import.service import ImportedBatch, ImportedHistoricalPosition, ImportedRawFile
from backend.app.infrastructure.persistence.legacy_rows import (
    LegacyImportBatchRow,
    LegacyPositionSnapshotRow,
    LegacyRawFileRow,
    OpeningPositionRow,
)


class SqlLegacyRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save(
        self,
        batch: ImportedBatch,
        raw_files: tuple[ImportedRawFile, ...],
        positions: tuple[OpeningPosition, ...],
        historical_snapshots: tuple[ImportedHistoricalPosition, ...],
    ) -> bool:
        existing = self._session.scalar(
            select(LegacyImportBatchRow).where(LegacyImportBatchRow.manifest_sha256 == batch.manifest_sha256)
        )
        if existing is not None:
            return False
        self._session.add(LegacyImportBatchRow(id=batch.batch_id, **{key: value for key, value in batch.__dict__.items() if key != "batch_id"}))
        self._session.add_all(
            LegacyRawFileRow(
                batch_id=batch.batch_id,
                relative_path=item.relative_path,
                sha256=item.sha256,
                quality_tags_json=item.quality_tags_json,
            )
            for item in raw_files
        )
        self._session.add_all(
            OpeningPositionRow(
                batch_id=batch.batch_id,
                portfolio_id=batch.portfolio_id,
                security_id=position.security_id,
                quantity=position.quantity,
                inherited_unit_cost=position.inherited_unit_cost,
                effective_at=position.effective_at,
                origin=position.origin.value,
                source_row_hash=position.source_row_hash,
            )
            for position in positions
        )
        self._session.add_all(
            LegacyPositionSnapshotRow(
                batch_id=batch.batch_id,
                snapshot_at=item.snapshot_at,
                security_id=item.security_id,
                quantity=item.quantity,
                inherited_unit_cost=item.inherited_unit_cost,
                imported_buy_date=item.imported_buy_date,
                source_file_sha256=item.source_file_sha256,
                raw_row_json=item.raw_row_json,
            )
            for item in historical_snapshots
        )
        self._session.flush()
        return True
```

```python
# backend/app/features/legacy_import/build.py
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from backend.app.features.legacy_import.repository import SqlLegacyRepository
from backend.app.features.legacy_import.service import LegacyImportService


@dataclass(frozen=True)
class LegacyImportDependencies:
    session_factory: Callable[[], Session]
    imports_root: Path


def build_legacy_import_service(
    *,
    session: Session,
    imports_root: Path,
) -> LegacyImportService:
    return LegacyImportService(imports_root, SqlLegacyRepository(session))
```

```python
# backend/tests/integration/test_legacy_repository.py
from datetime import datetime

from sqlalchemy import func, select

from backend.app.features.legacy_import.build import build_legacy_import_service
from backend.app.infrastructure.persistence.legacy_rows import (
    LegacyImportBatchRow,
    LegacyPositionSnapshotRow,
    LegacyRawFileRow,
    OpeningPositionRow,
)


def test_sql_repository_persists_manifest_snapshots_and_opening_only_once(
    db_session,
    legacy_source,
    tmp_path,
) -> None:
    service = build_legacy_import_service(session=db_session, imports_root=tmp_path / "imports")
    effective_at = datetime.fromisoformat("2026-07-17T09:00:00+08:00")

    service.import_source(source_root=legacy_source, portfolio_id="main", effective_at=effective_at)
    service.import_source(source_root=legacy_source, portfolio_id="main", effective_at=effective_at)
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(LegacyImportBatchRow)) == 1
    assert db_session.scalar(select(func.count()).select_from(LegacyRawFileRow)) == 2
    assert db_session.scalar(select(func.count()).select_from(LegacyPositionSnapshotRow)) == 1
    assert db_session.scalar(select(func.count()).select_from(OpeningPositionRow)) == 1
```

协调 Agent 在 `20260716_0002_pit_legacy.py` 增加
`legacy_import_batches`、`legacy_raw_files`、`legacy_position_snapshots`、`opening_positions` 及上述唯一约束；
`downgrade()` 以反向顺序删除这些表后再删除 Task 3 的表。

- [ ] **Step 5: 运行服务、PostgreSQL 和迁移回滚测试并提交**

Run:

```bash
python -m pytest backend/tests/features/legacy_import/test_service.py backend/tests/integration/test_legacy_repository.py -q
alembic upgrade head
alembic downgrade 20260716_0001
alembic upgrade head
```

Expected: pytest 全部 PASS；迁移可正向、反向、再次正向执行；数据库中不存在由导入器创建的
`fills` 或 `execution_attempts` 行。

```bash
git add backend/app/features/legacy_import backend/app/infrastructure/persistence/legacy_rows.py backend/migrations/versions/20260716_0002_pit_legacy.py backend/tests/features/legacy_import backend/tests/integration/test_legacy_repository.py
git commit -m "feat: import legacy bytes idempotently without inventing fills"
```

### Task 9: 提供显式 CLI 并验证源目录只读和 DA 独立性

**Files:**
- Create: `backend/app/features/legacy_import/cli.py`
- Create: `backend/tests/features/legacy_import/test_cli.py`
- Create: `backend/tests/architecture/test_da_independence.py`

- [ ] **Step 1: 写 CLI 缺少 effective_at、成功报告和独立性测试**

```python
# backend/tests/features/legacy_import/test_cli.py
from backend.app.features.legacy_import.cli import build_parser


def test_cli_requires_source_root_effective_at_and_portfolio() -> None:
    parser = build_parser()
    parsed = parser.parse_args(
        ["--source-root", "/read-only/source", "--effective-at", "2026-07-17T09:00:00+08:00", "--portfolio-id", "main"]
    )

    assert parsed.source_root == "/read-only/source"
    assert parsed.effective_at.endswith("+08:00")
    assert parsed.portfolio_id == "main"
```

```python
# backend/tests/architecture/test_da_independence.py
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_runtime_source_does_not_reference_la_or_import_outside_da() -> None:
    forbidden = ("/Users/bujiatang/workspace/LA", "workspace.LA", "PYTHONPATH")
    runtime_files = tuple((PROJECT_ROOT / "backend" / "app").rglob("*.py"))

    violations = [str(path) for path in runtime_files if any(token in path.read_text(encoding="utf-8") for token in forbidden)]

    assert violations == []


def test_da_contains_no_symlinks() -> None:
    assert [str(path) for path in PROJECT_ROOT.rglob("*") if path.is_symlink()] == []
```

- [ ] **Step 2: 实现 argparse 入口；数据库 session 使用 00 的 session factory**

```python
# backend/app/features/legacy_import/cli.py
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from backend.app.bootstrap.settings import Settings
from backend.app.infrastructure.persistence.database import build_engine, build_session_factory
from backend.app.features.legacy_import.repository import SqlLegacyRepository
from backend.app.features.legacy_import.service import LegacyImportService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="da-legacy-import")
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--effective-at", required=True)
    parser.add_argument("--portfolio-id", required=True)
    parser.add_argument("--imports-root", default="data/imports")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    effective_at = datetime.fromisoformat(args.effective_at)
    settings = Settings()
    engine = build_engine(settings.database_url)
    sessions = build_session_factory(engine)
    with sessions.begin() as session:
        service = LegacyImportService(Path(args.imports_root), SqlLegacyRepository(session))
        batch = service.import_source(
            source_root=Path(args.source_root),
            portfolio_id=args.portfolio_id,
            effective_at=effective_at,
        )
    print(
        json.dumps(
            {
                "batch_id": batch.batch_id,
                "effective_at": batch.effective_at.isoformat(),
                "manifest_sha256": batch.manifest_sha256,
                "origin": "legacy_opening_balance",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: 在只读 fixture 上执行两次导入并比较源树哈希**

Run:

```bash
find backend/tests/fixtures/legacy_la -type f -exec shasum -a 256 {} \; | sort > /tmp/legacy-before.sha
chmod -R a-w backend/tests/fixtures/legacy_la
python -m backend.app.features.legacy_import.cli --source-root backend/tests/fixtures/legacy_la --effective-at 2026-07-17T09:00:00+08:00 --portfolio-id main --imports-root data/imports
python -m backend.app.features.legacy_import.cli --source-root backend/tests/fixtures/legacy_la --effective-at 2026-07-17T09:00:00+08:00 --portfolio-id main --imports-root data/imports
find backend/tests/fixtures/legacy_la -type f -exec shasum -a 256 {} \; | sort > /tmp/legacy-after.sha
diff -u /tmp/legacy-before.sha /tmp/legacy-after.sha
```

Expected: 两次命令输出相同 `batch_id`；`diff` 无输出；数据库只有一个 batch；opening positions
从 `effective_at` 开始可见，之前不可见；成交表保持空。

- [ ] **Step 4: 运行计划验收集并提交**

Run:

```bash
python -m pytest backend/tests/core/market backend/tests/core/portfolio backend/tests/infrastructure/market backend/tests/features/legacy_import backend/tests/architecture/test_da_independence.py -q
python -m mypy backend/app/core/market backend/app/core/portfolio backend/app/ports backend/app/features/legacy_import backend/app/infrastructure/market
```

Expected: pytest 全部 PASS；mypy 输出 `Success: no issues found`；输出和日志不包含持仓备注正文。

```bash
git add backend/app/features/legacy_import/cli.py backend/tests/features/legacy_import/test_cli.py backend/tests/architecture/test_da_independence.py
git commit -m "feat: expose an explicit read-only legacy import boundary"
```

## 完成定义

- 00 冻结的 DA 策略与 `strategies/manifest.json` 哈希一致；01 不创建第二套策略注册表。
- research 快照始终是 `DataGrade.RESEARCH`，即使供应商返回多年历史也不能自行晋级。
- research adapters 覆盖 calendar、universe、raw bars、quote、financial、official policy 和
  DeepSeek 结构化因子；LLM action/quantity、未知证据和未来证据全部拒绝。
- 02/03/04 共用三参数 `StrategyInputBuilder` 和 00 的 `V212StrategyEngine`，没有第二套指标。
- 每条进入策略的记录都有 `available_at`、源 hash 和 manifest；未来记录在快照出口被拒绝。
- 导入报告完整保留 `missing_archive`、`checksum_mismatch`、`unindexed_file`、
  `buy_date_after_snapshot`，不修改异常 CSV。
- Legacy 当前持仓只形成 `legacy_opening_balance`，不产生历史订单、成交或导入日前收益。
- 同一源 manifest、组合和 `effective_at` 重复导入幂等；原始字节位于
  `data/imports/<batch_id>/raw/` 且 SHA-256 可复核。
- 组合手工成交和 correction 使用乐观 version、不可变审计事件和事务化 projection；
  correction 不伪装为成交，长生命周期依赖只注入 session-scoped reader/store。
- 在 LA 目录不存在的环境中，除用户主动执行 legacy CLI 外，DA 的安装、测试和启动均成功。
