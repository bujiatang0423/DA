# PIT-Verified Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为研究级回测补齐严格历史证券状态、行业、财报修订、政策、复权和 `available_at` 审计，以滚动前推验证策略，并让 `pit_verified` 只能经未来函数门禁授予。

**Architecture:** 严格数据先进入带 checksum 和覆盖范围的 canonical PIT bundle，按追加版本写入 PostgreSQL；任何策略输入仍只通过 01 的 `PointInTimeWarehouse`。严格仓库在证书缺失时失败关闭，毒丸审计对每类数据证明未来记录无法改变历史 manifest 后才签发覆盖区间证书；04 的同一回测引擎随后执行 walk-forward，数据等级、LLM 等级和策略研究门槛分别保存。

**Tech Stack:** Python 3.11、SQLAlchemy 2、PostgreSQL、Alembic、pytest、Hypothesis、04 的 `BacktestEngine`、00 的 `V212StrategyEngine`

---

## 依赖、所有权与不变量

- 阻塞依赖：00、01 和 04 已完成。必须复用：
  - `backend.app.contracts.grades.DataGrade` 与 `LlmGrade`；
  - `backend.app.core.strategy.service.V212StrategyEngine`，不得在本计划重写 P/F/R/T/V/S；
  - `backend.app.ports.point_in_time.PointInTimeWarehouse`、`SnapshotScope`、
    `PointInTimeSnapshot` 和 `TemporalRecord`；
  - `backend.app.features.backtests.engine.BacktestEngine`、
    `backend.app.features.backtests.models.BacktestRequest` 与 `BacktestResult`。
- 本计划独占 `backend/app/infrastructure/market/strict_*`、
  `backend/app/features/backtests/pit_*`、`walk_forward.py` 及对应测试。
- 只有协调 Agent 创建 `backend/migrations/versions/20260716_0003_strict_pit.py` 并修改迁移链。
- `daily_bars_raw` 的价格只用于成交和估值；指标调整序列只由当时已知的 adjustment factor
  派生，二者不能共用字段或回填未来公司行动。
- 严格模式任何必需数据缺失、越界或来源不合格均失败关闭，不能用中性分或当前数据替代。
- `data_grade=pit_verified` 只表示输入时点审计通过，不表示策略收益验收通过；两种状态不得合并。
- 历史 LLM 保持 `llm_grade=reconstructed`，前瞻采集才能是 `forward_observed`。

## 文件职责图

```text
backend/app/infrastructure/market/
├── strict_bundle.py              # canonical bundle manifest、checksum 与文件 schema
├── strict_ingest.py              # 追加式解析和批次入库
├── strict_rows.py                # 全部严格历史 ORM 行
├── strict_queries.py             # as_of universe、状态、行业、财报和政策版本选择
├── adjustment_series.py          # 原始成交价与已知复权因子分离
├── strict_reader.py              # ORM 历史版本到已选 TemporalRecord
├── strict_warehouse.py           # 证书保护的 PointInTimeWarehouse 实现
└── build.py                      # build_strict_pit_warehouse 组合入口
backend/app/features/backtests/
├── pit_audit.py                  # 覆盖检查、毒丸审计和审计报告
├── pit_certificate.py            # 不可伪造的覆盖区间证书仓储
├── walk_forward.py               # 3 年开发/1 年验证/滚动 1 年和保留样本锁
└── pit_promotion.py              # 回测数据等级晋级；不判断收益门槛
backend/app/infrastructure/persistence/strict_pit_rows.py
backend/migrations/versions/20260716_0003_strict_pit.py
```

### Task 1: 定义可校验的 canonical PIT bundle

**Files:**
- Create: `backend/app/infrastructure/market/strict_bundle.py`
- Create: `backend/tests/infrastructure/market/test_strict_bundle.py`
- Create: `backend/tests/fixtures/pit_bundle/manifest.json`
- Create: `backend/tests/fixtures/pit_bundle/security_master_history.csv`
- Create: `backend/tests/fixtures/pit_bundle/security_status_daily.csv`
- Create: `backend/tests/fixtures/pit_bundle/trading_calendar.csv`
- Create: `backend/tests/fixtures/pit_bundle/daily_bars_raw.csv`
- Create: `backend/tests/fixtures/pit_bundle/index_daily_bars.csv`
- Create: `backend/tests/fixtures/pit_bundle/corporate_actions.csv`
- Create: `backend/tests/fixtures/pit_bundle/adjustment_factors.csv`
- Create: `backend/tests/fixtures/pit_bundle/industry_membership_history.csv`
- Create: `backend/tests/fixtures/pit_bundle/theme_membership_history.csv`
- Create: `backend/tests/fixtures/pit_bundle/financial_disclosures.csv`
- Create: `backend/tests/fixtures/pit_bundle/financial_facts.csv`
- Create: `backend/tests/fixtures/pit_bundle/policy_documents.csv`
- Create: `backend/tests/fixtures/pit_bundle/fee_schedules.csv`

- [ ] **Step 1: 写缺文件、checksum 错误和来源缺失测试**

```python
# backend/tests/infrastructure/market/test_strict_bundle.py
import json
from pathlib import Path

import pytest

from backend.app.infrastructure.market.strict_bundle import PitBundleError, PitBundleManifest


def test_bundle_requires_every_strict_dataset(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "bundle_id": "bad", "files": []}),
        encoding="utf-8",
    )

    with pytest.raises(PitBundleError, match="missing required datasets"):
        PitBundleManifest.load(tmp_path)


def test_bundle_rejects_checksum_mismatch(pit_bundle: Path) -> None:
    manifest = json.loads((pit_bundle / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"][0]["sha256"] = "0" * 64
    (pit_bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(PitBundleError, match="checksum mismatch"):
        PitBundleManifest.load(pit_bundle)


def test_verified_source_requires_source_and_license_ids(pit_bundle: Path) -> None:
    bundle = PitBundleManifest.load(pit_bundle)

    assert all(item.source_id and item.license_id for item in bundle.files)
```

- [ ] **Step 2: 运行测试，确认 manifest 类型缺失**

Run: `python -m pytest backend/tests/infrastructure/market/test_strict_bundle.py -q`

Expected: FAIL，错误包含
`No module named 'backend.app.infrastructure.market.strict_bundle'`。

- [ ] **Step 3: 实现精确数据集白名单、路径保护和逐文件验哈希**

```python
# backend/app/infrastructure/market/strict_bundle.py
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path


REQUIRED_DATASETS = frozenset(
    {
        "security_master_history",
        "security_status_daily",
        "trading_calendar",
        "daily_bars_raw",
        "index_daily_bars",
        "corporate_actions",
        "adjustment_factors",
        "industry_membership_history",
        "theme_membership_history",
        "financial_disclosures",
        "financial_facts",
        "policy_documents",
        "fee_schedules",
    }
)


class PitBundleError(ValueError):
    pass


@dataclass(frozen=True)
class PitBundleFile:
    dataset: str
    path: Path
    sha256: str
    row_count: int
    source_id: str
    license_id: str


@dataclass(frozen=True)
class PitBundleManifest:
    schema_version: int
    bundle_id: str
    coverage_start: date
    coverage_end: date
    files: tuple[PitBundleFile, ...]
    manifest_sha256: str

    def file(self, dataset: str) -> PitBundleFile:
        for item in self.files:
            if item.dataset == dataset:
                return item
        raise PitBundleError(f"dataset not found: {dataset}")

    @classmethod
    def load(cls, root: Path) -> "PitBundleManifest":
        resolved_root = root.resolve()
        manifest_path = resolved_root / "manifest.json"
        raw = manifest_path.read_bytes()
        payload = json.loads(raw)
        if payload.get("schema_version") != 1:
            raise PitBundleError("unsupported schema_version")
        entries: list[PitBundleFile] = []
        for item in payload.get("files", []):
            path = (resolved_root / item["path"]).resolve()
            if path.parent != resolved_root:
                raise PitBundleError("bundle file escapes root")
            if not item.get("source_id") or not item.get("license_id"):
                raise PitBundleError("verified source requires source_id and license_id")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != item["sha256"]:
                raise PitBundleError(f"checksum mismatch: {item['dataset']}")
            entries.append(
                PitBundleFile(
                    item["dataset"],
                    path,
                    actual,
                    int(item["row_count"]),
                    item["source_id"],
                    item["license_id"],
                )
            )
        datasets = {entry.dataset for entry in entries}
        missing = REQUIRED_DATASETS - datasets
        if missing:
            raise PitBundleError(f"missing required datasets: {','.join(sorted(missing))}")
        return cls(
            schema_version=1,
            bundle_id=str(payload["bundle_id"]),
            coverage_start=date.fromisoformat(payload["coverage_start"]),
            coverage_end=date.fromisoformat(payload["coverage_end"]),
            files=tuple(entries),
            manifest_sha256=hashlib.sha256(raw).hexdigest(),
        )
```

- [ ] **Step 4: 固定 CSV schema 与最小 fixture**

每个 fixture 第一行为以下精确字段，测试数据至少包含一个过去版本和一个未来修订版本：

```text
security_master_history.csv: record_id,security_id,name,listed_on,delisted_on,valid_from,valid_to,available_at,source_artifact_hash
security_status_daily.csv: record_id,security_id,trade_date,is_st,is_suspended,board,price_limit_pct,available_at,source_artifact_hash
trading_calendar.csv: record_id,exchange,trade_date,is_open,available_at,source_artifact_hash
daily_bars_raw.csv: record_id,security_id,trade_date,open,high,low,close,volume,amount,available_at,source_artifact_hash
index_daily_bars.csv: record_id,index_id,trade_date,open,high,low,close,volume,amount,available_at,source_artifact_hash
corporate_actions.csv: record_id,security_id,ex_date,action_type,ratio,cash_amount,announced_at,available_at,source_artifact_hash
adjustment_factors.csv: record_id,security_id,trade_date,factor,available_at,source_artifact_hash
industry_membership_history.csv: record_id,security_id,industry_id,effective_from,effective_to,available_at,source_artifact_hash
theme_membership_history.csv: record_id,security_id,theme_id,effective_from,effective_to,version,available_at,source_artifact_hash
financial_disclosures.csv: disclosure_id,security_id,report_period,revision,published_at,available_at,source_artifact_hash
financial_facts.csv: record_id,disclosure_id,metric,value,unit,available_at,source_artifact_hash
policy_documents.csv: document_id,published_at,first_observed_at,available_at,evidence_grade,official_parent_id,content_hash,source_artifact_hash
fee_schedules.csv: record_id,effective_from,effective_to,exchange,asset_type,commission_rate,minimum_commission,stamp_tax_sell_rate,transfer_rate,available_at,source_artifact_hash
```

