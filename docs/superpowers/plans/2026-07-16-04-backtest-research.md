# Research-Grade Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox
> (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible research-grade V2.12 backtest engine, A-D experiments, structured API
results, and Web visualizations without claiming point-in-time verification.

**Architecture:** The backtest feature is a vertical slice behind a generic `BacktestDecisionPort` and
the PIT snapshot port delivered by plan 01. A deterministic event loop owns execution order, lot ledger,
A-share execution constraints, metrics, and manifests. Plan 06 later wires the real candidate and holding
decision services into this port, allowing plans 02-04 to develop concurrently.

**Tech Stack:** Python 3.11, Pydantic v2, SQLAlchemy 2, PostgreSQL, FastAPI, pytest, Hypothesis,
React, TypeScript, TanStack Query, ECharts, Vitest

---

## Dependencies and Ownership

Required completed plans: `00-foundation-contracts` and `01-pit-and-legacy`.

This plan owns only:

```text
backend/app/features/backtests/**
backend/tests/features/backtests/**
web/src/features/backtests/**
```

Do not edit `backend/app/main.py`, Alembic revisions, generated OpenAPI/TypeScript, global Web routes,
global styles, or other feature directories. Export a router and route descriptor for plan 06.

### Task 1: Define backtest contracts and fakes

**Files:**
- Create: `backend/app/features/backtests/__init__.py`
- Create: `backend/app/features/backtests/models.py`
- Create: `backend/app/features/backtests/ports.py`
- Create: `backend/tests/features/backtests/fakes.py`
- Test: `backend/tests/features/backtests/test_models.py`

- [ ] **Step 1: Write failing validation tests**

```python
from datetime import date

import pytest
from pydantic import ValidationError

from backend.app.contracts.grades import LlmGrade
from backend.app.features.backtests.models import BacktestRequest, StrategyGroup


def test_request_does_not_accept_result_grades() -> None:
    request = BacktestRequest(
        strategy_version="v2.12",
        start_date=date(2020, 1, 2),
        end_date=date(2023, 12, 29),
        initial_cash=150_000,
        groups=[StrategyGroup.A, StrategyGroup.B, StrategyGroup.C, StrategyGroup.D],
    )

    assert "data_grade" not in request.model_dump()
    assert "llm_grade" not in request.model_dump()
    assert request.with_period(date(2021, 1, 4), date(2021, 12, 31)).start_date == date(
        2021, 1, 4
    )
    assert request.with_group(StrategyGroup.C).groups == [StrategyGroup.C]
    with pytest.raises(ValidationError):
        BacktestRequest.model_validate(
            {**request.model_dump(), "llm_grade": LlmGrade.RECONSTRUCTED},
        )


def test_request_rejects_inverted_dates() -> None:
    with pytest.raises(ValidationError):
        BacktestRequest(
            strategy_version="v2.12",
            start_date=date(2024, 2, 1),
            end_date=date(2024, 1, 1),
            initial_cash=150_000,
            groups=[StrategyGroup.A],
        )
```

- [ ] **Step 2: Run RED**

Run `python -m pytest backend/tests/features/backtests/test_models.py -q`.

Expected: collection fails because `app.features.backtests.models` does not exist.

- [ ] **Step 3: Implement the immutable request contract**

```python
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.contracts.grades import DataGrade, LlmGrade


class StrategyGroup(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderIntent(BaseModel):
    model_config = ConfigDict(frozen=True)

    order_id: str
    security_id: str
    side: OrderSide
    quantity: int = Field(gt=0)
    signal_date: date
    earliest_trade_date: date
    strategy_book: str
    priority: int = Field(ge=1)
    reason_codes: tuple[str, ...]
    signal_close: Decimal = Field(gt=0)
    stop_price: Decimal | None = Field(default=None, gt=0)
    max_participation_rate: Decimal = Field(default=Decimal("0.002"), gt=0, le=1)


class BacktestRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_version: str
    start_date: date
    end_date: date
    initial_cash: Decimal = Field(gt=0)
    groups: list[StrategyGroup] = Field(min_length=1)
    buy_slippage_bps: int = Field(default=10, ge=0)
    sell_slippage_bps: int = Field(default=10, ge=0)
    fee_schedule_version: str = "research-cn-a-2023-08-28"

    @model_validator(mode="after")
    def validate_dates(self) -> "BacktestRequest":
        if self.start_date > self.end_date:
            raise ValueError("start_date must not exceed end_date")
        return self

    def with_period(self, start_date: date, end_date: date) -> "BacktestRequest":
        return type(self).model_validate(
            {**self.model_dump(), "start_date": start_date, "end_date": end_date}
        )

    def with_group(self, group: StrategyGroup) -> "BacktestRequest":
        return type(self).model_validate({**self.model_dump(), "groups": [group]})


class BacktestGroupSummary(BaseModel):
    group: StrategyGroup
    data_grade: DataGrade
    llm_grade: LlmGrade
    input_manifest_hash: str
    metrics: dict[str, str | int | None]


class BacktestRunSummary(BaseModel):
    run_id: str
    status: str
    strategy_version: str
    input_manifest_hash: str
    groups: tuple[BacktestGroupSummary, ...]
    created_at: datetime


class BacktestGroupResult(BaseModel):
    group: StrategyGroup
    data_grade: DataGrade
    llm_grade: LlmGrade
    input_manifest_hash: str
    equity_curve: list[dict[str, str]]
    trades: list[dict[str, str]]
    metrics: dict[str, str | int | None]
    warnings: list[str]


class BacktestExperimentResult(BaseModel):
    request: BacktestRequest
    input_manifest_hash: str
    groups: tuple[BacktestGroupResult, ...]
    warnings: list[str]
```

Intent priority is ascending: 1 red-light/delisting, 2 hard stop, 3 market or portfolio reduction,
4 strategy-book exit, 5 ranking/replacement, and 100 new buy. Sort ties by `security_id`; execute all
sell attempts before recalculating cash and risk for buys.

Define typed protocols in `ports.py`: `BacktestDecisionPort` accepts an immutable context and returns
order intents; `BacktestRepository` persists structured results. The backtest port is intentionally
different from the shared `StrategyDecisionPort`, which returns factor/risk evaluations rather than
orders. Neither protocol can create fills or mutate the ledger.

```python
from collections.abc import Mapping
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from backend.app.core.market.pit_models import PointInTimeSnapshot
from backend.app.core.portfolio.models import PortfolioSnapshot
from backend.app.features.backtests.models import BacktestExperimentResult, OrderIntent, StrategyGroup
from backend.app.ports.artifacts import ArtifactRepository


@dataclass(frozen=True)
class BacktestDecisionContext:
    as_of_time: datetime
    next_trade_date: date
    strategy_version: str
    group: StrategyGroup
    snapshot: PointInTimeSnapshot
    portfolio: PortfolioSnapshot
    candidate_states: Mapping[str, str]


@dataclass(frozen=True)
class BacktestDecision:
    intents: tuple[OrderIntent, ...]
    candidate_states: Mapping[str, str]


class BacktestDecisionPort(Protocol):
    def decide(self, context: BacktestDecisionContext) -> BacktestDecision: ...


class BacktestTradingDayPort(Protocol):
    def between(self, start_date: date, end_date: date) -> tuple[date, ...]: ...


class BacktestRepository(Protocol):
    def publish_result(
        self,
        run_id: UUID,
        result: BacktestExperimentResult,
        artifacts: ArtifactRepository,
    ) -> None: ...
```

`BacktestDecisionContext` and `BacktestDecision` are defined only in `ports.py`; consumers import them
from `backend.app.features.backtests.ports`, never from `models.py`. The context always carries the shared
`backend.app.core.portfolio.models.PortfolioSnapshot`, not the mutable backtest ledger state.

- [ ] **Step 4: Add fakes and run GREEN**

Add `FixedDecisionPort`, `MemoryBacktestRepository`, and `MemoryArtifactRepository` to `fakes.py`.

```python
@dataclass(frozen=True)
class FixedDecisionPort:
    intents: tuple[OrderIntent, ...]

    def decide(self, context: BacktestDecisionContext) -> BacktestDecision:
        return BacktestDecision(self.intents, context.candidate_states)


@dataclass
class MemoryBacktestRepository:
    summaries: dict[str, BacktestRunSummary] = field(default_factory=dict)

    def save_summary(self, summary: BacktestRunSummary) -> None:
        self.summaries[summary.run_id] = summary
```

Run `python -m pytest backend/tests/features/backtests/test_models.py -q`.

Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/features/backtests backend/tests/features/backtests
git commit -m "feat(backtests): freeze research backtest contracts"
```

### Task 2: Implement the lot-level portfolio ledger

**Files:**
- Create: `backend/app/features/backtests/ledger.py`
- Test: `backend/tests/features/backtests/test_ledger.py`

- [ ] **Step 1: Write failing accounting tests**

```python
def test_buy_fee_enters_weighted_cost() -> None:
    ledger = PortfolioLedger.opening(cash=Decimal("150000"))
    ledger.apply_fill(buy_fill(quantity=1000, price="10.00", fee="5.00"))
    assert ledger.position("600000.SH").average_cost == Decimal("10.005")


def test_partial_sale_preserves_remaining_cost() -> None:
    ledger = ledger_with_position(quantity=1000, average_cost="10.005")
    ledger.apply_fill(sell_fill(quantity=300, price="12.00", fee="8.60"))
    assert ledger.position("600000.SH").quantity == 700
    assert ledger.position("600000.SH").average_cost == Decimal("10.005")


def test_buy_day_quantity_is_not_sellable() -> None:
    ledger = ledger_with_today_buy(quantity=1000)
    assert ledger.position("600000.SH").sellable_quantity == 0
```

- [ ] **Step 2: Run RED**

Run `python -m pytest backend/tests/features/backtests/test_ledger.py -q`.

Expected: import failure for `PortfolioLedger`.

- [ ] **Step 3: Implement event application**

Create typed `Fill`, `PositionLot`, `PositionState`, and `PortfolioState`. Use `Decimal` for all money and
prices. `apply_fill()` rejects negative cash, overselling, duplicate fill ids, and mismatched trade dates.
It preserves `strategy_book`, original `one_r`, and highest close across adds and reductions. Buy fees
enter average cost; sell fees enter realized P/L; partial sales do not change remaining cost.

```python
@dataclass(frozen=True)
class PositionLot:
    lot_id: str
    security_id: str
    acquired_at: datetime
    quantity: int
    remaining_quantity: int
    average_cost: Decimal
    strategy_book: str
    entry_score: Decimal | None
    initial_risk_per_share: Decimal
    effective_stop: Decimal
    highest_close: Decimal
    add_count: int


@dataclass
class PortfolioLedger:
    state: PortfolioState
    applied_fill_ids: set[str]

    def apply_fill(self, fill: Fill) -> None:
        if fill.fill_id in self.applied_fill_ids:
            raise DuplicateFillError(fill.fill_id)
        if fill.side is Side.BUY:
            self._apply_buy(fill)
        else:
            self._apply_sell(fill)
        if self.state.cash < 0:
            raise NegativeCashError()
        self.applied_fill_ids.add(fill.fill_id)
```

Expose a read-only bridge to the shared portfolio contract; integration code must not repeat this map:

```python
from backend.app.core.portfolio.models import (
    PortfolioLot,
    PortfolioSnapshot,
    PositionOrigin,
    StrategyBook,
)


def to_portfolio_snapshot(self, as_of_time: datetime) -> PortfolioSnapshot:
    lots = tuple(
        PortfolioLot(
            lot_id=lot.lot_id,
            security_id=lot.security_id,
            quantity=lot.remaining_quantity,
            available_to_sell=self._sellable_quantity(lot, as_of_time.date()),
            average_cost=lot.average_cost,
            effective_at=lot.acquired_at,
            origin=PositionOrigin.SIMULATED_FILL,
            strategy_book=StrategyBook(lot.strategy_book),
            entry_score=lot.entry_score,
            initial_risk_per_share=lot.initial_risk_per_share,
            effective_stop=lot.effective_stop,
            highest_close=lot.highest_close,
            add_count=lot.add_count,
        )
        for lot in self.state.lots
        if lot.remaining_quantity > 0
    )
    return PortfolioSnapshot(
        portfolio_id=self.state.portfolio_id,
        as_of_time=as_of_time,
        version=self.state.version,
        cash=self.state.cash,
        equity=self.state.equity,
        lots=lots,
    )
```

- [ ] **Step 4: Add property tests and run GREEN**

Generate valid buy/sell sequences with Hypothesis and assert cash, quantity, cost, and sellable quantity
never become negative.

```python
@given(valid_fill_sequences())
def test_valid_sequences_preserve_ledger_invariants(fills: list[Fill]) -> None:
    ledger = PortfolioLedger.opening(cash=Decimal("1000000"))
    for fill in fills:
        ledger.apply_fill(fill)
        assert ledger.state.cash >= 0
        assert all(position.quantity >= 0 for position in ledger.state.positions.values())
        assert all(position.sellable_quantity >= 0 for position in ledger.state.positions.values())
```

Run `python -m pytest backend/tests/features/backtests/test_ledger.py -q`.

Expected: unit and property tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/features/backtests/ledger.py backend/tests/features/backtests/test_ledger.py
git commit -m "feat(backtests): preserve lot-level A-share accounting"
```

### Task 3: Implement A-share execution attempts

**Files:**
- Create: `backend/app/features/backtests/execution.py`
- Create: `backend/app/features/backtests/fees.py`
- Test: `backend/tests/features/backtests/test_execution.py`
- Test: `backend/tests/features/backtests/test_fees.py`

- [ ] **Step 1: Write a failing execution matrix**

Use a typed fixture that returns the positional and keyword arguments for
`ExecutionSimulator.attempt()` without changing its public signature:

```python
# backend/tests/features/backtests/test_execution.py
from collections.abc import Callable

import pytest

from backend.app.features.backtests.execution import (
    ExecutionSimulator,
    FilledAttempt,
    RejectedAttempt,
)


ExecutionCaseFactory = Callable[
    [str],
    tuple[tuple[object, ...], dict[str, object]],
]


@pytest.mark.parametrize(
    ("case_name", "expected_type", "reason_code", "quantity"),
    [
        ("t_plus_one", RejectedAttempt, "T_PLUS_ONE", 0),
        ("suspension", RejectedAttempt, "SUSPENDED", 0),
        ("limit_up_buy", RejectedAttempt, "LIMIT_UP_LOCKED", 0),
        ("limit_down_sell", RejectedAttempt, "LIMIT_DOWN_LOCKED", 0),
        ("buy_gap_over_three_percent", RejectedAttempt, "BUY_GAP_TOO_HIGH", 0),
        ("volume_participation", FilledAttempt, None, 200),
        ("stop_gap", FilledAttempt, None, 1_000),
        ("intraday_stop", FilledAttempt, None, 1_000),
        ("buy_lot_rounding", FilledAttempt, None, 900),
        ("odd_lot_sell", FilledAttempt, None, 37),
    ],
)
def test_execution_matrix(
    execution_case: ExecutionCaseFactory,
    case_name: str,
    expected_type: type[FilledAttempt] | type[RejectedAttempt],
    reason_code: str | None,
    quantity: int,
) -> None:
    args, kwargs = execution_case(case_name)

    result = ExecutionSimulator().attempt(*args, **kwargs)

    assert isinstance(result, expected_type)
    assert getattr(result, "reason_code", None) == reason_code
    assert getattr(result, "quantity", 0) == quantity
```

Add the hand-calculated fee assertions separately:

```python
# backend/tests/features/backtests/test_fees.py
from decimal import Decimal

from backend.app.features.backtests.fees import RESEARCH_FEE_SCHEDULE, calculate_fee
from backend.app.features.backtests.models import OrderSide


def test_research_fee_schedule_has_minimum_commission_tax_and_transfer_fee() -> None:
    notional = Decimal("10000")

    assert calculate_fee(RESEARCH_FEE_SCHEDULE, OrderSide.BUY, notional) == Decimal("5.10")
    assert calculate_fee(RESEARCH_FEE_SCHEDULE, OrderSide.SELL, notional) == Decimal("10.10")
```

- [ ] **Step 2: Run RED**

Run `python -m pytest backend/tests/features/backtests/test_execution.py backend/tests/features/backtests/test_fees.py -q`.

Expected: import failure for `ExecutionSimulator`.

- [ ] **Step 3: Implement explicit attempt results**

`ExecutionSimulator.attempt()` returns `FilledAttempt` or `RejectedAttempt`; it never drops an order.
Store order id, date, theoretical/actual price, fee version, slippage, quantity, and reason code.

Implement the V2.12 stop model exactly:

```python
def stop_price(bar: DailyBar, stop: Decimal, slippage: Decimal) -> Decimal | None:
    if bar.open <= stop:
        return bar.open * (Decimal("1") - slippage)
    if bar.low <= stop:
        return stop * (Decimal("1") - slippage)
    return None
```

Check suspension, limit lock, and participation before producing a fill.

`fees.py` makes the research assumption explicit and versioned:

```python
@dataclass(frozen=True)
class FeeSchedule:
    version: str
    commission_rate: Decimal
    minimum_commission: Decimal
    stamp_tax_sell_rate: Decimal
    transfer_rate: Decimal


RESEARCH_FEE_SCHEDULE = FeeSchedule(
    version="research-cn-a-2023-08-28",
    commission_rate=Decimal("0.0003"),
    minimum_commission=Decimal("5"),
    stamp_tax_sell_rate=Decimal("0.0005"),
    transfer_rate=Decimal("0.00001"),
)


def calculate_fee(schedule: FeeSchedule, side: OrderSide, notional: Decimal) -> Decimal:
    commission = max(schedule.minimum_commission, notional * schedule.commission_rate)
    transfer = notional * schedule.transfer_rate
    stamp = notional * schedule.stamp_tax_sell_rate if side is OrderSide.SELL else Decimal("0")
    return (commission + transfer + stamp).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```

This schedule is a research assumption, not a historical truth. Plan 05 replaces it with dated PIT fee
schedules and fails strict runs when the correct date has no schedule.

- [ ] **Step 4: Run GREEN and commit**

```bash
python -m pytest backend/tests/features/backtests/test_execution.py backend/tests/features/backtests/test_fees.py -q
git add backend/app/features/backtests/execution.py backend/app/features/backtests/fees.py backend/tests/features/backtests/test_execution.py backend/tests/features/backtests/test_fees.py
git commit -m "feat(backtests): model A-share execution failures"
```

Expected: every matrix case passes.

### Task 4: Build the deterministic daily event loop

**Files:**
- Create: `backend/app/features/backtests/engine.py`
- Test: `backend/tests/features/backtests/test_engine.py`

- [ ] **Step 1: Write a failing event-order golden test**

Use a three-day engine fixture whose injected collaborators append their calls to `observed_events`:

```python
# backend/tests/features/backtests/test_engine.py
from backend.app.features.backtests.engine import BacktestEngine
from backend.app.features.backtests.models import BacktestRequest, StrategyGroup
from backend.app.contracts.grades import LlmGrade


def test_daily_event_order_and_next_day_execution(
    three_day_engine: tuple[BacktestEngine, list[str]],
    three_day_request: BacktestRequest,
) -> None:
    engine, observed_events = three_day_engine

    result = engine.run(three_day_request, StrategyGroup.A, LlmGrade.NOT_USED)

    assert observed_events[:5] == [
        "pre_open_risk",
        "open_execution",
        "intraday_stops",
        "close_valuation",
        "post_close_decision",
    ]
    assert result.equity_curve[0]["trade_date"] == "2024-01-02"
    assert result.trades[0]["signal_date"] == "2024-01-02"
    assert result.trades[0]["trade_date"] == "2024-01-03"
```

- [ ] **Step 2: Run RED**

Run `python -m pytest backend/tests/features/backtests/test_engine.py -q`.

Expected: collection fails with
`ModuleNotFoundError: No module named 'backend.app.features.backtests.engine'`.

- [ ] **Step 3: Implement `BacktestEngine`**

Inject `PointInTimeWarehouse`, `BacktestTradingDayPort`, `BacktestDecisionPort`, `ExecutionSimulator`, and
`PortfolioLedger`. The trading-day port supplies the date sequence; `PointInTimeWarehouse` is used only
through `snapshot(as_of_time=..., scope=SnapshotScope.backtest(...))`. Request snapshots at explicit
Shanghai-time boundaries. Record every intent, attempt, fill, risk event, and close snapshot. Hash
strategy version, parameter set, data batch ids, fee version, execution settings, and experiment group
into the input manifest before execution.

```python
from collections.abc import Mapping
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from backend.app.core.market.pit_models import SnapshotScope
from backend.app.features.backtests.ports import BacktestDecision, BacktestDecisionContext


SHANGHAI = ZoneInfo("Asia/Shanghai")


class BacktestEngine:
    def run(
        self,
        request: BacktestRequest,
        group: StrategyGroup,
        llm_grade: LlmGrade,
    ) -> BacktestGroupResult:
        group_request = request.with_group(group)
        manifest = self._build_manifest(group_request)
        ledger = PortfolioLedger.opening(group_request.initial_cash)
        candidate_states: dict[str, str] = {}
        trade_days = self._trading_days.between(
            group_request.start_date,
            group_request.end_date,
        )
        for index, trade_day in enumerate(trade_days):
            self._run_pre_open_risk(trade_day, ledger)
            self._run_open_execution(trade_day, ledger)
            self._run_intraday_stops(trade_day, ledger)
            self._record_close_valuation(trade_day, ledger)
            if index + 1 < len(trade_days):
                decision = self._run_post_close_decision(
                    trade_day,
                    trade_days[index + 1],
                    ledger,
                    candidate_states,
                    group_request,
                    group,
                )
                candidate_states = dict(decision.candidate_states)
        return self._build_group_result(manifest, ledger, group, llm_grade)

    def _run_post_close_decision(
        self,
        trade_day: date,
        next_trade_date: date,
        ledger: PortfolioLedger,
        candidate_states: Mapping[str, str],
        request: BacktestRequest,
        group: StrategyGroup,
    ) -> BacktestDecision:
        as_of_time = datetime.combine(trade_day, time(15, 30), SHANGHAI)
        history_start = datetime.combine(request.start_date, time.min, SHANGHAI)
        snapshot = self._warehouse.snapshot(
            as_of_time=as_of_time,
            scope=SnapshotScope.backtest((), history_start),
        )
        context = BacktestDecisionContext(
            as_of_time=as_of_time,
            next_trade_date=next_trade_date,
            strategy_version=request.strategy_version,
            group=group,
            snapshot=snapshot,
            portfolio=ledger.to_portfolio_snapshot(as_of_time),
            candidate_states=candidate_states,
        )
        return self._decision_port.decide(context)
```

Candidate lifecycle state belongs to this `run()` invocation. The engine must not save it on the engine
or adapter instance. `ExperimentRunner` invokes `run(request.with_group(group), group)` separately for
each requested group, so A-D cannot share candidate state or a mutable portfolio ledger.

- [ ] **Step 4: Verify replay and run GREEN**

Run the same fixture twice. After excluding run id and wall-clock creation time, serialized results and
manifest hashes must be byte-identical.

Run `python -m pytest backend/tests/features/backtests/test_engine.py -q`.

Expected: event-order and replay tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/features/backtests/engine.py backend/tests/features/backtests/test_engine.py
git commit -m "feat(backtests): replay deterministic daily events"
```

### Task 5: Add A-D experiment isolation

**Files:**
- Create: `backend/app/features/backtests/experiments.py`
- Test: `backend/tests/features/backtests/test_experiments.py`

- [ ] **Step 1: Write failing factor-mask tests**

```python
# backend/tests/features/backtests/test_experiments.py
from backend.app.contracts.grades import LlmGrade
from backend.app.features.backtests.experiments import ExperimentRunner, FACTOR_MASKS, llm_grade_for
from backend.app.features.backtests.models import BacktestRequest, StrategyGroup


EXPECTED_MASKS: dict[StrategyGroup, frozenset[str]] = {
    StrategyGroup.A: frozenset({"R", "T", "V"}),
    StrategyGroup.B: frozenset({"F", "R", "T", "V"}),
    StrategyGroup.C: frozenset({"P", "R", "T", "V"}),
    StrategyGroup.D: frozenset({"P", "F", "R", "T", "V"}),
}


def test_factor_masks_differ_only_by_selected_factor() -> None:
    assert FACTOR_MASKS == EXPECTED_MASKS
    assert set.intersection(*(set(mask) for mask in FACTOR_MASKS.values())) == {"R", "T", "V"}


def test_only_group_a_avoids_reconstructed_llm_output() -> None:
    assert llm_grade_for(StrategyGroup.A) is LlmGrade.NOT_USED
    assert all(
        llm_grade_for(group) is LlmGrade.RECONSTRUCTED
        for group in (StrategyGroup.B, StrategyGroup.C, StrategyGroup.D)
    )


def test_non_factor_manifest_fields_are_identical(
    recorded_group_manifests: dict[StrategyGroup, dict[str, object]],
) -> None:
    shared_fields = (
        "universe_hash",
        "market_filter_hash",
        "execution_settings_hash",
        "fee_schedule_version",
        "risk_budget",
        "start_date",
        "end_date",
    )
    baseline = recorded_group_manifests[StrategyGroup.A]

    for manifest in recorded_group_manifests.values():
        assert {field: manifest[field] for field in shared_fields} == {
            field: baseline[field] for field in shared_fields
        }


def test_candidate_state_starts_empty_for_every_group(
    group_state_fixture: tuple[
        ExperimentRunner,
        BacktestRequest,
        list[dict[str, str]],
    ],
) -> None:
    runner, request, observed_initial_states = group_state_fixture

    runner.run(request)

    assert observed_initial_states == [{}, {}, {}, {}]
```

- [ ] **Step 2: Run RED**

Run `python -m pytest backend/tests/features/backtests/test_experiments.py -q`.

Expected: collection fails with
`ModuleNotFoundError: No module named 'backend.app.features.backtests.experiments'`.

- [ ] **Step 3: Implement `ExperimentRunner`**

Run each group with one factor mask and an otherwise identical base manifest. Reject comparisons with any
non-factor difference. Group A uses `llm_grade=not_used`; B/C/D retain `reconstructed` when their selected
P or F factor uses reconstructed LLM output.

```python
import hashlib

from backend.app.features.backtests.engine import BacktestEngine
from backend.app.features.backtests.models import (
    BacktestExperimentResult,
    BacktestGroupResult,
    BacktestRequest,
    StrategyGroup,
)


FACTOR_MASKS: dict[StrategyGroup, frozenset[str]] = {
    StrategyGroup.A: frozenset({"R", "T", "V"}),
    StrategyGroup.B: frozenset({"F", "R", "T", "V"}),
    StrategyGroup.C: frozenset({"P", "R", "T", "V"}),
    StrategyGroup.D: frozenset({"P", "F", "R", "T", "V"}),
}


def llm_grade_for(group: StrategyGroup) -> LlmGrade:
    return LlmGrade.NOT_USED if group is StrategyGroup.A else LlmGrade.RECONSTRUCTED


def combine_group_results(
    request: BacktestRequest,
    results: tuple[BacktestGroupResult, ...],
) -> BacktestExperimentResult:
    manifest_input = "|".join(result.input_manifest_hash for result in results)
    return BacktestExperimentResult(
        request=request,
        input_manifest_hash=hashlib.sha256(manifest_input.encode("utf-8")).hexdigest(),
        groups=results,
        warnings=sorted({warning for result in results for warning in result.warnings}),
    )


class ExperimentRunner:
    def __init__(self, engine: BacktestEngine) -> None:
        self._engine = engine

    def run(self, request: BacktestRequest) -> BacktestExperimentResult:
        results = tuple(
            self._engine.run(
                request.with_group(group),
                group,
                llm_grade_for(group),
            )
            for group in request.groups
        )
        return combine_group_results(request, results)
```

- [ ] **Step 4: Run GREEN and commit**

```bash
python -m pytest backend/tests/features/backtests/test_experiments.py -q
git add backend/app/features/backtests/experiments.py backend/tests/features/backtests/test_experiments.py
git commit -m "feat(backtests): isolate V2.12 factor experiments"
```

Expected: `4 passed`; all four masks retain R/T/V, only group A has `llm_grade=not_used`, every
non-factor manifest field is identical, and each group starts with empty candidate state.

### Task 6: Calculate V2.12 research metrics

**Files:**
- Create: `backend/app/features/backtests/metrics.py`
- Test: `backend/tests/features/backtests/test_metrics.py`

- [ ] **Step 1: Write hand-calculated metric tests**

Use fixed equity/trade fixtures with hand-calculated values:

```python
# backend/tests/features/backtests/test_metrics.py
from decimal import Decimal

from backend.app.features.backtests.metrics import MetricsReporter, closed_trade_gate, safe_ratio
from backend.app.features.backtests.models import BacktestGroupResult


def test_hand_calculated_metrics(fixed_metric_result: BacktestGroupResult) -> None:
    observed = MetricsReporter().calculate(fixed_metric_result)

    expected = {
        "annualized_return": Decimal("0.10"),
        "maximum_drawdown": Decimal("-0.20"),
        "recovery": Decimal("0.50"),
        "calmar": Decimal("0.50"),
        "profit_factor": Decimal("2.00"),
        "net_win_rate": Decimal("0.50"),
        "average_win_loss": Decimal("2.00"),
        "expectancy": Decimal("0.25"),
        "turnover": Decimal("0.40"),
        "costs": Decimal("15.20"),
        "slippage": Decimal("0.001"),
        "average_exposure": Decimal("0.60"),
        "maximum_industry_exposure": Decimal("0.35"),
        "maximum_risk": Decimal("0.012"),
        "unfilled_rate": Decimal("0.25"),
        "limit_block_count": Decimal("1"),
    }
    assert {name: observed[name].value for name in expected} == expected
    assert observed["r_distribution"].breakdown == {
        "negative": Decimal("1"),
        "zero": Decimal("0"),
        "positive": Decimal("1"),
    }
    assert set(observed["market_regime"].breakdown) == {"bull", "neutral", "bear"}
    assert set(observed["strategy_book"].breakdown) == {"growth", "value"}


def test_zero_denominator_and_sample_size_fail_closed() -> None:
    assert safe_ratio(Decimal("1"), Decimal("0")).diagnostic == "ZERO_DENOMINATOR"
    assert closed_trade_gate(199).passed is False
    assert closed_trade_gate(200).passed is True
```

- [ ] **Step 2: Run RED**

Run `python -m pytest backend/tests/features/backtests/test_metrics.py -q`.

Expected: collection fails with
`ModuleNotFoundError: No module named 'backend.app.features.backtests.metrics'`.

- [ ] **Step 3: Implement `MetricsReporter` and acceptance results**

Zero denominators return `None` plus a diagnostic code, never infinity or silent zero. Round only in the
presentation layer. Each V2.12 section 18.4 gate returns observed value, pass/fail, and reason. Fewer than
200 sample-out closed trades always yields `passed=false`.

```python
@dataclass(frozen=True)
class MetricValue:
    value: Decimal | None
    diagnostic: str | None = None


def safe_ratio(numerator: Decimal, denominator: Decimal) -> MetricValue:
    if denominator == 0:
        return MetricValue(value=None, diagnostic="ZERO_DENOMINATOR")
    return MetricValue(value=numerator / denominator)


def closed_trade_gate(count: int) -> AcceptanceGate:
    return AcceptanceGate(
        name="sample_out_closed_trades",
        observed=count,
        threshold=200,
        passed=count >= 200,
    )
```

- [ ] **Step 4: Run GREEN and commit**

```bash
python -m pytest backend/tests/features/backtests/test_metrics.py -q
git add backend/app/features/backtests/metrics.py backend/tests/features/backtests/test_metrics.py
git commit -m "feat(backtests): report V2.12 research gates"
```

Expected: `2 passed`; zero denominators return diagnostics and 199 closed trades fail the sample gate.

### Task 7: Persist runs and expose a feature-local API

**Files:**
- Create: `backend/app/features/backtests/db_models.py`
- Create: `backend/app/features/backtests/repository.py`
- Create: `backend/app/features/backtests/service.py`
- Create: `backend/app/features/backtests/handler.py`
- Create: `backend/app/features/backtests/schemas.py`
- Create: `backend/app/features/backtests/router.py`
- Create: `backend/app/features/backtests/module.py`
- Test: `backend/tests/features/backtests/test_repository.py`
- Test: `backend/tests/features/backtests/test_api.py`

- [ ] **Step 1: Write failing repository and API tests**

Write the API contract with an exact request and response:

```python
# backend/tests/features/backtests/test_api.py
from fastapi.testclient import TestClient


REQUEST_BODY: dict[str, object] = {
    "strategy_version": "v2.12",
    "start_date": "2020-01-02",
    "end_date": "2023-12-29",
    "initial_cash": "150000",
    "groups": ["A", "B", "C", "D"],
}


def test_submit_is_async_research_only_and_idempotent(client: TestClient) -> None:
    headers = {"Idempotency-Key": "research-run-1"}

    first = client.post("/api/v1/backtests", json=REQUEST_BODY, headers=headers)
    second = client.post("/api/v1/backtests", json=REQUEST_BODY, headers=headers)

    assert first.status_code == 202
    assert first.headers["Location"] == f"/api/v1/backtests/{first.json()['run_id']}"
    assert first.json()["run_id"] == second.json()["run_id"]
    assert first.json()["status"] == "queued"


def test_result_pages_preserve_grades_and_cursor(client: TestClient) -> None:
    response = client.get("/api/v1/backtests/run-1?trade_limit=1")

    assert response.status_code == 200
    groups = response.json()["groups"]
    assert [(item["group"], item["data_grade"], item["llm_grade"]) for item in groups] == [
        ("A", "research", "not_used"),
        ("B", "research", "reconstructed"),
        ("C", "research", "reconstructed"),
        ("D", "research", "reconstructed"),
    ]
    assert response.json()["trades"]["next_cursor"] == "trade-2"
```

Write the PostgreSQL round-trip separately:

```python
# backend/tests/features/backtests/test_repository.py
from datetime import timezone
from decimal import Decimal
from uuid import UUID

from backend.app.features.backtests.models import BacktestExperimentResult
from backend.app.features.backtests.repository import SqlBacktestRepository


def test_result_round_trip_preserves_decimal_and_aware_time(
    repository: SqlBacktestRepository,
    fixed_result: BacktestExperimentResult,
) -> None:
    run_id = UUID("00000000-0000-0000-0000-000000000001")

    repository.save_result(run_id, fixed_result)
    restored = repository.fetch_result(run_id)
    summary = repository.fetch_summary(run_id)

    assert restored.request.initial_cash == Decimal("150000")
    assert [item.llm_grade.value for item in restored.groups] == [
        "not_used",
        "reconstructed",
        "reconstructed",
        "reconstructed",
    ]
    assert summary.created_at.tzinfo is not None
    assert summary.created_at.utcoffset() == timezone.utc.utcoffset(summary.created_at)
    assert restored.input_manifest_hash == fixed_result.input_manifest_hash
    assert restored.warnings == fixed_result.warnings
```

- [ ] **Step 2: Run RED**

```bash
python -m pytest backend/tests/features/backtests/test_repository.py \
    backend/tests/features/backtests/test_api.py -q
```

Expected: collection fails because `db_models.py`, `repository.py`, and `router.py` do not exist.

- [ ] **Step 3: Implement persistence and service**

Define SQLAlchemy models but no Alembic revision. Repository methods create, claim, save, fail, fetch,
page curves, and page trades. `BacktestService.submit()` writes a typed foundation queue payload and
returns immediately. Publish results only after the transaction containing metrics and artifacts commits.

```python
class SqlBacktestRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def publish_result(
        self,
        run_id: UUID,
        result: BacktestExperimentResult,
        artifacts: ArtifactRepository,
    ) -> None:
        with self._session_factory.begin() as session:
            session.add(BacktestResultRow.from_result(run_id, result))
            artifacts.save_json(session, run_id, "backtest-result.json", result.model_dump(mode="json"))


class BacktestService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        clock: Callable[[], datetime],
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    def submit(self, request: BacktestRequest, idempotency_key: str) -> RunRef:
        with self._session_factory.begin() as session:
            row = RunRepository(session).submit(
                RunKind.BACKTEST,
                request.model_dump(mode="json"),
                idempotency_key,
                self._clock(),
            )
            return RunRef(
                run_id=str(row.id),
                kind=RunKind.BACKTEST,
                status=RunStatus(row.status),
                submitted_at=row.submitted_at,
                links=RunLinks(self=f"/api/v1/runs/{row.id}"),
            )
```

- [ ] **Step 4: Export the router**

Create a router factory; do not edit `main.py`. Use the foundation `ErrorResponse` for invalid ranges,
missing data, and failed runs. `module.py` is the only integration surface.

```python
def build_backtest_router(service: BacktestService) -> APIRouter:
    router = APIRouter(prefix="/backtests", tags=["backtests"])

    @router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=RunRef)
    def submit_backtest(
        request: BacktestRequest,
        response: Response,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> RunRef:
        run_ref = service.submit(request, idempotency_key)
        response.headers["Location"] = f"/api/v1/backtests/{run_ref.run_id}"
        return run_ref

    return router
```

```python
@dataclass(frozen=True)
class BacktestDependencies:
    service: BacktestService
    job_handler: JobHandler


def build_backtest_feature(dependencies: BacktestDependencies) -> FeatureModule:
    return FeatureModule(
        name="backtests",
        router=build_backtest_router(dependencies.service),
        job_handlers=((RunKind.BACKTEST, dependencies.job_handler),),
    )
```

`handler.py` exposes a callable `BacktestJobHandler`. It validates the persisted run payload, invokes the
engine, emits heartbeats, and atomically saves the structured result before returning:

```python
class BacktestJobHandler:
    def __init__(
        self,
        runner: ExperimentRunner,
        repository: BacktestRepository,
        artifacts: ArtifactRepository,
    ) -> None:
        self._runner = runner
        self._repository = repository
        self._artifacts = artifacts

    def __call__(self, context: JobContext) -> None:
        request = BacktestRequest.model_validate(context.payload)
        context.heartbeat("replaying", 10)
        result = self._runner.run(request)
        self._repository.publish_result(context.run_id, result, self._artifacts)
        context.heartbeat("persisted", 100)
```

`module.py` also exposes the concrete construction boundary used by plan 06:

```python
def build_backtest_dependencies(
    session_factory: sessionmaker[Session],
    warehouse: PointInTimeWarehouse,
    trading_days: BacktestTradingDayPort,
    decision_port: BacktestDecisionPort,
    execution_simulator: ExecutionSimulator,
    artifact_repository: ArtifactRepository,
    clock: Callable[[], datetime],
) -> BacktestDependencies:
    result_repository = SqlBacktestRepository(session_factory)
    engine = BacktestEngine(
        warehouse,
        trading_days,
        decision_port,
        execution_simulator,
        PortfolioLedger,
    )
    runner = ExperimentRunner(engine)
    return BacktestDependencies(
        service=BacktestService(session_factory, clock),
        job_handler=BacktestJobHandler(runner, result_repository, artifact_repository),
    )
```

- [ ] **Step 5: Run GREEN and commit**

```bash
python -m pytest backend/tests/features/backtests/test_repository.py \
    backend/tests/features/backtests/test_api.py -q
git add backend/app/features/backtests backend/tests/features/backtests
git commit -m "feat(backtests): persist research runs and results"
```

Expected: API and PostgreSQL tests PASS; duplicate idempotency keys return one run id, persisted Decimal
values and aware timestamps round-trip, and per-group grades are A=`not_used`, B/C/D=`reconstructed`.

### Task 8: Build research backtest Web views

**Files:**
- Create: `web/src/features/backtests/api.ts`
- Create: `web/src/features/backtests/index.tsx`
- Create: `web/src/features/backtests/BacktestPage.tsx`
- Create: `web/src/features/backtests/BacktestForm.tsx`
- Create: `web/src/features/backtests/BacktestSummary.tsx`
- Create: `web/src/features/backtests/EquityDrawdownChart.tsx`
- Create: `web/src/features/backtests/TradeTable.tsx`
- Create: `web/src/features/backtests/backtests.module.css`
- Test: `web/src/features/backtests/BacktestPage.test.tsx`

- [ ] **Step 1: Write failing component tests**

Mock only the generated client and assert the user-visible contract:

```tsx
// web/src/features/backtests/BacktestPage.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { BacktestPage } from "./BacktestPage";
import * as api from "./api";

vi.mock("./api");

describe("BacktestPage", () => {
    it("submits and renders honest research labels", async () => {
        vi.mocked(api.submitBacktest).mockResolvedValue({ run_id: "run-1", status: "queued" });
        vi.mocked(api.getBacktest).mockResolvedValue({
            run_id: "run-1",
            status: "succeeded",
            groups: [
                { group: "A", data_grade: "research", llm_grade: "not_used" },
                { group: "B", data_grade: "research", llm_grade: "reconstructed" },
                { group: "C", data_grade: "research", llm_grade: "reconstructed" },
                { group: "D", data_grade: "research", llm_grade: "reconstructed" },
            ],
            acceptance: [{ name: "sample_out_closed_trades", passed: false }],
            equity_curve: [{ date: "2024-01-02", equity: "150000", drawdown: "0" }],
            trades: { items: [], next_cursor: "trade-2" },
        });

        render(<BacktestPage />);
        await userEvent.click(screen.getByRole("button", { name: "开始回测" }));

        expect(await screen.findByText("研究级数据")).toBeVisible();
        expect(screen.getByText("重建 LLM 因子")).toBeVisible();
        expect(screen.getByText("未通过：样本外平仓数")).toBeVisible();
        expect(screen.queryByText("策略已验证")).not.toBeInTheDocument();
        expect(screen.getByTestId("equity-series")).toBeVisible();
        expect(screen.getByTestId("drawdown-series")).toBeVisible();
        expect(screen.getByRole("button", { name: "下一页" })).toBeEnabled();
    });
});
```

- [ ] **Step 2: Run RED**

Run `cd web && npm test -- --run src/features/backtests/BacktestPage.test.tsx`.

Expected: feature component imports fail.

- [ ] **Step 3: Implement the feature slice**

Use generated client types, TanStack Query, ECharts, and local CSS modules. Poll only queued/running runs
and stop at terminal status. Export `backtestsFeature: FeatureDefinition` from `index.tsx`; do not edit
global routing or duplicate DTOs.

```tsx
export function BacktestPage(): JSX.Element {
    const [runId, setRunId] = useState<string>();
    const run = useBacktestRun(runId, {
        refetchInterval: (query) => {
            const status = query.state.data?.status;
            return status === "queued" || status === "running" ? 1_500 : false;
        },
    });

    return (
        <section>
            <GradeBadge grade="research">研究级数据</GradeBadge>
            <BacktestForm onSubmitted={setRunId} />
            {run.data ? <BacktestSummary result={run.data} /> : null}
        </section>
    );
}
```

```tsx
export const backtestsFeature: FeatureDefinition = {
    id: "backtests",
    path: "/backtests",
    label: "历史回测",
    element: <BacktestPage />,
};
```

- [ ] **Step 4: Run GREEN and commit**

```bash
cd web
npm test -- --run src/features/backtests/BacktestPage.test.tsx
npm run typecheck
cd ..
git add web/src/features/backtests
git commit -m "feat(web): visualize research backtests honestly"
```

Expected: Vitest PASS; TypeScript reports zero errors; the production build creates
`web/dist/index.html`.

### Task 9: Verify isolated ownership and behavior

**Files:**
- Verify: `backend/app/features/backtests/__init__.py`
- Verify: `backend/app/features/backtests/models.py`
- Verify: `backend/app/features/backtests/ports.py`
- Verify: `backend/app/features/backtests/ledger.py`
- Verify: `backend/app/features/backtests/execution.py`
- Verify: `backend/app/features/backtests/fees.py`
- Verify: `backend/app/features/backtests/engine.py`
- Verify: `backend/app/features/backtests/experiments.py`
- Verify: `backend/app/features/backtests/metrics.py`
- Verify: `backend/app/features/backtests/db_models.py`
- Verify: `backend/app/features/backtests/repository.py`
- Verify: `backend/app/features/backtests/service.py`
- Verify: `backend/app/features/backtests/handler.py`
- Verify: `backend/app/features/backtests/schemas.py`
- Verify: `backend/app/features/backtests/router.py`
- Verify: `backend/app/features/backtests/module.py`
- Verify: `backend/tests/features/backtests/fakes.py`
- Verify: `backend/tests/features/backtests/test_models.py`
- Verify: `backend/tests/features/backtests/test_ledger.py`
- Verify: `backend/tests/features/backtests/test_execution.py`
- Verify: `backend/tests/features/backtests/test_fees.py`
- Verify: `backend/tests/features/backtests/test_engine.py`
- Verify: `backend/tests/features/backtests/test_experiments.py`
- Verify: `backend/tests/features/backtests/test_metrics.py`
- Verify: `backend/tests/features/backtests/test_repository.py`
- Verify: `backend/tests/features/backtests/test_api.py`
- Verify: `web/src/features/backtests/api.ts`
- Verify: `web/src/features/backtests/index.tsx`
- Verify: `web/src/features/backtests/BacktestPage.tsx`
- Verify: `web/src/features/backtests/BacktestForm.tsx`
- Verify: `web/src/features/backtests/BacktestSummary.tsx`
- Verify: `web/src/features/backtests/EquityDrawdownChart.tsx`
- Verify: `web/src/features/backtests/TradeTable.tsx`
- Verify: `web/src/features/backtests/backtests.module.css`
- Verify: `web/src/features/backtests/BacktestPage.test.tsx`

- [ ] **Step 1: Run all feature checks**

```bash
python -m pytest backend/tests/features/backtests -q
```

Expected: all backtest tests PASS without live provider or LLM calls.

```bash
python -m ruff check backend/app/features/backtests backend/tests/features/backtests
python -m mypy backend/app/features/backtests
```

Expected: Ruff prints `All checks passed!`; mypy prints `Success: no issues found`.

```bash
cd web
npm test -- --run src/features/backtests
npm run typecheck
npm run build
```

Expected: Vitest PASS; TypeScript reports zero errors; Vite exits 0 and creates `web/dist/index.html`.

- [ ] **Step 2: Audit ownership and honest labels**

```bash
cd /Users/bujiatang/workspace/DA-worktrees/04-backtest
git diff --name-only main...HEAD
test -z "$(git diff --name-only main...HEAD | \
  rg -v '^(backend/app/features/backtests/|backend/tests/features/backtests/|web/src/features/backtests/)')"
! rg -n 'DataGrade\.PIT_VERIFIED|data_grade\s*=.*pit_verified' \
  backend/app/features/backtests web/src/features/backtests
! rg -n '/Users/bujiatang/workspace/LA|shield_sword' \
  backend/app/features/backtests web/src/features/backtests
```

Expected: `git diff` lists only the exact files above; the ownership command exits 0 with no output;
neither negative `rg` command prints a match. Plan 04 never assigns `pit_verified` and has no LA runtime
reference.

- [ ] **Step 3: Commit verification corrections when needed**

```bash
git add backend/app/features/backtests backend/tests/features/backtests web/src/features/backtests
git commit -m "test(backtests): enforce reproducible research labeling"
git status --short
```

Expected: when corrections exist, the Conventional Commit succeeds and `git status --short` has no
output. Skip this commit when Step 1 and Step 2 required no file changes; the status command must still
have no output.