生成 `manifest.json` 时逐文件使用
`shasum -a 256 backend/tests/fixtures/pit_bundle/<file>.csv` 的实际输出，并填入实际数据行数；
不得把示例 hash 写成生产 fixture 的 hash。

- [ ] **Step 5: 运行测试并提交**

Run: `python -m pytest backend/tests/infrastructure/market/test_strict_bundle.py -q`

Expected: `3 passed`。

```bash
git add backend/app/infrastructure/market/strict_bundle.py backend/tests/infrastructure/market/test_strict_bundle.py backend/tests/fixtures/pit_bundle
git commit -m "feat: require checksummed canonical bundles for strict PIT data"
```

### Task 2: 建立追加式严格历史表和原子 ingest

**Files:**
- Create: `backend/app/infrastructure/persistence/strict_pit_rows.py`
- Create: `backend/app/infrastructure/market/strict_ingest.py`
- Create: `backend/migrations/versions/20260716_0003_strict_pit.py`
- Create: `backend/tests/integration/test_strict_ingest.py`

- [ ] **Step 1: 写重复批次幂等、版本不覆盖和错误批次回滚测试**

```python
# backend/tests/integration/test_strict_ingest.py
from pathlib import Path

import pytest
from sqlalchemy import func, select

from backend.app.infrastructure.market.strict_bundle import PitBundleManifest
from backend.app.infrastructure.market.strict_ingest import StrictPitIngestor
from backend.app.infrastructure.persistence.strict_pit_rows import DailyBarRawRow, PitBundleRow


def test_ingest_is_idempotent_and_append_only(db_session, pit_bundle: Path) -> None:
    bundle = PitBundleManifest.load(pit_bundle)
    ingestor = StrictPitIngestor(db_session)

    assert ingestor.ingest(bundle) is True
    assert ingestor.ingest(bundle) is False
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(PitBundleRow)) == 1
    assert db_session.scalar(select(func.count()).select_from(DailyBarRawRow)) == bundle.file("daily_bars_raw").row_count


def test_invalid_decimal_rolls_back_entire_bundle(db_session, broken_pit_bundle: Path) -> None:
    bundle = PitBundleManifest.load(broken_pit_bundle)

    with pytest.raises(ValueError, match="daily_bars_raw.close"):
        StrictPitIngestor(db_session).ingest(bundle)
    db_session.rollback()

    assert db_session.scalar(select(func.count()).select_from(PitBundleRow)) == 0
```

- [ ] **Step 2: 实现表模型，所有版本表均保留 `available_at` 和 source hash**

```python
# backend/app/infrastructure/persistence/strict_pit_rows.py
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.infrastructure.persistence.models import Base


class PitBundleRow(Base):
    __tablename__ = "pit_bundles"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    manifest_sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    coverage_start: Mapped[date] = mapped_column(Date, nullable=False)
    coverage_end: Mapped[date] = mapped_column(Date, nullable=False)


class SecurityMasterHistoryRow(Base):
    __tablename__ = "security_master_history"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    security_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(128))
    listed_on: Mapped[date] = mapped_column(Date)
    delisted_on: Mapped[date | None] = mapped_column(Date)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_artifact_hash: Mapped[str] = mapped_column(String(64))


class SecurityStatusDailyRow(Base):
    __tablename__ = "security_status_daily"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    security_id: Mapped[str] = mapped_column(String(32), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    is_st: Mapped[bool] = mapped_column(Boolean)
    is_suspended: Mapped[bool] = mapped_column(Boolean)
    board: Mapped[str] = mapped_column(String(32))
    price_limit_pct: Mapped[Decimal] = mapped_column(Numeric(8, 4))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_artifact_hash: Mapped[str] = mapped_column(String(64))


class TradingCalendarRow(Base):
    __tablename__ = "trading_calendar"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    exchange: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    is_open: Mapped[bool] = mapped_column(Boolean)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_artifact_hash: Mapped[str] = mapped_column(String(64))


class DailyBarRawRow(Base):
    __tablename__ = "daily_bars_raw"
    __table_args__ = (UniqueConstraint("security_id", "trade_date", "source_artifact_hash", name="uq_raw_bar_version"),)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    security_id: Mapped[str] = mapped_column(String(32), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    high: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    low: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    close: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    volume: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 2))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_artifact_hash: Mapped[str] = mapped_column(String(64))


class IndexDailyBarRow(Base):
    __tablename__ = "index_daily_bars"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    index_id: Mapped[str] = mapped_column(String(32), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    high: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    low: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    close: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    volume: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 2))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_artifact_hash: Mapped[str] = mapped_column(String(64))


class TemporalJsonRow(Base):
    __abstract__ = True
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    security_id: Mapped[str] = mapped_column(String(32), index=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_artifact_hash: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)


class CorporateActionRow(TemporalJsonRow):
    __tablename__ = "corporate_actions"


class AdjustmentFactorRow(TemporalJsonRow):
    __tablename__ = "adjustment_factors"


class IndustryMembershipHistoryRow(TemporalJsonRow):
    __tablename__ = "industry_membership_history"


class ThemeMembershipHistoryRow(TemporalJsonRow):
    __tablename__ = "theme_membership_history"


class FinancialDisclosureRow(Base):
    __tablename__ = "financial_disclosures"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    security_id: Mapped[str] = mapped_column(String(32), index=True)
    report_period: Mapped[date] = mapped_column(Date)
    revision: Mapped[int] = mapped_column(Integer)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_artifact_hash: Mapped[str] = mapped_column(String(64))


class FinancialFactRow(Base):
    __tablename__ = "financial_facts"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    disclosure_id: Mapped[str] = mapped_column(ForeignKey("financial_disclosures.id"), index=True)
    metric: Mapped[str] = mapped_column(String(64))
    value: Mapped[str] = mapped_column(String(128))
    unit: Mapped[str] = mapped_column(String(32))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_artifact_hash: Mapped[str] = mapped_column(String(64))


class PolicyDocumentRow(Base):
    __tablename__ = "policy_documents"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    evidence_grade: Mapped[str] = mapped_column(String(8))
    official_parent_id: Mapped[str | None] = mapped_column(String(128))
    content_hash: Mapped[str] = mapped_column(String(64))
    source_artifact_hash: Mapped[str] = mapped_column(String(64))


class FeeScheduleRow(Base):
    __tablename__ = "fee_schedules"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    exchange: Mapped[str] = mapped_column(String(16))
    asset_type: Mapped[str] = mapped_column(String(16))
    commission_rate: Mapped[Decimal] = mapped_column(Numeric(12, 8))
    minimum_commission: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    stamp_tax_sell_rate: Mapped[Decimal] = mapped_column(Numeric(12, 8))
    transfer_rate: Mapped[Decimal] = mapped_column(Numeric(12, 8))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_artifact_hash: Mapped[str] = mapped_column(String(64))
```

- [ ] **Step 3: 实现 schema 驱动解析与同一事务的 ingest**

```python
# backend/app/infrastructure/market/strict_ingest.py
from __future__ import annotations

import csv
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.infrastructure.market.strict_bundle import PitBundleFile, PitBundleManifest
from backend.app.infrastructure.persistence.strict_pit_rows import (
    DailyBarRawRow,
    FeeScheduleRow,
    IndexDailyBarRow,
    PitBundleRow,
    SecurityMasterHistoryRow,
    SecurityStatusDailyRow,
    TradingCalendarRow,
)


class StrictPitIngestor:
    def __init__(self, session: Session) -> None:
        self._session = session

    def ingest(self, bundle: PitBundleManifest) -> bool:
        existing = self._session.scalar(select(PitBundleRow).where(PitBundleRow.manifest_sha256 == bundle.manifest_sha256))
        if existing is not None:
            return False
        self._session.add(
            PitBundleRow(
                id=bundle.bundle_id,
                manifest_sha256=bundle.manifest_sha256,
                coverage_start=bundle.coverage_start,
                coverage_end=bundle.coverage_end,
            )
        )
        parsers = {
            "security_master_history": self._security_master,
            "security_status_daily": self._security_status,
            "trading_calendar": self._trading_calendar,
            "daily_bars_raw": self._daily_bars,
            "index_daily_bars": self._index_bars,
        }
        for item in bundle.files:
            parser = parsers.get(item.dataset, self._temporal_json_rows)
            rows = parser(item)
            if len(rows) != item.row_count:
                raise ValueError(f"row_count mismatch: {item.dataset}")
            self._session.add_all(rows)
        self._session.flush()
        return True

    @staticmethod
    def _read(item: PitBundleFile) -> list[dict[str, str]]:
        with item.path.open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))

    def _security_master(self, item: PitBundleFile) -> list[SecurityMasterHistoryRow]:
        return [
            SecurityMasterHistoryRow(
                id=row["record_id"], security_id=row["security_id"], name=row["name"],
                listed_on=date.fromisoformat(row["listed_on"]),
                delisted_on=date.fromisoformat(row["delisted_on"]) if row["delisted_on"] else None,
                valid_from=date.fromisoformat(row["valid_from"]),
                valid_to=date.fromisoformat(row["valid_to"]) if row["valid_to"] else None,
                available_at=datetime.fromisoformat(row["available_at"]),
                source_artifact_hash=row["source_artifact_hash"],
            )
            for row in self._read(item)
        ]

    def _security_status(self, item: PitBundleFile) -> list[SecurityStatusDailyRow]:
        return [
            SecurityStatusDailyRow(
                id=row["record_id"], security_id=row["security_id"],
                trade_date=date.fromisoformat(row["trade_date"]),
                is_st=row["is_st"].lower() == "true", is_suspended=row["is_suspended"].lower() == "true",
                board=row["board"], price_limit_pct=Decimal(row["price_limit_pct"]),
                available_at=datetime.fromisoformat(row["available_at"]),
                source_artifact_hash=row["source_artifact_hash"],
            )
            for row in self._read(item)
        ]

    def _daily_bars(self, item: PitBundleFile) -> list[DailyBarRawRow]:
        result: list[DailyBarRawRow] = []
        for row in self._read(item):
            try:
                close = Decimal(row["close"])
            except InvalidOperation as error:
                raise ValueError("daily_bars_raw.close is not decimal") from error
            result.append(
                DailyBarRawRow(
                    id=row["record_id"], security_id=row["security_id"], trade_date=date.fromisoformat(row["trade_date"]),
                    open=Decimal(row["open"]), high=Decimal(row["high"]), low=Decimal(row["low"]), close=close,
                    volume=int(row["volume"]), amount=Decimal(row["amount"]),
                    available_at=datetime.fromisoformat(row["available_at"]), source_artifact_hash=row["source_artifact_hash"],
                )
            )
        return result

    def _trading_calendar(self, item: PitBundleFile) -> list[TradingCalendarRow]:
        return [
            TradingCalendarRow(
                id=row["record_id"], exchange=row["exchange"],
                trade_date=date.fromisoformat(row["trade_date"]),
                is_open=row["is_open"].lower() == "true",
                available_at=datetime.fromisoformat(row["available_at"]),
                source_artifact_hash=row["source_artifact_hash"],
            )
            for row in self._read(item)
        ]

    def _index_bars(self, item: PitBundleFile) -> list[IndexDailyBarRow]:
        return [
            IndexDailyBarRow(
                id=row["record_id"], index_id=row["index_id"],
                trade_date=date.fromisoformat(row["trade_date"]),
                open=Decimal(row["open"]), high=Decimal(row["high"]),
                low=Decimal(row["low"]), close=Decimal(row["close"]),
                volume=int(row["volume"]), amount=Decimal(row["amount"]),
                available_at=datetime.fromisoformat(row["available_at"]),
                source_artifact_hash=row["source_artifact_hash"],
            )
            for row in self._read(item)
        ]

    def _temporal_json_rows(self, item: PitBundleFile) -> list[object]:
        from backend.app.infrastructure.market.strict_row_mapping import parse_temporal_rows

        return parse_temporal_rows(item.dataset, self._read(item))
```

```python
# backend/app/infrastructure/market/strict_row_mapping.py
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

from backend.app.infrastructure.persistence.strict_pit_rows import (
    AdjustmentFactorRow,
    CorporateActionRow,
    FinancialDisclosureRow,
    FinancialFactRow,
    FeeScheduleRow,
    IndustryMembershipHistoryRow,
    PolicyDocumentRow,
    ThemeMembershipHistoryRow,
)


TEMPORAL_TYPES = {
    "corporate_actions": CorporateActionRow,
    "adjustment_factors": AdjustmentFactorRow,
    "industry_membership_history": IndustryMembershipHistoryRow,
    "theme_membership_history": ThemeMembershipHistoryRow,
}


def _required(row: dict[str, str], field: str, dataset: str) -> str:
    value = row.get(field, "").strip()
    if not value:
        raise ValueError(f"{dataset}.{field} is required")
    return value


def parse_temporal_rows(dataset: str, rows: list[dict[str, str]]) -> list[object]:
    if dataset in TEMPORAL_TYPES:
        row_type = TEMPORAL_TYPES[dataset]
        return [
            row_type(
                id=_required(row, "record_id", dataset),
                security_id=_required(row, "security_id", dataset),
                available_at=datetime.fromisoformat(_required(row, "available_at", dataset)),
                source_artifact_hash=_required(row, "source_artifact_hash", dataset),
                payload_json=json.dumps(row, ensure_ascii=False, sort_keys=True),
            )
            for row in rows
        ]
    if dataset == "financial_disclosures":
        return [
            FinancialDisclosureRow(
                id=_required(row, "disclosure_id", dataset),
                security_id=_required(row, "security_id", dataset),
                report_period=date.fromisoformat(_required(row, "report_period", dataset)),
                revision=int(_required(row, "revision", dataset)),
                published_at=datetime.fromisoformat(_required(row, "published_at", dataset)),
                available_at=datetime.fromisoformat(_required(row, "available_at", dataset)),
                source_artifact_hash=_required(row, "source_artifact_hash", dataset),
            )
            for row in rows
        ]
    if dataset == "financial_facts":
        return [
            FinancialFactRow(
                id=_required(row, "record_id", dataset),
                disclosure_id=_required(row, "disclosure_id", dataset),
                metric=_required(row, "metric", dataset),
                value=_required(row, "value", dataset),
                unit=_required(row, "unit", dataset),
                available_at=datetime.fromisoformat(_required(row, "available_at", dataset)),
                source_artifact_hash=_required(row, "source_artifact_hash", dataset),
            )
            for row in rows
        ]
    if dataset == "policy_documents":
        return [
            PolicyDocumentRow(
                id=_required(row, "document_id", dataset),
                published_at=datetime.fromisoformat(_required(row, "published_at", dataset)),
                first_observed_at=datetime.fromisoformat(_required(row, "first_observed_at", dataset)),
                available_at=datetime.fromisoformat(_required(row, "available_at", dataset)),
                evidence_grade=_required(row, "evidence_grade", dataset),
                official_parent_id=row.get("official_parent_id") or None,
                content_hash=_required(row, "content_hash", dataset),
                source_artifact_hash=_required(row, "source_artifact_hash", dataset),
            )
            for row in rows
        ]
    if dataset == "fee_schedules":
        return [
            FeeScheduleRow(
                id=_required(row, "record_id", dataset),
                effective_from=date.fromisoformat(_required(row, "effective_from", dataset)),
                effective_to=(
                    date.fromisoformat(row["effective_to"])
                    if row.get("effective_to")
                    else None
                ),
                exchange=_required(row, "exchange", dataset),
                asset_type=_required(row, "asset_type", dataset),
                commission_rate=Decimal(row["commission_rate"]),
                minimum_commission=Decimal(row["minimum_commission"]),
                stamp_tax_sell_rate=Decimal(row["stamp_tax_sell_rate"]),
                transfer_rate=Decimal(row["transfer_rate"]),
                available_at=datetime.fromisoformat(_required(row, "available_at", dataset)),
                source_artifact_hash=_required(row, "source_artifact_hash", dataset),
            )
            for row in rows
        ]
    raise ValueError(f"unsupported strict dataset: {dataset}")
```

- [ ] **Step 4: 协调 Agent 创建完整迁移并运行回滚**

`20260716_0003_strict_pit.py` 固定 `revision = "20260716_0003"`、
`down_revision = "20260716_0002"`，按 Task 2 ORM 精确创建 14 张表、索引和
`uq_raw_bar_version`。`downgrade()` 以反向顺序删除；迁移不得更新 01 的历史行。

Run:

```bash
alembic -c backend/alembic.ini upgrade head
alembic -c backend/alembic.ini downgrade 20260716_0002
alembic -c backend/alembic.ini upgrade head
```

Expected: 两次 upgrade 成功，downgrade 仅移除 strict PIT 表。

- [ ] **Step 5: 运行集成测试并提交**

Run: `python -m pytest backend/tests/integration/test_strict_ingest.py -q`

Expected: `2 passed`。

```bash
git add backend/app/infrastructure/market/strict_ingest.py backend/app/infrastructure/market/strict_row_mapping.py backend/app/infrastructure/persistence/strict_pit_rows.py backend/migrations/versions/20260716_0003_strict_pit.py backend/tests/integration/test_strict_ingest.py
git commit -m "feat: append strict PIT versions without overwriting historical truth"
```

### Task 3: 查询历史股票池、状态和行业而不使用当前视图

**Files:**
- Create: `backend/app/infrastructure/market/strict_queries.py`
- Create: `backend/app/features/backtests/strict_execution.py`
- Create: `backend/tests/integration/test_temporal_security_queries.py`
- Create: `backend/tests/integration/test_historical_fee_schedule.py`
- Create: `backend/tests/features/backtests/test_strict_execution.py`
- Modify: `backend/app/features/backtests/execution.py`

- [ ] **Step 1: 写退市幸存者、未来 ST 和当前行业毒丸测试**

```python
# backend/tests/integration/test_temporal_security_queries.py
from datetime import datetime
from decimal import Decimal

from backend.app.infrastructure.market.strict_queries import TemporalSecurityQueries


def test_delisted_later_security_remains_in_past_universe(strict_pit_session) -> None:
    query = TemporalSecurityQueries(strict_pit_session)

    universe = query.universe(datetime.fromisoformat("2020-06-01T15:30:00+08:00"))

    assert "PAST_DELISTED.SZ" in universe
    assert "NOT_LISTED_YET.SZ" not in universe


def test_future_st_and_industry_change_do_not_leak(strict_pit_session) -> None:
    query = TemporalSecurityQueries(strict_pit_session)
    as_of = datetime.fromisoformat("2020-06-01T15:30:00+08:00")

    status = query.status("PAST_DELISTED.SZ", as_of)
    industry = query.industry("PAST_DELISTED.SZ", as_of)

    assert status.is_st is False
    assert status.price_limit_pct == Decimal("0.10")
    assert industry == "OLD_INDUSTRY"
```

```python
# backend/tests/integration/test_historical_fee_schedule.py
from datetime import date, datetime
from decimal import Decimal

import pytest

from backend.app.infrastructure.market.strict_queries import (
    StrictDataMissingError,
    TemporalExecutionQueries,
)


def test_fee_and_board_rule_use_trade_date_version(strict_pit_session) -> None:
    queries = TemporalExecutionQueries(strict_pit_session)

    fee = queries.fee_schedule(
        trade_date=date(2020, 6, 1),
        exchange="SSE",
        asset_type="stock",
        as_of_time=datetime.fromisoformat("2020-06-01T09:00:00+08:00"),
    )

    assert fee.stamp_tax_sell_rate == Decimal("0.001")
    assert fee.minimum_commission == Decimal("5")


def test_missing_historical_fee_fails_instead_of_using_current(strict_pit_session) -> None:
    queries = TemporalExecutionQueries(strict_pit_session)

    with pytest.raises(StrictDataMissingError, match="fee schedule missing"):
        queries.fee_schedule(
            trade_date=date(2000, 1, 1),
            exchange="SSE",
            asset_type="stock",
            as_of_time=datetime.fromisoformat("2000-01-01T09:00:00+08:00"),
        )
```

```python
# backend/tests/features/backtests/test_strict_execution.py
from datetime import date, datetime

import pytest

from backend.app.features.backtests.strict_execution import StrictExecutionSimulator
from backend.app.infrastructure.market.strict_queries import StrictDataMissingError


def test_strict_attempt_injects_dated_fee_and_board_rule(
    recording_execution_simulator,
    temporal_security_queries,
    temporal_execution_queries,
) -> None:
    simulator = StrictExecutionSimulator(
        recording_execution_simulator,
        temporal_security_queries,
        temporal_execution_queries,
    )

    result = simulator.attempt(
        object(),
        security_id="PAST_DELISTED.SZ",
        trade_date=date(2020, 6, 1),
        exchange="SSE",
        asset_type="stock",
        as_of_time=datetime.fromisoformat("2020-06-01T09:00:00+08:00"),
    )

    assert recording_execution_simulator.price_limit_pct == "0.10"
    assert recording_execution_simulator.fee_schedule.version.startswith("pit:fee-2020:")
    assert result.fee_schedule_id == "fee-2020"
    assert len(result.fee_schedule_hash) == 64


def test_strict_attempt_never_falls_back_to_research_defaults(
    recording_execution_simulator,
    temporal_security_queries,
    missing_temporal_execution_queries,
) -> None:
    simulator = StrictExecutionSimulator(
        recording_execution_simulator,
        temporal_security_queries,
        missing_temporal_execution_queries,
    )

    with pytest.raises(StrictDataMissingError, match="fee schedule missing"):
        simulator.attempt(
            object(),
            security_id="PAST_DELISTED.SZ",
            trade_date=date(2020, 6, 1),
            exchange="SSE",
            asset_type="stock",
            as_of_time=datetime.fromisoformat("2020-06-01T09:00:00+08:00"),
        )

    assert recording_execution_simulator.calls == 0
```

- [ ] **Step 2: 运行测试，确认时点查询缺失**

Run:

```bash
python -m pytest backend/tests/integration/test_temporal_security_queries.py \
    backend/tests/integration/test_historical_fee_schedule.py \
    backend/tests/features/backtests/test_strict_execution.py -q
```

Expected: FAIL，错误包含 `No module named 'backend.app.infrastructure.market.strict_queries'`。

- [ ] **Step 3: 实现 `available_at`、上市区间和有效区间三重条件**

```python
# backend/app/infrastructure/market/strict_queries.py
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.infrastructure.persistence.strict_pit_rows import (
    FeeScheduleRow,
    IndustryMembershipHistoryRow,
    SecurityMasterHistoryRow,
    SecurityStatusDailyRow,
)


@dataclass(frozen=True)
class SecurityStatus:
    is_st: bool
    is_suspended: bool
    board: str
    price_limit_pct: Decimal


class StrictDataMissingError(RuntimeError):
    pass


class TemporalSecurityQueries:
    def __init__(self, session: Session) -> None:
        self._session = session

    def universe(self, as_of_time: datetime) -> tuple[str, ...]:
        rows = self._session.scalars(
            select(SecurityMasterHistoryRow).where(
                SecurityMasterHistoryRow.available_at <= as_of_time,
                SecurityMasterHistoryRow.valid_from <= as_of_time.date(),
                or_(SecurityMasterHistoryRow.valid_to.is_(None), SecurityMasterHistoryRow.valid_to > as_of_time.date()),
                SecurityMasterHistoryRow.listed_on <= as_of_time.date(),
                or_(SecurityMasterHistoryRow.delisted_on.is_(None), SecurityMasterHistoryRow.delisted_on > as_of_time.date()),
            )
        ).all()
        latest = self._latest_by_security(rows)
        return tuple(sorted(latest))

    def status(self, security_id: str, as_of_time: datetime) -> SecurityStatus:
        row = self._session.scalar(
            select(SecurityStatusDailyRow)
            .where(
                SecurityStatusDailyRow.security_id == security_id,
                SecurityStatusDailyRow.trade_date == as_of_time.date(),
                SecurityStatusDailyRow.available_at <= as_of_time,
            )
            .order_by(SecurityStatusDailyRow.available_at.desc())
            .limit(1)
        )
        if row is None:
            raise StrictDataMissingError(f"security status missing: {security_id}")
        return SecurityStatus(row.is_st, row.is_suspended, row.board, row.price_limit_pct)

    def industry(self, security_id: str, as_of_time: datetime) -> str:
        rows = self._session.scalars(
            select(IndustryMembershipHistoryRow).where(
                IndustryMembershipHistoryRow.security_id == security_id,
                IndustryMembershipHistoryRow.available_at <= as_of_time,
            )
        ).all()
        eligible = [
            json.loads(row.payload_json)
            for row in rows
            if json.loads(row.payload_json)["effective_from"] <= as_of_time.date().isoformat()
            and (not json.loads(row.payload_json)["effective_to"] or json.loads(row.payload_json)["effective_to"] > as_of_time.date().isoformat())
        ]
        if not eligible:
            raise StrictDataMissingError(f"industry missing: {security_id}")
        return str(eligible[-1]["industry_id"])

    @staticmethod
    def _latest_by_security(rows: list[SecurityMasterHistoryRow]) -> dict[str, SecurityMasterHistoryRow]:
        result: dict[str, SecurityMasterHistoryRow] = {}
        for row in sorted(rows, key=lambda item: item.available_at):
            result[row.security_id] = row
        return result


@dataclass(frozen=True)
class FeeSchedule:
    record_id: str
    source_artifact_hash: str
    commission_rate: Decimal
    minimum_commission: Decimal
    stamp_tax_sell_rate: Decimal
    transfer_rate: Decimal


class TemporalExecutionQueries:
    def __init__(self, session: Session) -> None:
        self._session = session

    def fee_schedule(
        self,
        *,
        trade_date: date,
        exchange: str,
        asset_type: str,
        as_of_time: datetime,
    ) -> FeeSchedule:
        row = self._session.scalar(
            select(FeeScheduleRow)
            .where(
                FeeScheduleRow.exchange == exchange,
                FeeScheduleRow.asset_type == asset_type,
                FeeScheduleRow.effective_from <= trade_date,
                or_(FeeScheduleRow.effective_to.is_(None), FeeScheduleRow.effective_to > trade_date),
                FeeScheduleRow.available_at <= as_of_time,
            )
            .order_by(FeeScheduleRow.effective_from.desc(), FeeScheduleRow.available_at.desc())
            .limit(1)
        )
        if row is None:
            raise StrictDataMissingError("fee schedule missing")
        return FeeSchedule(
            row.record_id,
            row.source_artifact_hash,
            row.commission_rate,
            row.minimum_commission,
            row.stamp_tax_sell_rate,
            row.transfer_rate,
        )
```

- [ ] **Step 4: 复用 04 成交公式并注入历史费率和历史板块规则**

`execution.py` 只扩展 04 已有的 `FilledAttempt`/`RejectedAttempt` 审计字段，不改变成交判断和
费用公式：

```python
# backend/app/features/backtests/execution.py（两个 attempt dataclass 均增加）
fee_schedule_id: str | None = None
fee_schedule_hash: str | None = None
```

严格装饰器调用同一个 `ExecutionSimulator.attempt()`。它只解析 PIT 规则、构造 04 的
`FeeSchedule` 并把审计字段写回结果：

```python
# backend/app/features/backtests/strict_execution.py
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from typing import Protocol

from backend.app.features.backtests.execution import (
    FilledAttempt,
    RejectedAttempt,
)
from backend.app.features.backtests.fees import FeeSchedule
from backend.app.infrastructure.market.strict_queries import (
    TemporalExecutionQueries,
    TemporalSecurityQueries,
)


class AttemptSimulator(Protocol):
    def attempt(
        self,
        *args: object,
        fee_schedule: FeeSchedule,
        price_limit_pct: object,
        **kwargs: object,
    ) -> FilledAttempt | RejectedAttempt: ...


class StrictExecutionSimulator:
    def __init__(
        self,
        simulator: AttemptSimulator,
        securities: TemporalSecurityQueries,
        executions: TemporalExecutionQueries,
    ) -> None:
        self._simulator = simulator
        self._securities = securities
        self._executions = executions

    def attempt(
        self,
        *args: object,
        security_id: str,
        trade_date: date,
        exchange: str,
        asset_type: str,
        as_of_time: datetime,
        **kwargs: object,
    ) -> FilledAttempt | RejectedAttempt:
        status = self._securities.status(security_id, as_of_time)
        dated = self._executions.fee_schedule(
            trade_date=trade_date,
            exchange=exchange,
            asset_type=asset_type,
            as_of_time=as_of_time,
        )
        fee_schedule = FeeSchedule(
            version=f"pit:{dated.record_id}:{dated.source_artifact_hash}",
            commission_rate=dated.commission_rate,
            minimum_commission=dated.minimum_commission,
            stamp_tax_sell_rate=dated.stamp_tax_sell_rate,
            transfer_rate=dated.transfer_rate,
        )
        result = self._simulator.attempt(
            *args,
            fee_schedule=fee_schedule,
            price_limit_pct=status.price_limit_pct,
            **kwargs,
        )
        return replace(
            result,
            fee_schedule_id=dated.record_id,
            fee_schedule_hash=dated.source_artifact_hash,
        )
```

严格组合根把 `StrictExecutionSimulator` 注入 04 的同一 `BacktestEngine`。任何
`security status missing`、`fee schedule missing` 或 PIT hash 缺失都会在调用基础 simulator 前
抛错；严格路径禁止引用 `RESEARCH_FEE_SCHEDULE`，也禁止把未知板块替换成当前 10% 规则。

- [ ] **Step 5: 运行测试并提交**

Run:

```bash
python -m pytest backend/tests/integration/test_temporal_security_queries.py \
    backend/tests/integration/test_historical_fee_schedule.py \
    backend/tests/features/backtests/test_strict_execution.py -q
```

Expected: `4 passed`；不同历史板块涨跌幅和费率版本均按交易日选择，缺失时失败关闭。

```bash
git add backend/app/infrastructure/market/strict_queries.py \
    backend/app/features/backtests/execution.py \
    backend/app/features/backtests/strict_execution.py \
    backend/tests/integration/test_temporal_security_queries.py \
    backend/tests/integration/test_historical_fee_schedule.py \
    backend/tests/features/backtests/test_strict_execution.py
git commit -m "feat: reconstruct historical universe status and industry as observed"
```

### Task 4: 选择当时已公开的财报修订和政策证据

**Files:**
- Modify: `backend/app/infrastructure/market/strict_queries.py`
- Create: `backend/tests/integration/test_temporal_disclosures.py`

- [ ] **Step 1: 写未来财报修订、政策首次抓取和证据等级测试**

```python
# backend/tests/integration/test_temporal_disclosures.py
from datetime import datetime

from backend.app.infrastructure.market.strict_queries import TemporalDisclosureQueries


AS_OF = datetime.fromisoformat("2020-06-01T15:30:00+08:00")


def test_future_financial_revision_does_not_replace_original(strict_pit_session) -> None:
    queries = TemporalDisclosureQueries(strict_pit_session)

    disclosure = queries.latest_financial("000001.SZ", AS_OF)

    assert disclosure.revision == 1
    assert disclosure.facts["revenue"] == "100"


def test_policy_available_at_is_later_of_publish_and_first_observed(strict_pit_session) -> None:
    queries = TemporalDisclosureQueries(strict_pit_session)

    documents = queries.policies(AS_OF)

    assert "FUTURE_FIRST_OBSERVED" not in {document.document_id for document in documents}
    assert "OFFICIAL_A" in {document.document_id for document in documents}


def test_untraceable_b_and_c_evidence_are_not_scoreable(strict_pit_session) -> None:
    queries = TemporalDisclosureQueries(strict_pit_session)

    documents = queries.policies(AS_OF)

    assert {document.document_id for document in documents if document.scoreable} == {"OFFICIAL_A", "TRACEABLE_B"}
```

- [ ] **Step 2: 实现修订版本选择、事实 join 和政策证据门禁**

```python
# append to backend/app/infrastructure/market/strict_queries.py
@dataclass(frozen=True)
class FinancialDisclosure:
    disclosure_id: str
    revision: int
    published_at: datetime
    available_at: datetime
    facts: dict[str, str]


@dataclass(frozen=True)
class PolicyDocument:
    document_id: str
    available_at: datetime
    evidence_grade: str
    scoreable: bool


class TemporalDisclosureQueries:
    def __init__(self, session: Session) -> None:
        self._session = session

    def latest_financial(self, security_id: str, as_of_time: datetime) -> FinancialDisclosure:
        rows = self._session.scalars(
            select(FinancialDisclosureRow).where(
                FinancialDisclosureRow.security_id == security_id,
                FinancialDisclosureRow.available_at <= as_of_time,
            )
        ).all()
        if not rows:
            raise StrictDataMissingError(f"financial disclosure missing: {security_id}")
        row = max(rows, key=lambda item: (item.report_period, item.revision, item.available_at))
        fact_rows = self._session.scalars(
            select(FinancialFactRow).where(
                FinancialFactRow.available_at <= as_of_time,
                FinancialFactRow.disclosure_id == row.id,
            )
        ).all()
        facts = {item.metric: item.value for item in fact_rows}
        return FinancialDisclosure(row.id, row.revision, row.published_at, row.available_at, facts)

    def policies(self, as_of_time: datetime) -> tuple[PolicyDocument, ...]:
        rows = self._session.scalars(
            select(PolicyDocumentRow).where(PolicyDocumentRow.available_at <= as_of_time)
        ).all()
        available_ids = {row.id for row in rows}
        result = []
        for row in rows:
            expected_available = max(row.published_at, row.first_observed_at)
            if row.available_at != expected_available:
                raise ValueError(f"policy available_at mismatch: {row.id}")
            scoreable = row.evidence_grade == "A" or (
                row.evidence_grade == "B" and row.official_parent_id in available_ids
            )
            result.append(PolicyDocument(row.id, row.available_at, row.evidence_grade, scoreable))
        return tuple(sorted(result, key=lambda item: item.document_id))
```

同时在文件顶部从 `strict_pit_rows` 导入 `FinancialDisclosureRow`、`FinancialFactRow`、
`PolicyDocumentRow`；事实只按非空外键 `FinancialFactRow.disclosure_id == row.id` 等值关联。

- [ ] **Step 3: 运行测试并提交**

Run: `python -m pytest backend/tests/integration/test_temporal_disclosures.py -q`

Expected: `3 passed`。

```bash
git add backend/app/infrastructure/market/strict_queries.py backend/app/infrastructure/persistence/strict_pit_rows.py backend/tests/integration/test_temporal_disclosures.py
git commit -m "feat: gate financial revisions and policy evidence by publication time"
```

### Task 5: 分离未复权成交价与当时已知的指标调整序列

**Files:**
- Create: `backend/app/infrastructure/market/adjustment_series.py`
- Create: `backend/tests/infrastructure/market/test_adjustment_series.py`

- [ ] **Step 1: 写未来公司行动不改变过去指标、成交始终使用 raw 的测试**

```python
# backend/tests/infrastructure/market/test_adjustment_series.py
from datetime import date, datetime
from decimal import Decimal

from backend.app.infrastructure.market.adjustment_series import AdjustmentSeriesBuilder, RawBar


def test_future_factor_does_not_change_historical_adjusted_series() -> None:
    as_of = datetime.fromisoformat("2020-06-01T15:30:00+08:00")
    bars = (RawBar(date(2020, 5, 29), Decimal("10"), Decimal("11"), Decimal("9"), Decimal("10")),)
    known = ((date(2020, 5, 29), Decimal("1"), as_of),)
    poisoned = known + ((date(2020, 6, 2), Decimal("2"), datetime.fromisoformat("2020-06-02T08:00:00+08:00")),)

    assert AdjustmentSeriesBuilder().build(bars, known, as_of) == AdjustmentSeriesBuilder().build(bars, poisoned, as_of)


def test_execution_price_is_raw_open_not_adjusted_open() -> None:
    bar = RawBar(date(2020, 5, 29), Decimal("10"), Decimal("11"), Decimal("9"), Decimal("10"))
    adjusted = AdjustmentSeriesBuilder().build((bar,), ((bar.trade_date, Decimal("0.5"), datetime.fromisoformat("2020-05-29T15:30:00+08:00")),), datetime.fromisoformat("2020-05-29T15:30:00+08:00"))[0]

    assert bar.execution_open == Decimal("10")
    assert adjusted.indicator_close == Decimal("5.0")
```

- [ ] **Step 2: 实现只接受 `available_at <= as_of_time` 的派生序列**

```python
# backend/app/infrastructure/market/adjustment_series.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class RawBar:
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal

    @property
    def execution_open(self) -> Decimal:
        return self.open


@dataclass(frozen=True)
class IndicatorBar:
    trade_date: date
    indicator_open: Decimal
    indicator_high: Decimal
    indicator_low: Decimal
    indicator_close: Decimal
    factor: Decimal


class AdjustmentSeriesBuilder:
    def build(
        self,
        bars: tuple[RawBar, ...],
        factors: tuple[tuple[date, Decimal, datetime], ...],
        as_of_time: datetime,
    ) -> tuple[IndicatorBar, ...]:
        known = {trade_date: factor for trade_date, factor, available_at in factors if available_at <= as_of_time}
        result = []
        for bar in bars:
            factor = known.get(bar.trade_date)
            if factor is None:
                raise ValueError(f"adjustment factor missing: {bar.trade_date.isoformat()}")
            result.append(
                IndicatorBar(
                    bar.trade_date,
                    bar.open * factor,
                    bar.high * factor,
                    bar.low * factor,
                    bar.close * factor,
                    factor,
                )
            )
        return tuple(result)
```

- [ ] **Step 3: 运行测试并提交**

Run: `python -m pytest backend/tests/infrastructure/market/test_adjustment_series.py -q`

Expected: `2 passed`。

```bash
git add backend/app/infrastructure/market/adjustment_series.py backend/tests/infrastructure/market/test_adjustment_series.py
git commit -m "feat: isolate raw execution prices from as-of adjustment factors"
```

### Task 6: 用严格覆盖证书保护 PointInTimeWarehouse

**Files:**
- Create: `backend/app/features/backtests/pit_certificate.py`
- Create: `backend/app/infrastructure/market/strict_reader.py`
- Create: `backend/app/infrastructure/market/strict_warehouse.py`
- Modify: `backend/app/infrastructure/market/build.py`
- Create: `backend/tests/infrastructure/market/test_strict_warehouse.py`

- [ ] **Step 1: 写无证书失败、区间外失败和有证书才返回 PIT 等级测试**

```python
# backend/tests/infrastructure/market/test_strict_warehouse.py
from datetime import date, datetime

import pytest

from backend.app.contracts.grades import DataGrade
from backend.app.core.market.pit_models import SnapshotScope
from backend.app.features.backtests.pit_certificate import PitAuditAuthorizer
from backend.app.infrastructure.market.strict_warehouse import StrictPointInTimeWarehouse, UnverifiedPitDataError


AS_OF = datetime.fromisoformat("2020-06-01T15:30:00+08:00")


def test_strict_warehouse_fails_closed_without_matching_certificate(strict_record_reader) -> None:
    warehouse = StrictPointInTimeWarehouse(strict_record_reader, certificate=None)

    with pytest.raises(UnverifiedPitDataError, match="certificate required"):
        warehouse.snapshot(as_of_time=AS_OF, scope=SnapshotScope())


def test_verified_grade_is_returned_only_inside_certificate_coverage(strict_record_reader) -> None:
    report = type(
        "PassedReport",
        (),
        {
            "passed": True,
            "report_id": "audit-1",
            "coverage_start": date(2020, 1, 1),
            "coverage_end": date(2020, 12, 31),
            "bundle_set_hash": "a" * 64,
            "audit_hash": "b" * 64,
        },
    )()
    certificate = PitAuditAuthorizer().issue(report)
    warehouse = StrictPointInTimeWarehouse(strict_record_reader, certificate)

    assert warehouse.snapshot(as_of_time=AS_OF, scope=SnapshotScope()).data_grade is DataGrade.PIT_VERIFIED
    with pytest.raises(UnverifiedPitDataError, match="outside certificate coverage"):
        warehouse.snapshot(
            as_of_time=datetime.fromisoformat("2021-01-02T15:30:00+08:00"),
            scope=SnapshotScope(),
        )
```

- [ ] **Step 2: 创建证书值对象；构造函数不负责签发**

```python
# backend/app/features/backtests/pit_certificate.py
from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class PitCertificate:
    audit_report_id: str
    coverage_start: date
    coverage_end: date
    bundle_set_hash: str
    audit_hash: str


class PassedAuditReport(Protocol):
    passed: bool
    report_id: str
    coverage_start: date
    coverage_end: date
    bundle_set_hash: str
    audit_hash: str


class PitAuditAuthorizer:
    def issue(self, report: PassedAuditReport) -> PitCertificate:
        if not report.passed:
            raise ValueError("failed audit cannot issue certificate")
        return PitCertificate(
            report.report_id,
            report.coverage_start,
            report.coverage_end,
            report.bundle_set_hash,
            report.audit_hash,
        )
```

- [ ] **Step 3: 实现严格仓库，查询后再次检查每条 `available_at`**

```python
# backend/app/infrastructure/market/strict_reader.py
from __future__ import annotations

import json
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.market.pit_models import (
    DataKind,
    LineageRef,
    QualityIssue,
    QualitySeverity,
    SnapshotScope,
    TemporalRecord,
)
from backend.app.infrastructure.persistence.strict_pit_rows import (
    AdjustmentFactorRow,
    CorporateActionRow,
    DailyBarRawRow,
    FeeScheduleRow,
    FinancialDisclosureRow,
    FinancialFactRow,
    IndexDailyBarRow,
    IndustryMembershipHistoryRow,
    PolicyDocumentRow,
    SecurityMasterHistoryRow,
    SecurityStatusDailyRow,
    ThemeMembershipHistoryRow,
    TradingCalendarRow,
)


ROW_MODELS = {
    DataKind.SECURITY_MASTER: SecurityMasterHistoryRow,
    DataKind.SECURITY_STATUS: SecurityStatusDailyRow,
    DataKind.TRADING_CALENDAR: TradingCalendarRow,
    DataKind.DAILY_BAR_RAW: DailyBarRawRow,
    DataKind.INDEX_DAILY_BAR: IndexDailyBarRow,
    DataKind.CORPORATE_ACTION: CorporateActionRow,
    DataKind.ADJUSTMENT_FACTOR: AdjustmentFactorRow,
    DataKind.INDUSTRY_MEMBERSHIP: IndustryMembershipHistoryRow,
    DataKind.THEME_MEMBERSHIP: ThemeMembershipHistoryRow,
    DataKind.FINANCIAL_DISCLOSURE: FinancialDisclosureRow,
    DataKind.FINANCIAL_FACT: FinancialFactRow,
    DataKind.POLICY_DOCUMENT: PolicyDocumentRow,
    DataKind.FEE_SCHEDULE: FeeScheduleRow,
}


class SqlStrictRecordReader:
    def __init__(self, session: Session) -> None:
        self._session = session

    def read(
        self,
        *,
        as_of_time: datetime,
        scope: SnapshotScope,
    ) -> tuple[
        tuple[TemporalRecord, ...],
        tuple[LineageRef, ...],
        tuple[QualityIssue, ...],
    ]:
        kinds = scope.required_kinds or tuple(ROW_MODELS)
        records: list[TemporalRecord] = []
        issues: list[QualityIssue] = []
        for kind in kinds:
            model = ROW_MODELS.get(kind)
            if model is None:
                issues.append(
                    QualityIssue(
                        "STRICT_DATASET_UNSUPPORTED",
                        QualitySeverity.ERROR,
                        kind.value,
                        None,
                        f"strict reader has no model for {kind.value}",
                    )
                )
                continue
            statement = select(model).where(model.available_at <= as_of_time)
            if scope.security_ids and hasattr(model, "security_id"):
                statement = statement.where(model.security_id.in_(scope.security_ids))
            rows = self._session.scalars(statement).all()
            selected = self._select_effective(kind, rows, as_of_time)
            if not selected:
                issues.append(
                    QualityIssue(
                        "REQUIRED_DATASET_MISSING",
                        QualitySeverity.ERROR,
                        kind.value,
                        None,
                        f"no eligible rows for {kind.value}",
                    )
                )
            records.extend(self._to_record(kind, row) for row in selected)
        hashes = sorted({record.source_artifact_hash for record in records})
        lineage = tuple(
            LineageRef(f"strict-{digest[:16]}", "strict_pit_bundle", digest)
            for digest in hashes
        )
        return tuple(records), lineage, tuple(issues)

    @staticmethod
    def _select_effective(
        kind: DataKind,
        rows: list[Any],
        as_of_time: datetime,
    ) -> list[Any]:
        eligible = []
        for row in rows:
            payload = json.loads(row.payload_json) if hasattr(row, "payload_json") else {}
            if kind in {DataKind.INDUSTRY_MEMBERSHIP, DataKind.THEME_MEMBERSHIP}:
                start = date.fromisoformat(payload["effective_from"])
                end = date.fromisoformat(payload["effective_to"]) if payload["effective_to"] else None
                if start > as_of_time.date() or (end is not None and end <= as_of_time.date()):
                    continue
            if kind is DataKind.SECURITY_MASTER:
                if row.valid_from > as_of_time.date():
                    continue
            if kind is DataKind.FEE_SCHEDULE:
                if row.effective_from > as_of_time.date():
                    continue
                if row.effective_to is not None and row.effective_to <= as_of_time.date():
                    continue
                if row.valid_to is not None and row.valid_to <= as_of_time.date():
                    continue
            eligible.append(row)
        keyed: dict[tuple[object, ...], Any] = {}
        for row in eligible:
            key = SqlStrictRecordReader._version_key(kind, row)
            previous = keyed.get(key)
            if previous is None or previous.available_at < row.available_at:
                keyed[key] = row
        return list(keyed.values())

    @staticmethod
    def _version_key(kind: DataKind, row: Any) -> tuple[object, ...]:
        if kind is DataKind.FINANCIAL_DISCLOSURE:
            return row.security_id, row.report_period
        if hasattr(row, "trade_date"):
            entity = getattr(row, "security_id", getattr(row, "index_id", "MARKET"))
            return entity, row.trade_date
        if kind in {DataKind.INDUSTRY_MEMBERSHIP, DataKind.THEME_MEMBERSHIP}:
            return row.security_id, kind.value
        return (row.id,)

    @staticmethod
    def _to_record(kind: DataKind, row: Any) -> TemporalRecord:
        payload = {
            column.name: str(getattr(row, column.name))
            for column in row.__table__.columns
            if column.name not in {"source_artifact_hash", "available_at"}
        }
        entity_id = getattr(
            row,
            "security_id",
            getattr(row, "index_id", f"MARKET:{kind.value}"),
        )
        event_date = getattr(row, "trade_date", None)
        event_time = (
            datetime.combine(event_date, time(15, 0), ZoneInfo("Asia/Shanghai"))
            if event_date
            else getattr(row, "published_at", row.available_at)
        )
        return TemporalRecord(
            str(row.id),
            kind,
            str(entity_id),
            event_time,
            row.available_at,
            row.available_at,
            row.source_artifact_hash,
            payload,
        )
```

```python
# backend/app/infrastructure/market/strict_warehouse.py
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from backend.app.contracts.grades import DataGrade
from backend.app.core.market.pit_models import (
    LineageRef,
    PointInTimeSnapshot,
    QualityIssue,
    SnapshotScope,
    TemporalRecord,
)
from backend.app.core.market.snapshot import assemble_snapshot
from backend.app.features.backtests.pit_certificate import PitCertificate


class StrictRecordReader(Protocol):
    def read(
        self,
        *,
        as_of_time: datetime,
        scope: SnapshotScope,
    ) -> tuple[
        tuple[TemporalRecord, ...],
        tuple[LineageRef, ...],
        tuple[QualityIssue, ...],
    ]: ...


class UnverifiedPitDataError(RuntimeError):
    pass


class StrictPointInTimeWarehouse:
    def __init__(self, reader: StrictRecordReader, certificate: PitCertificate | None) -> None:
        self._reader = reader
        self._certificate = certificate

    def snapshot(
        self,
        *,
        as_of_time: datetime,
        scope: SnapshotScope,
    ) -> PointInTimeSnapshot:
        certificate = self._certificate
        if certificate is None:
            raise UnverifiedPitDataError("certificate required")
        if not certificate.coverage_start <= as_of_time.date() <= certificate.coverage_end:
            raise UnverifiedPitDataError("outside certificate coverage")
        records, lineage, issues = self._reader.read(as_of_time=as_of_time, scope=scope)
        if any(record.available_at > as_of_time for record in records):
            raise UnverifiedPitDataError("reader returned future record")
        return assemble_snapshot(
            as_of_time=as_of_time,
            scope=scope,
            data_grade=DataGrade.PIT_VERIFIED,
            records=records,
            lineage=lineage,
            quality_issues=issues,
        )
```

```python
# append to backend/app/infrastructure/market/build.py
from sqlalchemy.orm import Session

from backend.app.features.backtests.pit_certificate import (
    PassedAuditReport,
    PitAuditAuthorizer,
)
from backend.app.infrastructure.market.strict_reader import SqlStrictRecordReader
from backend.app.infrastructure.market.strict_warehouse import StrictPointInTimeWarehouse


def build_strict_pit_warehouse(
    *,
    session: Session,
    audit_report: PassedAuditReport,
    authorizer: PitAuditAuthorizer,
) -> StrictPointInTimeWarehouse:
    certificate = authorizer.issue(audit_report)
    return StrictPointInTimeWarehouse(SqlStrictRecordReader(session), certificate)
```

- [ ] **Step 4: 运行测试并提交**

Run: `python -m pytest backend/tests/infrastructure/market/test_strict_warehouse.py -q`

Expected: `2 passed`。

```bash
git add backend/app/features/backtests/pit_certificate.py backend/app/infrastructure/market/strict_warehouse.py backend/app/infrastructure/market/build.py backend/tests/infrastructure/market/test_strict_warehouse.py
git commit -m "feat: require audit certificates before exposing PIT verified snapshots"
```

### Task 7: 建立毒丸审计、覆盖检查和证书签发

**Files:**
- Create: `backend/app/features/backtests/pit_audit.py`
- Create: `backend/tests/integration/test_future_poison_audit.py`
- Create: `backend/tests/property/test_available_at_invariant.py`

- [ ] **Step 1: 写九类未来毒丸不改变 manifest 的参数化测试**

```python
# backend/tests/integration/test_future_poison_audit.py
from datetime import datetime

import pytest

from backend.app.core.market.pit_models import DataKind, SnapshotScope
from backend.app.features.backtests.pit_audit import PitAuditRunner


POISON_KINDS = (
    DataKind.SECURITY_MASTER,
    DataKind.SECURITY_STATUS,
    DataKind.DAILY_BAR_RAW,
    DataKind.ADJUSTMENT_FACTOR,
    DataKind.INDUSTRY_MEMBERSHIP,
    DataKind.FINANCIAL_DISCLOSURE,
    DataKind.FINANCIAL_FACT,
    DataKind.POLICY_DOCUMENT,
    DataKind.LLM_FACTOR,
)


@pytest.mark.parametrize("kind", POISON_KINDS)
def test_future_poison_cannot_change_historical_snapshot(auditable_warehouse, poison_injector, kind: DataKind) -> None:
    as_of = datetime.fromisoformat("2020-06-01T15:30:00+08:00")
    scope = SnapshotScope(("000001.SZ",), (kind,))
    baseline = auditable_warehouse.candidate_snapshot(as_of_time=as_of, scope=scope)

    poison_injector.insert(kind=kind, available_at=datetime.fromisoformat("2020-06-02T09:00:00+08:00"), marker="FUTURE_POISON")
    replay = auditable_warehouse.candidate_snapshot(as_of_time=as_of, scope=scope)

    assert replay.manifest_hash == baseline.manifest_hash
    assert "FUTURE_POISON" not in repr(replay)


def test_audit_fails_when_any_required_daily_coverage_is_missing(auditable_warehouse, coverage_calendar) -> None:
    report = PitAuditRunner(auditable_warehouse, coverage_calendar).run(
        coverage_start=coverage_calendar[0],
        coverage_end=coverage_calendar[-1],
    )

    assert report.passed is False
    assert "security_status_daily:2020-05-29" in report.failures
```

- [ ] **Step 2: 写性质测试，任意成功快照都没有未来记录**

```python
# backend/tests/property/test_available_at_invariant.py
from datetime import datetime, timedelta, timezone

from hypothesis import given, strategies as st

from backend.app.core.market.pit_models import DataKind, SnapshotScope, TemporalRecord
from backend.app.core.market.snapshot import FutureDataError, assemble_snapshot
from backend.app.contracts.grades import DataGrade


@given(st.integers(min_value=-86400, max_value=86400))
def test_snapshot_never_accepts_available_at_after_as_of(offset_seconds: int) -> None:
    as_of = datetime(2020, 1, 1, tzinfo=timezone.utc)
    record = TemporalRecord(
        "probe", DataKind.POLICY_DOCUMENT, "MARKET:POLICY", as_of,
        as_of + timedelta(seconds=offset_seconds), as_of + timedelta(seconds=offset_seconds),
        "a" * 64, {"marker": "probe"},
    )
    if offset_seconds > 0:
        try:
            assemble_snapshot(as_of_time=as_of, scope=SnapshotScope(), data_grade=DataGrade.RESEARCH, records=(record,), lineage=(), quality_issues=())
        except FutureDataError:
            return
        raise AssertionError("future record was accepted")
    snapshot = assemble_snapshot(as_of_time=as_of, scope=SnapshotScope(), data_grade=DataGrade.RESEARCH, records=(record,), lineage=(), quality_issues=())
    assert snapshot.market_inputs[0].available_at <= as_of
```

- [ ] **Step 3: 实现审计报告；只有全绿报告可以签发证书**

```python
# backend/app/features/backtests/pit_audit.py
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Protocol
from zoneinfo import ZoneInfo

from backend.app.core.market.pit_models import DataKind, PointInTimeSnapshot, SnapshotScope
DAILY_REQUIRED = (
    DataKind.SECURITY_MASTER,
    DataKind.SECURITY_STATUS,
    DataKind.TRADING_CALENDAR,
    DataKind.DAILY_BAR_RAW,
    DataKind.INDEX_DAILY_BAR,
    DataKind.ADJUSTMENT_FACTOR,
    DataKind.INDUSTRY_MEMBERSHIP,
    DataKind.THEME_MEMBERSHIP,
)


@dataclass(frozen=True)
class PitAuditReport:
    report_id: str
    coverage_start: date
    coverage_end: date
    bundle_set_hash: str
    checked_manifests: tuple[str, ...]
    failures: tuple[str, ...]
    audit_hash: str

    @property
    def passed(self) -> bool:
        return not self.failures


class AuditablePointInTimeWarehouse(Protocol):
    def candidate_snapshot(
        self,
        *,
        as_of_time: datetime,
        scope: SnapshotScope,
    ) -> PointInTimeSnapshot: ...

    def bundle_set_hash(self, coverage_start: date, coverage_end: date) -> str: ...


class PitAuditRunner:
    def __init__(
        self,
        warehouse: AuditablePointInTimeWarehouse,
        trading_dates: tuple[date, ...],
    ) -> None:
        self._warehouse = warehouse
        self._trading_dates = trading_dates

    def run(self, *, coverage_start: date, coverage_end: date) -> PitAuditReport:
        failures: list[str] = []
        manifests: list[str] = []
        for trading_date in self._trading_dates:
            if not coverage_start <= trading_date <= coverage_end:
                continue
            as_of = datetime.combine(trading_date, time(15, 30), ZoneInfo("Asia/Shanghai"))
            for kind in DAILY_REQUIRED:
                try:
                    snapshot = self._warehouse.candidate_snapshot(
                        as_of_time=as_of,
                        scope=SnapshotScope(required_kinds=(kind,)),
                    )
                except Exception as error:
                    failures.append(f"{kind.value}:{trading_date.isoformat()}:{type(error).__name__}")
                    continue
                if snapshot.quality.has_errors:
                    failures.append(f"{kind.value}:{trading_date.isoformat()}")
                manifests.append(snapshot.manifest_hash)
        bundle_set_hash = self._warehouse.bundle_set_hash(coverage_start, coverage_end)
        body = json.dumps(
            {"start": coverage_start.isoformat(), "end": coverage_end.isoformat(), "bundles": bundle_set_hash, "manifests": sorted(manifests), "failures": sorted(failures)},
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(body.encode()).hexdigest()
        return PitAuditReport(digest[:24], coverage_start, coverage_end, bundle_set_hash, tuple(sorted(manifests)), tuple(sorted(failures)), digest)
```

在集成 fixture 中，`candidate_snapshot` 使用与 `StrictPointInTimeWarehouse` 相同的
`SqlStrictRecordReader` 和 `assemble_snapshot`，但固定返回 `research`；它只对审计 runner
开放，不能注入候选、持仓或回测用例。

- [ ] **Step 4: 运行毒丸、性质和 01 的时间门禁回归测试**

Run:

```bash
python -m pytest backend/tests/integration/test_future_poison_audit.py backend/tests/property/test_available_at_invariant.py backend/tests/core/market/test_snapshot.py -q
```

Expected: 全部 PASS；九类毒丸均不改变历史 manifest；缺一个交易日状态即审计失败。

- [ ] **Step 5: 提交**

```bash
git add backend/app/features/backtests/pit_audit.py backend/tests/integration/test_future_poison_audit.py backend/tests/property/test_available_at_invariant.py
git commit -m "feat: prove future poison cannot cross the PIT boundary"
```

### Task 8: 实现滚动前推和最终保留样本锁

**Files:**
- Create: `backend/app/features/backtests/walk_forward.py`
- Create: `backend/tests/features/backtests/test_walk_forward.py`

- [ ] **Step 1: 写 3 年开发、1 年验证、滚动 1 年和 12 月保留样本测试**

```python
# backend/tests/features/backtests/test_walk_forward.py
from datetime import date, datetime, timezone

import pytest

from backend.app.features.backtests.walk_forward import HoldoutLock, HoldoutViolation, WalkForwardPlan


def test_walk_forward_windows_never_touch_final_holdout() -> None:
    plan = WalkForwardPlan.build(date(2015, 1, 1), date(2025, 12, 31), holdout_months=12)

    assert plan.holdout_start == date(2025, 1, 1)
    assert plan.windows[0].development == (date(2015, 1, 1), date(2017, 12, 31))
    assert plan.windows[0].validation == (date(2018, 1, 1), date(2018, 12, 31))
    assert all(window.validation[1] < plan.holdout_start for window in plan.windows)


def test_locked_holdout_rejects_parameter_change() -> None:
    lock = HoldoutLock("v2.12", "a" * 64, date(2025, 1, 1), date(2025, 12, 31), datetime.now(timezone.utc))

    with pytest.raises(HoldoutViolation, match="parameter hash changed"):
        lock.authorize("b" * 64, date(2025, 1, 1), date(2025, 12, 31))
```

- [ ] **Step 2: 运行测试并确认 walk-forward 模块尚未存在**

Run: `python -m pytest backend/tests/features/backtests/test_walk_forward.py -q`

Expected: FAIL，包含
`No module named 'backend.app.features.backtests.walk_forward'`。

- [ ] **Step 3: 实现确定性窗口构造和不可变 lock**

```python
# backend/app/features/backtests/walk_forward.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta


class HoldoutViolation(RuntimeError):
    pass


def _end_of_previous_year(year: int) -> date:
    return date(year - 1, 12, 31)


def _twelve_month_holdout_start(end: date) -> date:
    try:
        prior_year_same_day = end.replace(year=end.year - 1)
    except ValueError:
        prior_year_same_day = end.replace(year=end.year - 1, day=28)
    return prior_year_same_day + timedelta(days=1)


@dataclass(frozen=True)
class WalkForwardWindow:
    development: tuple[date, date]
    validation: tuple[date, date]


@dataclass(frozen=True)
class WalkForwardPlan:
    windows: tuple[WalkForwardWindow, ...]
    holdout_start: date
    holdout_end: date

    @classmethod
    def build(cls, start: date, end: date, *, holdout_months: int) -> "WalkForwardPlan":
        if holdout_months != 12:
            raise ValueError("V2.12 final holdout must be 12 months")
        holdout_start = _twelve_month_holdout_start(end)
        windows = []
        development_start = start
        while True:
            development_end = date(development_start.year + 2, 12, 31)
            validation_start = date(development_start.year + 3, 1, 1)
            validation_end = date(development_start.year + 3, 12, 31)
            if validation_end >= holdout_start:
                break
            windows.append(WalkForwardWindow((development_start, development_end), (validation_start, validation_end)))
            development_start = date(development_start.year + 1, 1, 1)
        return cls(tuple(windows), holdout_start, end)


@dataclass(frozen=True)
class HoldoutLock:
    strategy_version: str
    parameter_hash: str
    holdout_start: date
    holdout_end: date
    created_at: datetime

    def authorize(self, parameter_hash: str, start: date, end: date) -> None:
        if parameter_hash != self.parameter_hash:
            raise HoldoutViolation("parameter hash changed after holdout lock")
        if (start, end) != (self.holdout_start, self.holdout_end):
            raise HoldoutViolation("holdout interval changed after lock")
```

- [ ] **Step 4: 编排 04 的同一 BacktestEngine，不复制交易规则**

在同一文件增加：

```python
from backend.app.features.backtests.engine import BacktestEngine
from backend.app.features.backtests.experiments import llm_grade_for
from backend.app.features.backtests.models import BacktestGroupResult, BacktestRequest, StrategyGroup


class WalkForwardRunner:
    def __init__(self, engine: BacktestEngine) -> None:
        self._engine = engine

    def run(
        self,
        base_request: BacktestRequest,
        plan: WalkForwardPlan,
        group: StrategyGroup,
    ) -> tuple[BacktestGroupResult, ...]:
        results: list[BacktestGroupResult] = []
        for window in plan.windows:
            development = base_request.with_period(*window.development)
            validation = base_request.with_period(*window.validation)
            grade = llm_grade_for(group)
            self._engine.run(development, group, grade)
            results.append(self._engine.run(validation, group, grade))
        return tuple(results)
```

`base_request` 必须是 04 的 `BacktestRequest`，`self._engine` 必须是 04 注入同一
`V212StrategyEngine`、`ExecutionSimulator` 和 `PointInTimeWarehouse` 的 `BacktestEngine`。
A/B/C/D 仅改变启用因子集合，股票池、市场过滤、费用、滑点和风险预算沿用同一 request。

- [ ] **Step 5: 运行测试并提交**

Run: `python -m pytest backend/tests/features/backtests/test_walk_forward.py -q`

Expected: `2 passed`。

```bash
git add backend/app/features/backtests/walk_forward.py backend/tests/features/backtests/test_walk_forward.py
git commit -m "feat: lock final holdout before rolling walk-forward validation"
```

### Task 9: 分离 PIT 晋级、LLM 等级和 V2.12 研究门槛

**Files:**
- Create: `backend/app/features/backtests/pit_promotion.py`
- Create: `backend/tests/features/backtests/test_pit_promotion.py`
- Create: `backend/tests/integration/test_pit_verified_backtest.py`

- [ ] **Step 1: 写好收益无审计不能晋级、坏收益有审计仍可验证数据的测试**

```python
# backend/tests/features/backtests/test_pit_promotion.py
import pytest

from backend.app.contracts.grades import DataGrade, LlmGrade
from backend.app.features.backtests.pit_promotion import (
    PitPromotionError,
    PitPromotionService,
    PromotionCandidate,
)


class FakeAuditAuthorizer:
    def __init__(self, passed: bool) -> None:
        self._passed = passed

    def assert_authorized(self, *, run_id: str, audit_report_id: str) -> None:
        if not self._passed:
            raise PitPromotionError("audit did not pass")


def candidate(*, research_gate_passed: bool) -> PromotionCandidate:
    return PromotionCandidate(
        run_id="run-1",
        current_data_grade=DataGrade.RESEARCH,
        llm_grade=LlmGrade.RECONSTRUCTED,
        audit_report_id="audit-1",
        walk_forward_complete=True,
        holdout_locked=True,
        all_manifests_within_as_of=True,
        research_gate_passed=research_gate_passed,
    )


def test_profitable_run_without_audit_cannot_be_promoted() -> None:
    with pytest.raises(PitPromotionError, match="audit did not pass"):
        PitPromotionService(FakeAuditAuthorizer(False)).promote(
            candidate(research_gate_passed=True)
        )


def test_data_can_be_pit_verified_even_when_strategy_gate_fails() -> None:
    result = PitPromotionService(FakeAuditAuthorizer(True)).promote(
        candidate(research_gate_passed=False)
    )

    assert result.data_grade is DataGrade.PIT_VERIFIED
    assert result.strategy_gate_passed is False
    assert result.llm_grade is LlmGrade.RECONSTRUCTED
```

- [ ] **Step 2: 实现单向、全条件晋级且不修改 LLM/收益状态**

```python
# backend/app/features/backtests/pit_promotion.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from backend.app.contracts.grades import DataGrade, LlmGrade


class PitPromotionError(RuntimeError):
    pass


class PitPromotionAuthorizer(Protocol):
    def assert_authorized(self, *, run_id: str, audit_report_id: str) -> None: ...


@dataclass(frozen=True)
class PromotionCandidate:
    run_id: str
    current_data_grade: DataGrade
    llm_grade: LlmGrade
    audit_report_id: str
    walk_forward_complete: bool
    holdout_locked: bool
    all_manifests_within_as_of: bool
    research_gate_passed: bool


@dataclass(frozen=True)
class PromotionResult:
    run_id: str
    data_grade: DataGrade
    llm_grade: LlmGrade
    strategy_gate_passed: bool
    audit_report_id: str


class PitPromotionService:
    def __init__(self, authorizer: PitPromotionAuthorizer) -> None:
        self._authorizer = authorizer

    def promote(self, candidate: PromotionCandidate) -> PromotionResult:
        if candidate.current_data_grade is not DataGrade.RESEARCH:
            raise PitPromotionError("only research results can be promoted")
        self._authorizer.assert_authorized(
            run_id=candidate.run_id,
            audit_report_id=candidate.audit_report_id,
        )
        if not candidate.walk_forward_complete:
            raise PitPromotionError("walk-forward incomplete")
        if not candidate.holdout_locked:
            raise PitPromotionError("final holdout is not locked")
        if not candidate.all_manifests_within_as_of:
            raise PitPromotionError("manifest contains future input")
        return PromotionResult(
            candidate.run_id,
            DataGrade.PIT_VERIFIED,
            candidate.llm_grade,
            candidate.research_gate_passed,
            candidate.audit_report_id,
        )
```

- [ ] **Step 3: 写完整严格回测集成测试**

```python
# backend/tests/integration/test_pit_verified_backtest.py
from backend.app.contracts.grades import DataGrade, LlmGrade


def test_strict_walk_forward_run_is_replayable_and_audited(strict_backtest_harness) -> None:
    first = strict_backtest_harness.run_all_groups()
    second = strict_backtest_harness.run_all_groups()

    assert first.result_hash == second.result_hash
    assert first.data_grade is DataGrade.PIT_VERIFIED
    assert first.llm_grade is LlmGrade.RECONSTRUCTED
    assert {item.group for item in first.experiments} == {"A", "B", "C", "D"}
    assert all(item.universe_hash == first.experiments[0].universe_hash for item in first.experiments)
    assert first.audit_report_id
    assert first.holdout_lock_id
```

- [ ] **Step 4: 运行 05 全量测试、04 回归和迁移往返**

Run:

```bash
python -m pytest backend/tests/infrastructure/market backend/tests/features/backtests backend/tests/integration/test_strict_ingest.py backend/tests/integration/test_temporal_security_queries.py backend/tests/integration/test_temporal_disclosures.py backend/tests/integration/test_future_poison_audit.py backend/tests/integration/test_pit_verified_backtest.py backend/tests/property/test_available_at_invariant.py -q
python -m mypy backend/app/infrastructure/market backend/app/features/backtests/pit_audit.py backend/app/features/backtests/pit_certificate.py backend/app/features/backtests/walk_forward.py backend/app/features/backtests/pit_promotion.py
alembic -c backend/alembic.ini downgrade 20260716_0002
alembic -c backend/alembic.ini upgrade head
```

Expected: pytest 全部 PASS；mypy 输出 `Success: no issues found`；迁移往返成功；相同输入
manifest、策略版本和参数 hash 的两次严格回测 result hash 完全一致。

- [ ] **Step 5: 提交**

```bash
git add backend/app/features/backtests/pit_promotion.py backend/tests/features/backtests/test_pit_promotion.py backend/tests/integration/test_pit_verified_backtest.py
git commit -m "feat: promote data grade only after PIT audit and walk-forward lock"
```

## 完成定义

- canonical bundle 的每个文件都有 source、license、行数和 SHA-256；入库只追加版本且批次原子。
- 任意严格查询和最终快照均满足 `available_at <= as_of_time`；缺失数据失败关闭。
- 历史股票池包含当时存在但后来退市的证券，不回填未来 ST、停牌、行业或名称。
- 财报按实际公告和修订可用时间选版本；政策使用发布时间和首次抓取时间较晚者。
- 成交只用未复权价；未来公司行动和复权因子不能改变过去指标输入 manifest。
- 九类未来毒丸、T 日信号/T+1、一字板、停牌和 LLM 证据越界测试全部通过；执行类测试复用
  04 的 `ExecutionSimulator`，本计划不另建成交公式。
- walk-forward 固定 3 年开发、1 年验证、滚动 1 年；最新 12 个月在参数运行前锁定。
- 只有审计证书覆盖的区间能返回 `pit_verified`；收益表现不能授予数据等级。
- `research_gate_passed` 独立报告 V2.12 的 200 笔、利润因子、净期望、回撤、稳定性和 D/A
  增量门槛；未通过时仍如实保存，不修改数据等级。
- 历史 LLM 始终保留 `reconstructed`，不因 PIT 审计改成 `forward_observed`。
