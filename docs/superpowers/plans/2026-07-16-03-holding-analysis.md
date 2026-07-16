# Holding Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the V2.12 holding-analysis vertical slice that produces persisted, risk-first, deterministic advice for DA portfolio positions, including legacy opening balances, and visualizes the structured result without submitting a real order.

**Architecture:** The use case reads a point-in-time market snapshot and the DA `PortfolioSnapshot`, then calls the frozen shared `V212StrategyEngine` for market, factor, risk, and constraint facts. The holding feature owns only V2.12 action priority, T+1 advice status, add-on gating, persistence, and projections; LLM text can change validated P/F facts but cannot name an action or quantity, while price-risk exits continue when text data is invalid.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2, PostgreSQL, pytest, React 18, TypeScript, TanStack Query, Vitest, React Testing Library

---

## Dependencies, ownership, and frozen contracts

Complete plans `00-foundation-contracts` and `01-pit-and-legacy` before starting. Plan 02 may execute in
parallel because this plan does not import candidate-feature code. This plan owns only:

- `backend/app/features/holdings/**`;
- `backend/tests/features/holdings/**`;
- `web/src/features/holdings/**`.

It must not modify `backend/app/main.py`, `backend/app/core/**`, `backend/app/ports/**`,
`backend/app/contracts/**`, the Alembic revision chain, `contracts/openapi.json`,
`web/src/generated/**`, `web/src/app/featureRegistry.ts`, global routes, or global styles. Plan 06 performs
those integration changes.

The implementation imports these frozen dependencies:

```python
from backend.app.contracts.grades import DataGrade, LlmGrade
from backend.app.contracts.runs import Page, RunKind, RunRef
from backend.app.core.market.strategy_inputs import StrategyInputBuilder
from backend.app.core.portfolio.models import (
    PortfolioPosition,
    PortfolioSnapshot,
    PositionOrigin,
    StrategyBook,
)
from backend.app.core.strategy.reason_codes import ReasonCode
from backend.app.core.strategy.service import V212StrategyEngine
from backend.app.core.strategy.types import StrategyEvaluation
from backend.app.infrastructure.tasks.handlers import JobContext, JobHandler
from backend.app.ports.point_in_time import PointInTimeWarehouse, SnapshotScope
from backend.app.ports.portfolio import PortfolioReader, PortfolioWriter
from backend.app.ports.runs import RunSubmitter
```

The feature never recalculates P/F/R/T/V/S, MA20, MA60, ATR14, R multiple, market state, risk exposure,
position size, or industry/theme concentration. Those values and condition facts come from
`V212StrategyEngine.evaluate()`. If plan-00 names differ, adapt the mapping once in
`strategy_projection.py`, preserving the single shared implementation.

`PointInTimeSnapshot` exposes `llm_evidence_manifest` with `grade: LlmGrade`, `valid: bool`, and
`completed_at`. The holding result derives `llm_grade` from that manifest and never accepts a client grade.

Position reads and writes use the plan-01 `PortfolioReader` and `PortfolioWriter`. A PUT is an explicit
manual correction with an optimistic `expected_version` and audit reason; it is never converted into an
invented historical fill. A real execution uses
`PortfolioWriter.record_manual_fill(command: ManualFillCommand, expected_version: int)` and preserves its
actual price, fee, and execution time. PUT uses
`replace_positions_for_correction(snapshot: CorrectionSnapshot, expected_version: int, reason: str)`;
`ConcurrentPortfolioUpdate` maps to HTTP 409.

The holding projection requires one shared evaluation per security with these facts:

```text
security_id, close, market_state, factors, llm_factor_valid,
financial_or_policy_red_light, delisting_or_major_violation,
hard_stop_triggered, effective_stop_triggered,
market_or_portfolio_reduction_required, reduction_quantity,
swing_time_stop, swing_two_r_trim, swing_trailing_stop,
swing_rank_exit, core_ma20_reduce, core_ma60_exit,
core_rank_exit, core_trailing_stop, add_signal_confirmed,
profit_at_least_one_r, score_not_below_entry, raised_stop_risk_not_higher,
stop_raise_required, proposed_effective_stop,
add_constraint.allowed, add_constraint.planned_quantity,
quality_codes, evidence_refs
```

`StrategyEvaluation.portfolio_summary` supplies `gross_exposure_pct`, `portfolio_risk_pct`, and the final
market state after all overrides; the holding feature displays these values unchanged.

The feature repository owns its ORM rows. Only plan 06 creates the Alembic revision and registers the
router, worker handler, generated OpenAPI schema, and Web navigation entry.

## File map

| File | Responsibility |
| --- | --- |
| `backend/app/features/holdings/models.py` | Immutable action, advice item, and result models |
| `backend/app/features/holdings/priority.py` | V2.12 risk-first action priority and T+1 status |
| `backend/app/features/holdings/addition.py` | Deterministic one-time add-on gate |
| `backend/app/features/holdings/strategy_projection.py` | Maps shared strategy facts and aggregated positions to advice |
| `backend/app/features/holdings/quality.py` | Derives and validates LLM grade from PIT evidence manifest |
| `backend/app/features/holdings/repository.py` | Feature repository protocol and SQL implementation |
| `backend/app/features/holdings/service.py` | Point-in-time application orchestration |
| `backend/app/features/holdings/markdown.py` | One-way Markdown projection |
| `backend/app/features/holdings/contracts.py` | Feature-local Pydantic API DTOs |
| `backend/app/features/holdings/router.py` | Portfolio queries and async holding-analysis routes |
| `backend/app/features/holdings/jobs.py` | Dependency-injected worker handler |
| `backend/app/features/holdings/module.py` | Feature module factory for plan 06 |
| `web/src/features/holdings/api.ts` | Generated-schema HTTP calls |
| `web/src/features/holdings/viewModel.ts` | Presentation labels without business decisions |
| `web/src/features/holdings/HoldingCard.tsx` | Position, risk, factor, and evidence card |
| `web/src/features/holdings/PositionCorrectionForm.tsx` | Audited optimistic portfolio correction |
| `web/src/features/holdings/ManualFillForm.tsx` | Records actual execution price, fee, and time |
| `web/src/features/holdings/HoldingAnalysisPage.tsx` | Current result, run submission, and states |
| `web/src/features/holdings/index.tsx` | Feature definition export |

### Task 1: Define immutable holding-advice models

**Files:**
- Create: `backend/app/features/holdings/__init__.py`
- Create: `backend/app/features/holdings/models.py`
- Test: `backend/tests/features/holdings/test_models.py`

- [ ] **Step 1: Write the failing model test**

```python
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from backend.app.contracts.grades import DataGrade, LlmGrade
from backend.app.core.portfolio.models import PositionOrigin, StrategyBook
from backend.app.core.strategy.reason_codes import ReasonCode
from backend.app.features.holdings.models import (
    AdviceAction,
    HoldingAdviceItem,
    HoldingAnalysisResult,
    HoldingFactors,
    HoldingRiskSummary,
)


def test_holding_result_is_advisory_and_structured() -> None:
    item = HoldingAdviceItem(
        security_id="000001.SZ",
        security_name="平安银行",
        origin=PositionOrigin.RECORDED_TRADE,
        strategy_book=StrategyBook.CORE,
        quantity=1000,
        available_to_sell=1000,
        average_cost=Decimal("10.00"),
        close=Decimal("9.40"),
        market_state="weak",
        factors=HoldingFactors(
            p=Decimal("60"), f=Decimal("72"), r=Decimal("45"),
            t=Decimal("25"), v=Decimal("40"), s=Decimal("49.4"),
            percentile_rank=Decimal("0.62"),
        ),
        r_multiple=Decimal("-0.60"),
        effective_stop=Decimal("9.50"),
        proposed_effective_stop=None,
        advised_action=AdviceAction.EXIT_ALL,
        planned_quantity=1000,
        pending_target_action=None,
        reason_codes=(ReasonCode.HARD_STOP_TRIGGERED,),
        quality_codes=(),
        evidence_refs=(),
    )
    result = HoldingAnalysisResult(
        run_id="run-h1",
        portfolio_id="default",
        as_of_time=datetime(2026, 7, 16, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        strategy_version="v2.12",
        manifest_hash="sha256:manifest",
        data_grade=DataGrade.RESEARCH,
        llm_grade=LlmGrade.RECONSTRUCTED,
        summary=HoldingRiskSummary(
            equity=Decimal("150000"),
            cash=Decimal("80000"),
            gross_exposure_pct=Decimal("0.4667"),
            portfolio_risk_pct=Decimal("0.0120"),
            market_state="weak",
        ),
        items=(item,),
    )

    assert result.auto_trade_enabled is False
    assert result.human_confirm_required is True
    assert result.items[0].planned_quantity == 1000
```

- [ ] **Step 2: Run the test and verify the missing module failure**

Run: `python -m pytest backend/tests/features/holdings/test_models.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'backend.app.features.holdings'`.

- [ ] **Step 3: Implement the immutable models**

```python
# backend/app/features/holdings/models.py
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from backend.app.contracts.grades import DataGrade, LlmGrade
from backend.app.core.portfolio.models import PositionOrigin, StrategyBook
from backend.app.core.strategy.reason_codes import ReasonCode


class AdviceAction(StrEnum):
    HOLD = "hold"
    EXIT_ALL = "exit_all"
    REDUCE_HALF = "reduce_half"
    TRIM_ONE_THIRD = "trim_one_third"
    RAISE_STOP = "raise_stop"
    ADD = "add"
    PENDING_EXIT = "pending_exit"
    MANUAL_REVIEW = "manual_review"


@dataclass(frozen=True, slots=True)
class HoldingFactors:
    p: Decimal
    f: Decimal
    r: Decimal
    t: Decimal
    v: Decimal
    s: Decimal
    percentile_rank: Decimal


@dataclass(frozen=True, slots=True)
class HoldingRiskSummary:
    equity: Decimal
    cash: Decimal
    gross_exposure_pct: Decimal
    portfolio_risk_pct: Decimal
    market_state: str


@dataclass(frozen=True, slots=True)
class HoldingAdviceItem:
    security_id: str
    security_name: str
    origin: PositionOrigin
    strategy_book: StrategyBook | None
    quantity: int
    available_to_sell: int
    average_cost: Decimal
    close: Decimal
    market_state: str
    factors: HoldingFactors
    r_multiple: Decimal | None
    effective_stop: Decimal | None
    proposed_effective_stop: Decimal | None
    advised_action: AdviceAction
    planned_quantity: int
    pending_target_action: AdviceAction | None
    reason_codes: tuple[ReasonCode, ...]
    quality_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HoldingAnalysisResult:
    run_id: str
    portfolio_id: str
    as_of_time: datetime
    strategy_version: Literal["v2.12"]
    manifest_hash: str
    data_grade: DataGrade
    llm_grade: LlmGrade
    summary: HoldingRiskSummary
    items: tuple[HoldingAdviceItem, ...]
    auto_trade_enabled: bool = False
    human_confirm_required: bool = True
```

Create an empty `backend/app/features/holdings/__init__.py`.

- [ ] **Step 4: Run the model test**

Run: `python -m pytest backend/tests/features/holdings/test_models.py -q`

Expected: `1 passed`.

- [ ] **Step 5: Commit the model**

```bash
git add backend/app/features/holdings/__init__.py \
  backend/app/features/holdings/models.py \
  backend/tests/features/holdings/test_models.py
git commit -m "feat(holdings): establish auditable advice model"
```

### Task 2: Enforce V2.12 action priority and T+1 status

**Files:**
- Create: `backend/app/features/holdings/priority.py`
- Test: `backend/tests/features/holdings/test_priority.py`

- [ ] **Step 1: Write failing priority tests**

```python
from backend.app.features.holdings.models import AdviceAction
from backend.app.features.holdings.priority import HoldingRuleFacts, decide_action


def test_red_light_preempts_every_lower_priority_rule() -> None:
    facts = HoldingRuleFacts(
        quantity=900,
        available_to_sell=900,
        red_light=True,
        hard_stop=True,
        market_reduction=True,
        core_ma20_reduce=True,
    )

    decision = decide_action(facts)

    assert decision.action is AdviceAction.EXIT_ALL
    assert decision.quantity == 900
    assert decision.reason == "red_light"


def test_hard_stop_continues_when_llm_is_invalid() -> None:
    facts = HoldingRuleFacts(
        quantity=500,
        available_to_sell=500,
        llm_factor_valid=False,
        hard_stop=True,
    )

    assert decide_action(facts).action is AdviceAction.EXIT_ALL


def test_t_plus_one_lock_keeps_exit_pending_instead_of_faking_a_sale() -> None:
    facts = HoldingRuleFacts(
        quantity=500,
        available_to_sell=0,
        hard_stop=True,
    )

    decision = decide_action(facts)

    assert decision.action is AdviceAction.PENDING_EXIT
    assert decision.pending_target is AdviceAction.EXIT_ALL
    assert decision.quantity == 0


def test_market_reduction_preempts_book_exit() -> None:
    facts = HoldingRuleFacts(
        quantity=900,
        available_to_sell=900,
        market_reduction=True,
        reduction_quantity=300,
        swing_two_r_trim=True,
    )

    decision = decide_action(facts)

    assert decision.action is AdviceAction.REDUCE_HALF
    assert decision.quantity == 300


def test_stop_raise_is_advised_when_no_exit_rule_triggers() -> None:
    facts = HoldingRuleFacts(
        quantity=900,
        available_to_sell=900,
        stop_raise_required=True,
    )

    decision = decide_action(facts)

    assert decision.action is AdviceAction.RAISE_STOP
    assert decision.quantity == 0
```

- [ ] **Step 2: Run priority tests and verify failure**

Run: `python -m pytest backend/tests/features/holdings/test_priority.py -q`

Expected: FAIL because `priority.py` is missing.

- [ ] **Step 3: Implement the ordered decision table**

```python
# backend/app/features/holdings/priority.py
from dataclasses import dataclass

from backend.app.features.holdings.models import AdviceAction


@dataclass(frozen=True, slots=True)
class HoldingRuleFacts:
    quantity: int
    available_to_sell: int
    llm_factor_valid: bool = True
    red_light: bool = False
    delisting_risk: bool = False
    hard_stop: bool = False
    effective_stop: bool = False
    market_reduction: bool = False
    reduction_quantity: int = 0
    swing_time_stop: bool = False
    swing_two_r_trim: bool = False
    swing_trailing_stop: bool = False
    swing_rank_exit: bool = False
    core_ma20_reduce: bool = False
    core_ma60_exit: bool = False
    core_rank_exit: bool = False
    core_trailing_stop: bool = False
    stop_raise_required: bool = False


@dataclass(frozen=True, slots=True)
class ActionDecision:
    action: AdviceAction
    quantity: int
    pending_target: AdviceAction | None
    reason: str


def _sell_decision(
    facts: HoldingRuleFacts,
    action: AdviceAction,
    requested_quantity: int,
    reason: str,
) -> ActionDecision:
    quantity = min(requested_quantity, facts.available_to_sell)
    if requested_quantity > 0 and quantity == 0:
        return ActionDecision(AdviceAction.PENDING_EXIT, 0, action, "t_plus_one_locked")
    return ActionDecision(action, quantity, None, reason)


def decide_action(facts: HoldingRuleFacts) -> ActionDecision:
    if facts.red_light or facts.delisting_risk:
        return _sell_decision(facts, AdviceAction.EXIT_ALL, facts.quantity, "red_light")
    if facts.hard_stop or facts.effective_stop:
        return _sell_decision(facts, AdviceAction.EXIT_ALL, facts.quantity, "hard_stop")
    if facts.market_reduction:
        return _sell_decision(
            facts,
            AdviceAction.REDUCE_HALF,
            facts.reduction_quantity,
            "market_or_portfolio_reduction",
        )
    if facts.swing_time_stop or facts.swing_trailing_stop or facts.swing_rank_exit:
        return _sell_decision(facts, AdviceAction.EXIT_ALL, facts.quantity, "swing_exit")
    if facts.swing_two_r_trim:
        return _sell_decision(
            facts,
            AdviceAction.TRIM_ONE_THIRD,
            max(1, facts.quantity // 3),
            "swing_two_r_trim",
        )
    if facts.core_ma60_exit or facts.core_rank_exit or facts.core_trailing_stop:
        return _sell_decision(facts, AdviceAction.EXIT_ALL, facts.quantity, "core_exit")
    if facts.core_ma20_reduce:
        return _sell_decision(
            facts,
            AdviceAction.REDUCE_HALF,
            max(1, facts.quantity // 2),
            "core_ma20_reduce",
        )
    if facts.stop_raise_required:
        return ActionDecision(AdviceAction.RAISE_STOP, 0, None, "raise_stop")
    return ActionDecision(AdviceAction.HOLD, 0, None, "no_exit_rule")
```

This file orders already-computed facts. It must not derive MA, ATR, R, ranks, scores, market drawdown,
or portfolio risk. Sell quantities may include odd-lot tails; do not round sell advice to 100 shares.

- [ ] **Step 4: Run priority tests**

Run: `python -m pytest backend/tests/features/holdings/test_priority.py -q`

Expected: `5 passed`.

- [ ] **Step 5: Commit risk-first priority**

```bash
git add backend/app/features/holdings/priority.py \
  backend/tests/features/holdings/test_priority.py
git commit -m "feat(holdings): enforce risk-first advice priority"
```

### Task 3: Gate one-time add-on advice without loss averaging

**Files:**
- Create: `backend/app/features/holdings/addition.py`
- Test: `backend/tests/features/holdings/test_addition.py`

- [ ] **Step 1: Write failing add-on tests**

```python
import pytest

from backend.app.features.holdings.addition import AdditionFacts, decide_addition
from backend.app.features.holdings.models import AdviceAction


def test_all_v212_conditions_are_required_for_an_addition() -> None:
    decision = decide_addition(
        AdditionFacts(
            strategy_book_known=True,
            profit_at_least_one_r=True,
            add_signal_confirmed=True,
            score_not_below_entry=True,
            raised_stop_risk_not_higher=True,
            llm_factor_valid=True,
            constraint_allowed=True,
            planned_quantity=200,
            maximum_quantity=200,
            add_count=0,
        )
    )

    assert decision.action is AdviceAction.ADD
    assert decision.quantity == 200


@pytest.mark.parametrize(
    "override",
    [
        {"profit_at_least_one_r": False},
        {"add_signal_confirmed": False},
        {"score_not_below_entry": False},
        {"raised_stop_risk_not_higher": False},
        {"llm_factor_valid": False},
        {"constraint_allowed": False},
        {"add_count": 1},
        {"strategy_book_known": False},
    ],
)
def test_any_failed_condition_prevents_addition(override: dict[str, object]) -> None:
    facts = AdditionFacts.valid().with_override(**override)

    assert decide_addition(facts).action is AdviceAction.HOLD
    assert decide_addition(facts).quantity == 0
```

- [ ] **Step 2: Run add-on tests and verify failure**

Run: `python -m pytest backend/tests/features/holdings/test_addition.py -q`

Expected: FAIL because `addition.py` does not exist.

- [ ] **Step 3: Implement the complete gate**

```python
# backend/app/features/holdings/addition.py
from dataclasses import dataclass, replace

from backend.app.features.holdings.models import AdviceAction


@dataclass(frozen=True, slots=True)
class AdditionFacts:
    strategy_book_known: bool
    profit_at_least_one_r: bool
    add_signal_confirmed: bool
    score_not_below_entry: bool
    raised_stop_risk_not_higher: bool
    llm_factor_valid: bool
    constraint_allowed: bool
    planned_quantity: int
    maximum_quantity: int
    add_count: int

    @classmethod
    def valid(cls) -> "AdditionFacts":
        return cls(True, True, True, True, True, True, True, 200, 200, 0)

    def with_override(self, **changes: object) -> "AdditionFacts":
        return replace(self, **changes)


@dataclass(frozen=True, slots=True)
class AdditionDecision:
    action: AdviceAction
    quantity: int


def decide_addition(facts: AdditionFacts) -> AdditionDecision:
    allowed = all(
        (
            facts.strategy_book_known,
            facts.profit_at_least_one_r,
            facts.add_signal_confirmed,
            facts.score_not_below_entry,
            facts.raised_stop_risk_not_higher,
            facts.llm_factor_valid,
            facts.constraint_allowed,
            facts.add_count == 0,
            facts.planned_quantity > 0,
        )
    )
    if not allowed:
        return AdditionDecision(AdviceAction.HOLD, 0)
    quantity = min(facts.planned_quantity, facts.maximum_quantity)
    return AdditionDecision(AdviceAction.ADD, quantity)
```

`maximum_quantity` is calculated by the shared core from the initial buy quantity and the 50% cap. This
feature does not increase the shared result and never derives a larger quantity from LLM confidence.

- [ ] **Step 4: Run add-on tests**

Run: `python -m pytest backend/tests/features/holdings/test_addition.py -q`

Expected: `9 passed`.

- [ ] **Step 5: Commit add-on gating**

```bash
git add backend/app/features/holdings/addition.py \
  backend/tests/features/holdings/test_addition.py
git commit -m "feat(holdings): prevent loss averaging and repeat additions"
```

### Task 4: Project shared facts and legacy lots into deterministic advice

**Files:**
- Create: `backend/app/features/holdings/strategy_projection.py`
- Test: `backend/tests/features/holdings/test_strategy_projection.py`

- [ ] **Step 1: Write failing projection tests for normal and legacy lots**

```python
from backend.app.core.portfolio.models import PositionOrigin
from backend.app.features.holdings.models import AdviceAction
from backend.app.features.holdings.strategy_projection import project_holding
from backend.tests.factories.portfolio import portfolio_position
from backend.tests.factories.strategy import holding_security_evaluation


def test_exit_rule_wins_over_an_addition_signal() -> None:
    position = portfolio_position(quantity=600, available_to_sell=600, strategy_book="swing")
    evaluation = holding_security_evaluation(
        hard_stop_triggered=True,
        add_signal_confirmed=True,
        add_constraint_allowed=True,
    )

    advice = project_holding(position, evaluation)

    assert advice.advised_action is AdviceAction.EXIT_ALL
    assert advice.planned_quantity == 600


def test_legacy_opening_balance_never_invents_a_strategy_book() -> None:
    position = portfolio_position(
        origin=PositionOrigin.LEGACY_OPENING_BALANCE,
        strategy_book=None,
        quantity=500,
        available_to_sell=500,
    )
    evaluation = holding_security_evaluation(hard_stop_triggered=False)

    advice = project_holding(position, evaluation)

    assert advice.strategy_book is None
    assert advice.advised_action is AdviceAction.MANUAL_REVIEW
    assert advice.planned_quantity == 0


def test_legacy_hard_stop_still_produces_risk_exit_advice() -> None:
    position = portfolio_position(
        origin=PositionOrigin.LEGACY_OPENING_BALANCE,
        strategy_book=None,
        quantity=500,
        available_to_sell=500,
    )
    evaluation = holding_security_evaluation(hard_stop_triggered=True)

    advice = project_holding(position, evaluation)

    assert advice.advised_action is AdviceAction.EXIT_ALL
    assert advice.planned_quantity == 500
```

- [ ] **Step 2: Run projection tests and verify failure**

Run: `python -m pytest backend/tests/features/holdings/test_strategy_projection.py -q`

Expected: FAIL because `project_holding` is missing.

- [ ] **Step 3: Implement the shared-core mapping boundary**

In `project_holding(position: PortfolioPosition, evaluation: HoldingSecurityEvaluation)`, construct
`HoldingRuleFacts` exclusively from shared booleans and quantities. Call `decide_action()` before
`decide_addition()` so exit and reduction always win. Apply these exact rules:

```python
exit_decision = decide_action(exit_facts)
if exit_decision.action is not AdviceAction.HOLD:
    action = exit_decision.action
    quantity = exit_decision.quantity
    pending = exit_decision.pending_target
elif position.strategy_book is None:
    action = AdviceAction.MANUAL_REVIEW
    quantity = 0
    pending = None
else:
    addition = decide_addition(addition_facts)
    action = addition.action
    quantity = addition.quantity
    pending = None
```

Map `origin`, `strategy_book`, quantity, available quantity, average cost, current close, effective stop,
shared reason codes, quality codes, and evidence refs into `HoldingAdviceItem`. Never alter
`PortfolioPosition.average_cost`, `effective_stop`, `highest_close`, `initial_risk_per_share`, `strategy_book`, or
`add_count`. The feature emits advice only; it does not append fills or ledger events.

- [ ] **Step 4: Run projection tests**

Run: `python -m pytest backend/tests/features/holdings/test_strategy_projection.py -q`

Expected: `3 passed`.

- [ ] **Step 5: Commit the holding projection**

```bash
git add backend/app/features/holdings/strategy_projection.py \
  backend/tests/features/holdings/test_strategy_projection.py
git commit -m "feat(holdings): project deterministic risk-first advice"
```

### Task 5: Persist holding-analysis results idempotently

**Files:**
- Create: `backend/app/features/holdings/repository.py`
- Create: `backend/tests/features/holdings/factories.py`
- Create: `backend/tests/features/holdings/fakes.py`
- Test: `backend/tests/features/holdings/test_repository.py`

- [ ] **Step 1: Write a failing PostgreSQL round-trip test**

```python
from backend.app.features.holdings.repository import SqlHoldingAnalysisRepository
from backend.tests.features.holdings.factories import holding_analysis_result
from sqlalchemy.orm import Session, sessionmaker


def test_repository_round_trips_latest_result(session: Session) -> None:
    repository = SqlHoldingAnalysisRepository(session_factory)
    result = holding_analysis_result(run_id="run-h2", portfolio_id="default")

    repository.save(result)

    assert repository.get("run-h2") == result
    assert repository.latest("default") == result
```

- [ ] **Step 2: Run repository tests and verify failure**

Run: `python -m pytest backend/tests/features/holdings/test_repository.py -q`

Expected: FAIL because the repository is absent.

- [ ] **Step 3: Implement typed repository and feature ORM rows**

Define this protocol:

```python
class HoldingAnalysisRepository(Protocol):
    def save(self, result: HoldingAnalysisResult) -> None:
        raise NotImplementedError

    def get(self, run_id: str) -> HoldingAnalysisResult | None:
        raise NotImplementedError

    def latest(self, portfolio_id: str) -> HoldingAnalysisResult | None:
        raise NotImplementedError
```

Create feature-local SQLAlchemy models `HoldingAnalysisResultRow` and `HoldingAnalysisItemRow` for tables
`holding_analysis_results` and `holding_analysis_items`. Store decimals
as strings, timestamps with timezone, enum values as stable strings, and items ordered by `security_id`.
Use parameterized SQLAlchemy statements. `save()` is idempotent by run id and manifest hash; a conflicting
manifest raises `HoldingAnalysisConflict`. The codec must round-trip every Task-1 field without reading or
writing portfolio lots.

The concrete repository is synchronous and session-injected:

```python
from sqlalchemy.orm import Session


class SqlHoldingAnalysisRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, result: HoldingAnalysisResult) -> None:
        with self._session_factory.begin() as session:
            self._save_idempotently(session, result)

    def get(self, run_id: str) -> HoldingAnalysisResult | None:
        with self._session_factory() as session:
            return self._decode_result(session.get(HoldingAnalysisResultRow, run_id))

    def latest(self, portfolio_id: str) -> HoldingAnalysisResult | None:
        with self._session_factory() as session:
            return self._decode_result(self._latest_row(session, portfolio_id))
```

`_save_idempotently`, `_latest_row`, and `_decode_result` must use bound SQLAlchemy parameters and never
read or write LA files.

- [ ] **Step 4: Run PostgreSQL repository tests**

Run: `python -m pytest backend/tests/features/holdings/test_repository.py -q`

Expected: `1 passed` with the temporary PostgreSQL fixture.

- [ ] **Step 5: Commit persistence**

```bash
git add backend/app/features/holdings/repository.py \
  backend/tests/features/holdings/factories.py \
  backend/tests/features/holdings/fakes.py \
  backend/tests/features/holdings/test_repository.py
git commit -m "feat(holdings): persist advice results idempotently"
```

### Task 6: Orchestrate one point-in-time holding analysis

**Files:**
- Create: `backend/app/features/holdings/service.py`
- Create: `backend/app/features/holdings/quality.py`
- Test: `backend/tests/features/holdings/test_service.py`

- [ ] **Step 1: Write failing orchestration and invalid-LLM tests**

```python
from backend.app.features.holdings.models import AdviceAction
from backend.app.features.holdings.service import HoldingAnalysisService
from backend.app.ports.point_in_time import SnapshotScope
from backend.tests.features.holdings.factories import holding_command
from backend.tests.features.holdings.fakes import FakeHoldingAnalysisRepository
from backend.tests.fakes.pit import FakePointInTimeWarehouse
from backend.tests.fakes.portfolio import FakePortfolioReader
from backend.tests.fakes.strategy import FakeStrategyDecisionPort
from backend.tests.fakes.strategy_inputs import FakeStrategyInputBuilder


def test_service_reads_portfolio_and_market_at_identical_as_of_time() -> None:
    command = holding_command(run_id="run-h3")
    warehouse = FakePointInTimeWarehouse()
    portfolios = FakePortfolioReader.with_position()
    input_builder = FakeStrategyInputBuilder()
    strategy = FakeStrategyDecisionPort.with_holding_evaluation()
    repository = FakeHoldingAnalysisRepository()
    service = HoldingAnalysisService(
        warehouse,
        portfolios,
        input_builder,
        strategy,
        repository,
    )

    result = service.run(command)

    assert portfolios.requests == [(command.portfolio_id, command.as_of_time)]
    assert warehouse.requests == [
        (
            command.as_of_time,
            SnapshotScope.holding_analysis(("000001.SZ",)),
        )
    ]
    assert input_builder.requests == [
        (warehouse.snapshot_value, portfolios.snapshot_value, command.strategy_version)
    ]
    assert strategy.requests == [input_builder.prepared_value]
    assert result.manifest_hash == warehouse.snapshot_value.manifest_hash
    assert repository.saved == [result]


def test_invalid_llm_does_not_disable_an_existing_price_stop() -> None:
    command = holding_command(run_id="run-h4")
    strategy = FakeStrategyDecisionPort.with_holding_evaluation(
        llm_factor_valid=False,
        hard_stop_triggered=True,
    )
    service = HoldingAnalysisService(
        FakePointInTimeWarehouse(),
        FakePortfolioReader.with_position(),
        FakeStrategyInputBuilder(),
        strategy,
        FakeHoldingAnalysisRepository(),
    )

    result = service.run(command)

    assert result.items[0].advised_action is AdviceAction.EXIT_ALL
```

- [ ] **Step 2: Run service tests and verify failure**

Run: `python -m pytest backend/tests/features/holdings/test_service.py -q`

Expected: FAIL because `HoldingAnalysisService` does not exist.

- [ ] **Step 3: Implement the service using only PIT and portfolio ports**

Create `quality.py` before the service:

```python
from backend.app.contracts.grades import LlmGrade
from backend.app.core.market.pit_models import PointInTimeSnapshot


class InvalidLlmEvidence(ValueError):
    pass


def derive_llm_grade(snapshot: PointInTimeSnapshot) -> LlmGrade:
    manifest = snapshot.llm_evidence_manifest
    if manifest.completed_at > snapshot.as_of_time:
        raise InvalidLlmEvidence("LLM evidence manifest is invalid for this snapshot")
    if not manifest.valid:
        return LlmGrade.NOT_USED
    return manifest.grade
```

An invalid manifest yields `LlmGrade.NOT_USED`; the shared strategy still emits existing price-risk facts,
while its invalid-text gate prevents new additions. A future-dated manifest raises
`InvalidLlmEvidence` and fails the run closed.

```python
# backend/app/features/holdings/service.py
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from backend.app.core.market.strategy_inputs import StrategyInputBuilder
from backend.app.features.holdings.models import HoldingAnalysisResult, HoldingRiskSummary
from backend.app.features.holdings.quality import derive_llm_grade
from backend.app.features.holdings.repository import HoldingAnalysisRepository
from backend.app.features.holdings.strategy_projection import project_holding
from backend.app.ports.point_in_time import PointInTimeWarehouse, SnapshotScope
from backend.app.ports.portfolio import PortfolioReader
from backend.app.ports.strategy import StrategyDecisionPort


@dataclass(frozen=True, slots=True)
class HoldingAnalysisCommand:
    run_id: str
    portfolio_id: str
    as_of_time: datetime
    strategy_version: Literal["v2.12"] = "v2.12"


class HoldingAnalysisService:
    def __init__(
        self,
        warehouse: PointInTimeWarehouse,
        portfolios: PortfolioReader,
        input_builder: StrategyInputBuilder,
        strategy: StrategyDecisionPort,
        repository: HoldingAnalysisRepository,
    ) -> None:
        self._warehouse = warehouse
        self._portfolios = portfolios
        self._input_builder = input_builder
        self._strategy = strategy
        self._repository = repository

    def run(self, command: HoldingAnalysisCommand) -> HoldingAnalysisResult:
        portfolio = self._portfolios.snapshot(
            portfolio_id=command.portfolio_id,
            as_of_time=command.as_of_time,
        )
        security_ids = tuple(
            sorted({position.security_id for position in portfolio.positions})
        )
        snapshot = self._warehouse.snapshot(
            as_of_time=command.as_of_time,
            scope=SnapshotScope.holding_analysis(security_ids),
        )
        prepared = self._input_builder.build(
            snapshot=snapshot,
            portfolio=portfolio,
            strategy_version=command.strategy_version,
        )
        evaluation = self._strategy.evaluate(prepared)
        llm_grade = derive_llm_grade(snapshot)
        by_security = {
            security.security_id: security for security in evaluation.securities
        }
        items = tuple(
            project_holding(position, by_security[position.security_id])
            for position in portfolio.positions
        )
        result = HoldingAnalysisResult(
            run_id=command.run_id,
            portfolio_id=command.portfolio_id,
            as_of_time=command.as_of_time,
            strategy_version=command.strategy_version,
            manifest_hash=snapshot.manifest_hash,
            data_grade=snapshot.data_grade,
            llm_grade=llm_grade,
            summary=HoldingRiskSummary(
                equity=portfolio.equity,
                cash=portfolio.cash,
                gross_exposure_pct=evaluation.portfolio_summary.gross_exposure_pct,
                portfolio_risk_pct=evaluation.portfolio_summary.portfolio_risk_pct,
                market_state=evaluation.portfolio_summary.market_state,
            ),
            items=items,
        )
        self._repository.save(result)
        return result
```

Before projection, assert snapshot, portfolio, builder output, and evaluation use the same timezone-aware
`as_of_time`, strategy version, and manifest hash, and that every aggregated position has one evaluation.
The feature must not assemble strategy inputs itself. A missing price evaluation fails the run with stable code
`HOLDING_MARKET_DATA_MISSING`; it must not create a fabricated hold, exit, price, or fill.

- [ ] **Step 4: Run service tests**

Run: `python -m pytest backend/tests/features/holdings/test_service.py -q`

Expected: `2 passed`.

- [ ] **Step 5: Commit orchestration**

```bash
git add backend/app/features/holdings/service.py \
  backend/tests/features/holdings/test_service.py
git commit -m "feat(holdings): analyze portfolio at one decision time"
```

### Task 7: Render Markdown from the structured holding result

**Files:**
- Create: `backend/app/features/holdings/markdown.py`
- Test: `backend/tests/features/holdings/test_markdown.py`

- [ ] **Step 1: Write a failing projection test**

```python
from backend.app.features.holdings.markdown import render_holding_markdown
from backend.tests.features.holdings.factories import holding_analysis_result


def test_markdown_includes_action_risk_and_advisory_boundary() -> None:
    result = holding_analysis_result(run_id="run-h5")

    markdown = render_holding_markdown(result)

    assert "仅供人工确认，不自动下单" in markdown
    assert "legacy_opening_balance" in markdown
    assert "有效止损" in markdown
    assert result.manifest_hash in markdown
```

- [ ] **Step 2: Run the Markdown test and verify failure**

Run: `python -m pytest backend/tests/features/holdings/test_markdown.py -q`

Expected: FAIL because `render_holding_markdown` is absent.

- [ ] **Step 3: Implement a one-way renderer**

```python
# backend/app/features/holdings/markdown.py
from backend.app.contracts.grades import DataGrade
from backend.app.features.holdings.models import HoldingAnalysisResult


def render_holding_markdown(result: HoldingAnalysisResult) -> str:
    grade = "研究级数据" if result.data_grade is DataGrade.RESEARCH else "PIT 数据已验证"
    lines = [
        "# 持仓分析",
        "",
        f"> {grade}；仅供人工确认，不自动下单。",
        "",
        f"- 组合：{result.portfolio_id}",
        f"- as_of_time：{result.as_of_time.isoformat()}",
        f"- 输入 manifest：{result.manifest_hash}",
        f"- 市场状态：{result.summary.market_state}",
        f"- 总敞口：{result.summary.gross_exposure_pct}",
        f"- 组合风险：{result.summary.portfolio_risk_pct}",
        "",
    ]
    for item in result.items:
        reasons = ", ".join(code.value for code in item.reason_codes)
        lines.extend(
            (
                f"## {item.security_id} {item.security_name}",
                "",
                f"- 来源：{item.origin.value}",
                f"- 策略账本：{item.strategy_book.value if item.strategy_book else '未追认'}",
                f"- 建议动作：{item.advised_action.value}",
                f"- 规则计划数量：{item.planned_quantity}",
                f"- 可卖数量：{item.available_to_sell}",
                f"- P/F/R/T/V/S：{item.factors.p}/{item.factors.f}/{item.factors.r}/"
                f"{item.factors.t}/{item.factors.v}/{item.factors.s}",
                f"- 有效止损：{item.effective_stop if item.effective_stop else '未知'}",
                f"- 建议新止损：{item.proposed_effective_stop if item.proposed_effective_stop else '无'}",
                f"- 原因码：{reasons}",
                "",
            )
        )
    return "\n".join(lines)
```

Do not implement a Markdown parser or use Markdown to update the portfolio ledger.

- [ ] **Step 4: Run the projection test**

Run: `python -m pytest backend/tests/features/holdings/test_markdown.py -q`

Expected: `1 passed`.

- [ ] **Step 5: Commit the renderer**

```bash
git add backend/app/features/holdings/markdown.py \
  backend/tests/features/holdings/test_markdown.py
git commit -m "feat(holdings): render advice from structured analysis"
```

### Task 8: Expose portfolio queries, async analysis API, and worker handler

**Files:**
- Create: `backend/app/features/holdings/contracts.py`
- Create: `backend/app/features/holdings/jobs.py`
- Create: `backend/app/features/holdings/router.py`
- Create: `backend/app/features/holdings/module.py`
- Test: `backend/tests/features/holdings/test_api.py`
- Test: `backend/tests/features/holdings/test_jobs.py`

- [ ] **Step 1: Write failing API and job tests**

```python
from decimal import Decimal
import pytest
from pydantic import ValidationError

from backend.app.features.holdings.contracts import HoldingAnalysisRequest


def test_analysis_request_rejects_client_owned_strategy_and_llm_grade() -> None:
    with pytest.raises(ValidationError):
        HoldingAnalysisRequest.model_validate(
            {
                "portfolio_id": "default",
                "as_of_time": "2026-07-16T15:30:00+08:00",
                "strategy_version": "v9.99",
                "llm_grade": "forward_observed",
            }
        )


def test_submit_holding_analysis_returns_202(holding_api_client) -> None:
    response = holding_api_client.post(
        "/api/v1/holding-analyses",
        headers={"Idempotency-Key": "holding-20260716"},
        json={
            "portfolio_id": "default",
            "as_of_time": "2026-07-16T15:30:00+08:00",
        },
    )

    assert response.status_code == 202
    assert response.json()["kind"] == "holding_analysis"
    assert response.headers["location"].endswith(response.json()["run_id"])


def test_positions_preserve_legacy_origin_and_unknown_book(holding_api_client) -> None:
    response = holding_api_client.get("/api/v1/portfolio/positions")

    assert response.status_code == 200
    position = response.json()["items"][0]
    assert position["origin"] == "legacy_opening_balance"
    assert position["strategy_book"] is None


def test_position_put_is_an_audited_optimistic_correction(
    holding_api_client,
    fake_portfolio_writer,
) -> None:
    response = holding_api_client.put(
        "/api/v1/portfolio/positions",
        json={
            "portfolio_id": "default",
            "expected_version": 7,
            "reason": "核对券商对账单后修正数量",
            "positions": [
                {
                    "security_id": "000001.SZ",
                    "quantity": 500,
                    "average_cost": "10.20",
                    "effective_at": "2026-07-16T15:30:00+08:00",
                }
            ],
        },
    )

    assert response.status_code == 200
    assert fake_portfolio_writer.corrections[0].expected_version == 7
    assert fake_portfolio_writer.corrections[0].reason == "核对券商对账单后修正数量"


def test_manual_fill_records_actual_execution_instead_of_replacing_positions(
    holding_api_client,
    fake_portfolio_writer,
) -> None:
    response = holding_api_client.post(
        "/api/v1/portfolio/fills",
        json={
            "portfolio_id": "default",
            "expected_version": 8,
            "security_id": "000001.SZ",
            "side": "sell",
            "quantity": 100,
            "price": "10.35",
            "fee": "5.00",
            "executed_at": "2026-07-17T09:31:00+08:00",
        },
    )

    assert response.status_code == 200
    assert fake_portfolio_writer.manual_fills[0].price == Decimal("10.35")
    assert fake_portfolio_writer.manual_fills[0].fee == Decimal("5.00")


def test_worker_reports_durable_progress(fake_job_context, holding_service) -> None:
    handler = HoldingAnalysisJobHandler(holding_service)

    handler(fake_job_context)

    assert fake_job_context.heartbeats == [("evaluating_holdings", 20), ("persisted", 100)]
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest backend/tests/features/holdings/test_api.py backend/tests/features/holdings/test_jobs.py -q`

Expected: FAIL because contracts, routes, and handler are absent; the RED validation test also fails while
client-owned fields are accepted.

- [ ] **Step 3: Implement feature-local API contracts**

Implement `contracts.py` with these concrete Pydantic contracts:

```python
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from backend.app.features.holdings.models import HoldingAdviceItem, HoldingAnalysisResult


class HoldingAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    portfolio_id: str = Field(min_length=1)
    as_of_time: AwareDatetime


class CorrectedPositionRequest(BaseModel):
    security_id: str = Field(min_length=1)
    quantity: int = Field(ge=0)
    average_cost: Decimal = Field(ge=0)
    effective_at: AwareDatetime


class PositionCorrectionRequest(BaseModel):
    portfolio_id: str = Field(min_length=1)
    expected_version: int = Field(ge=0)
    reason: str = Field(min_length=5, max_length=200)
    positions: tuple[CorrectedPositionRequest, ...] = Field(min_length=1)


class ManualFillRequest(BaseModel):
    portfolio_id: str = Field(min_length=1)
    expected_version: int = Field(ge=0)
    security_id: str = Field(min_length=1)
    side: Literal["buy", "sell"]
    quantity: int = Field(gt=0)
    price: Decimal = Field(gt=0)
    fee: Decimal = Field(ge=0)
    executed_at: AwareDatetime


class HoldingAdviceItemResponse(BaseModel):
    security_id: str
    security_name: str
    origin: str
    strategy_book: str | None
    quantity: int
    available_to_sell: int
    average_cost: Decimal
    close: Decimal
    market_state: str
    advised_action: str
    planned_quantity: int
    pending_target_action: str | None
    effective_stop: Decimal | None
    proposed_effective_stop: Decimal | None
    reason_codes: tuple[str, ...]
    quality_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    @classmethod
    def from_domain(cls, item: HoldingAdviceItem) -> "HoldingAdviceItemResponse":
        return cls(
            security_id=item.security_id,
            security_name=item.security_name,
            origin=item.origin.value,
            strategy_book=item.strategy_book.value if item.strategy_book else None,
            quantity=item.quantity,
            available_to_sell=item.available_to_sell,
            average_cost=item.average_cost,
            close=item.close,
            market_state=item.market_state,
            advised_action=item.advised_action.value,
            planned_quantity=item.planned_quantity,
            pending_target_action=(
                item.pending_target_action.value if item.pending_target_action else None
            ),
            effective_stop=item.effective_stop,
            proposed_effective_stop=item.proposed_effective_stop,
            reason_codes=tuple(code.value for code in item.reason_codes),
            quality_codes=item.quality_codes,
            evidence_refs=item.evidence_refs,
        )


class HoldingAnalysisResponse(BaseModel):
    run_id: str
    portfolio_id: str
    as_of_time: datetime
    strategy_version: Literal["v2.12"]
    manifest_hash: str
    data_grade: str
    llm_grade: str
    items: tuple[HoldingAdviceItemResponse, ...]
    auto_trade_enabled: Literal[False] = False
    human_confirm_required: Literal[True] = True

    @classmethod
    def from_domain(cls, result: HoldingAnalysisResult) -> "HoldingAnalysisResponse":
        return cls(
            run_id=result.run_id,
            portfolio_id=result.portfolio_id,
            as_of_time=result.as_of_time,
            strategy_version="v2.12",
            manifest_hash=result.manifest_hash,
            data_grade=result.data_grade.value,
            llm_grade=result.llm_grade.value,
            items=tuple(HoldingAdviceItemResponse.from_domain(item) for item in result.items),
        )
```

The analysis request has only `portfolio_id` and timezone-aware `as_of_time`; the worker fixes strategy
version to `v2.12` and derives `llm_grade` from the PIT evidence manifest. Position responses omit personal
notes and source paths.

- [ ] **Step 4: Implement the injected job handler**

```python
# backend/app/features/holdings/jobs.py
from backend.app.features.holdings.contracts import HoldingAnalysisRequest
from backend.app.features.holdings.service import HoldingAnalysisCommand, HoldingAnalysisService
from backend.app.infrastructure.tasks.handlers import JobContext


class HoldingAnalysisJobHandler:
    def __init__(self, service: HoldingAnalysisService) -> None:
        self._service = service

    def __call__(self, context: JobContext) -> None:
        request = HoldingAnalysisRequest.model_validate(context.payload)
        context.heartbeat("evaluating_holdings", 20)
        self._service.run(
            HoldingAnalysisCommand(
                run_id=context.run_id,
                portfolio_id=request.portfolio_id,
                as_of_time=request.as_of_time,
            )
        )
        context.heartbeat("persisted", 100)
```

- [ ] **Step 5: Implement router and feature module factories**

`create_holding_router(run_submitter, repository, portfolio_reader, portfolio_writer, clock)` exposes:

```text
GET  /portfolio/positions                 -> PortfolioPositionPage
PUT  /portfolio/positions                 -> PortfolioPositionPage
POST /portfolio/fills                     -> PortfolioPositionPage
POST /holding-analyses                    -> 202 RunRef + Location
GET  /holding-analyses/latest             -> HoldingAnalysisResponse
GET  /holding-analyses/{run_id}           -> HoldingAnalysisResponse
```

The GET positions route reads the DA portfolio at the supplied `as_of_time` query value or the injected
clock; it never reads legacy files. PUT constructs one validated `CorrectionSnapshot` and calls
`PortfolioWriter.replace_positions_for_correction(snapshot, expected_version, reason)`, then returns the
resulting `PortfolioSnapshot`. It neither writes portfolio tables directly nor invents fills. A stale version returns
HTTP 409 with stable code `PORTFOLIO_VERSION_CONFLICT`. The POST analysis route forwards
`Idempotency-Key` and `submitted_at=clock.now()` to the plan-00 run service and does not perform analysis
synchronously. Missing results use common `ErrorResponse` with
`HOLDING_ANALYSIS_NOT_FOUND`.

POST fills constructs `ManualFillCommand` with the submitted actual price, fee, quantity, side, and
execution time, then calls `PortfolioWriter.record_manual_fill(command, expected_version)`. It never uses
the model price or rewrites the event as a correction.

`module.py` exports this dependency-injected factory and does not import `main.py`:

```python
@dataclass(frozen=True, slots=True)
class HoldingDependencies:
    run_submitter: RunSubmitter
    repository: HoldingAnalysisRepository
    portfolio_reader: PortfolioReader
    portfolio_writer: PortfolioWriter
    clock: Clock
    input_builder: StrategyInputBuilder
    job_handler: HoldingAnalysisJobHandler


def build_holding_feature(dependencies: HoldingDependencies) -> FeatureModule:
    router = create_holding_router(
        dependencies.run_submitter,
        dependencies.repository,
        dependencies.portfolio_reader,
        dependencies.portfolio_writer,
        dependencies.clock,
    )
    return FeatureModule(
        name="holdings",
        router=router,
        job_handlers=((RunKind.HOLDING_ANALYSIS, dependencies.job_handler),),
    )
```

Plan 06 constructs the dependencies and performs global registration.

- [ ] **Step 6: Run API and worker tests**

Run: `python -m pytest backend/tests/features/holdings/test_api.py backend/tests/features/holdings/test_jobs.py -q`

Expected: `6 passed`; analysis POST returns before the strategy service runs.

- [ ] **Step 7: Commit async boundaries**

```bash
git add backend/app/features/holdings/contracts.py \
  backend/app/features/holdings/jobs.py \
  backend/app/features/holdings/router.py \
  backend/app/features/holdings/module.py \
  backend/tests/features/holdings/test_api.py \
  backend/tests/features/holdings/test_jobs.py
git commit -m "feat(holdings): expose persistent async analysis API"
```

### Task 9: Build the holdings Web feature from generated contracts

**Files:**
- Create: `web/src/features/holdings/api.ts`
- Create: `web/src/features/holdings/viewModel.ts`
- Create: `web/src/features/holdings/HoldingCard.tsx`
- Create: `web/src/features/holdings/PositionCorrectionForm.tsx`
- Create: `web/src/features/holdings/ManualFillForm.tsx`
- Create: `web/src/features/holdings/HoldingAnalysisPage.tsx`
- Create: `web/src/features/holdings/index.tsx`
- Test: `web/src/features/holdings/HoldingAnalysisPage.test.tsx`

- [ ] **Step 1: Write failing page tests for risk priority and legacy labels**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { HoldingAnalysisPage } from "./HoldingAnalysisPage";
import { holdingApi } from "./api";

vi.mock("./api", () => ({
    holdingApi: {
        positions: vi.fn(),
        correctPositions: vi.fn(),
        recordManualFill: vi.fn(),
        latest: vi.fn(),
        submit: vi.fn(),
    },
}));

test("shows risk action, T+1 quantity, evidence, and legacy semantics", async () => {
    vi.mocked(holdingApi.positions).mockResolvedValue(positionPageFixture);
    vi.mocked(holdingApi.latest).mockResolvedValue(holdingResultFixture);
    render(
        <QueryClientProvider client={new QueryClient()}>
            <HoldingAnalysisPage />
        </QueryClientProvider>,
    );

    expect(await screen.findByText("全部退出")).toBeVisible();
    expect(screen.getByText("可卖数量：0")).toBeVisible();
    expect(screen.getByText("T+1 锁定，退出待执行")).toBeVisible();
    expect(screen.getByText("历史期初持仓，未追认策略账本")).toBeVisible();
    expect(screen.getByText("仅供人工确认，不自动下单")).toBeVisible();
});

test("submits an asynchronous analysis", async () => {
    vi.mocked(holdingApi.positions).mockResolvedValue(positionPageFixture);
    vi.mocked(holdingApi.latest).mockResolvedValue(holdingResultFixture);
    vi.mocked(holdingApi.submit).mockResolvedValue(runRefFixture);
    render(
        <QueryClientProvider client={new QueryClient()}>
            <HoldingAnalysisPage />
        </QueryClientProvider>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "分析当前持仓" }));

    await waitFor(() => expect(holdingApi.submit).toHaveBeenCalledOnce());
    expect(screen.getByRole("link", { name: "查看运行进度" })).toHaveAttribute(
        "href",
        `/runs/${runRefFixture.run_id}`,
    );
});

test("sends version and audit reason for a position correction", async () => {
    vi.mocked(holdingApi.positions).mockResolvedValue(positionPageFixture);
    vi.mocked(holdingApi.latest).mockResolvedValue(holdingResultFixture);
    vi.mocked(holdingApi.correctPositions).mockResolvedValue(correctedPositionPageFixture);
    render(
        <QueryClientProvider client={new QueryClient()}>
            <HoldingAnalysisPage />
        </QueryClientProvider>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "校正持仓" }));
    fireEvent.change(screen.getByLabelText("校正原因"), {
        target: { value: "核对券商对账单后修正数量" },
    });
    fireEvent.click(screen.getByRole("button", { name: "确认人工校正" }));

    await waitFor(() =>
        expect(holdingApi.correctPositions).toHaveBeenCalledWith(
            expect.objectContaining({ expected_version: positionPageFixture.version }),
        ),
    );
});

test("records actual fill price and fee", async () => {
    vi.mocked(holdingApi.positions).mockResolvedValue(positionPageFixture);
    vi.mocked(holdingApi.latest).mockResolvedValue(holdingResultFixture);
    vi.mocked(holdingApi.recordManualFill).mockResolvedValue(correctedPositionPageFixture);
    render(
        <QueryClientProvider client={new QueryClient()}>
            <HoldingAnalysisPage />
        </QueryClientProvider>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "记录实际成交" }));
    fireEvent.change(screen.getByLabelText("实际成交价"), {
        target: { value: "10.35" },
    });
    fireEvent.change(screen.getByLabelText("实际费用"), {
        target: { value: "5.00" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存实际成交" }));

    await waitFor(() =>
        expect(holdingApi.recordManualFill).toHaveBeenCalledWith(
            expect.objectContaining({ price: "10.35", fee: "5.00" }),
        ),
    );
});
```

- [ ] **Step 2: Run Web tests and verify failure**

Run: `npm --prefix web test -- --run src/features/holdings/HoldingAnalysisPage.test.tsx`

Expected: FAIL because the holdings Web feature is absent.

- [ ] **Step 3: Implement typed API calls using generated OpenAPI schema**

```ts
// web/src/features/holdings/api.ts
import type { components } from "@/generated/schema";
import { apiClient } from "@/shared/api/client";

export type HoldingRequest = components["schemas"]["HoldingAnalysisRequest"];
export type HoldingResult = components["schemas"]["HoldingAnalysisResponse"];
export type PositionPage = components["schemas"]["PortfolioPositionPage"];
export type PositionCorrection = components["schemas"]["PositionCorrectionRequest"];
export type ManualFill = components["schemas"]["ManualFillRequest"];
export type RunRef = components["schemas"]["RunRef"];

export const holdingApi = {
    positions: (): Promise<PositionPage> => apiClient.get("/api/v1/portfolio/positions"),
    correctPositions: (request: PositionCorrection): Promise<PositionPage> =>
        apiClient.put("/api/v1/portfolio/positions", request),
    recordManualFill: (request: ManualFill): Promise<PositionPage> =>
        apiClient.post("/api/v1/portfolio/fills", request),
    latest: (): Promise<HoldingResult> => apiClient.get("/api/v1/holding-analyses/latest"),
    submit: (request: HoldingRequest, idempotencyKey: string): Promise<RunRef> =>
        apiClient.post("/api/v1/holding-analyses", request, {
            headers: { "Idempotency-Key": idempotencyKey },
        }),
};
```

- [ ] **Step 4: Implement view-model labels and accessible holding cards**

`viewModel.ts` maps stable enums to Chinese labels only. `HoldingCard.tsx` displays position origin,
strategy book, quantity, T+1 available quantity, average cost, close, effective stop, deterministic action,
proposed stop, P/F/R/T/V/S, percentile rank, R multiple, planned quantity, reason codes, quality issues, and
evidence. A `pending_exit` item must display its target
action and must not claim a fill. A legacy item with no strategy book displays “历史期初持仓，未追认策略
账本”. `PositionCorrectionForm.tsx` requires a reason, includes the loaded portfolio version, and labels the
operation “人工校正，不是历史成交”. It refreshes positions after success and displays 409 version conflicts
without retrying over newer state. `ManualFillForm.tsx` requires actual execution time, side, quantity, price,
fee, and loaded portfolio version; its mutation calls the fill endpoint and never reuses an advised price.
`HoldingAnalysisPage.tsx` includes explicit loading, empty, not-yet-run, and error states, a research
grade warning, a run-center link after submit, and “仅供人工确认，不自动下单”.

`index.tsx` exports without global registration:

```tsx
import type { FeatureDefinition } from "@/app/featureRegistry";
import { HoldingAnalysisPage } from "./HoldingAnalysisPage";

export const holdingFeature: FeatureDefinition = {
    id: "holdings",
    path: "/holdings",
    label: "持仓分析",
    element: <HoldingAnalysisPage />,
};
```

- [ ] **Step 5: Run Web unit and type tests**

Run: `npm --prefix web test -- --run src/features/holdings/HoldingAnalysisPage.test.tsx`

Expected: `4 passed`.

Run: `npm --prefix web run typecheck`

Expected: TypeScript exits 0 and no backend DTO is handwritten.

- [ ] **Step 6: Commit the Web feature**

```bash
git add web/src/features/holdings
git commit -m "feat(holdings): visualize risk-first portfolio advice"
```

### Task 10: Verify holding invariants and prepare integration handoff

**Files:**
- Create: `backend/tests/features/holdings/test_invariants.py`
- Create: `backend/app/features/holdings/INTEGRATION.md`

- [ ] **Step 1: Add invariants for ledger immutability and deterministic replay**

```python
from dataclasses import asdict
from pathlib import Path

from backend.tests.features.holdings.factories import holding_command


def test_analysis_does_not_mutate_portfolio_lots(holding_service_fixture) -> None:
    lot = holding_service_fixture.portfolio.lots[0]
    before = asdict(lot)

    holding_service_fixture.run(holding_command(run_id="run-one"))

    assert asdict(lot) == before


def test_same_manifest_and_portfolio_produce_identical_advice(
    holding_service_fixture,
) -> None:
    first = holding_service_fixture.run(holding_command(run_id="run-one"))
    second = holding_service_fixture.run(holding_command(run_id="run-two"))

    assert first.items == second.items


def test_feature_has_no_markdown_parser_or_la_runtime_dependency() -> None:
    files = Path("backend/app/features/holdings").glob("*.py")
    source = "\n".join(path.read_text(encoding="utf-8") for path in files)

    assert "parse_markdown" not in source
    assert "/Users/bujiatang/workspace/LA" not in source
    assert "auto_trade_enabled=True" not in source
```

- [ ] **Step 2: Write the exact plan-06 handoff**

`INTEGRATION.md` must require the coordinator to:

1. import feature ORM metadata and generate holding tables in the plan-06 migration;
2. construct `HoldingAnalysisService` with PIT, portfolio reader, `StrategyInputBuilder`,
   `V212StrategyEngine`, and repository;
3. inject `PortfolioWriter` into the GET/PUT portfolio router and verify optimistic version conflicts;
4. call `build_holding_feature()` in the global feature registry;
5. export OpenAPI and regenerate `web/src/generated/schema.d.ts` twice to prove a clean second run;
6. register `holdingFeature` in global navigation;
7. run E2E for legacy display, audited correction, actual fill, async analysis, persisted result, and restart;
8. confirm no log contains position notes, source paths, API secrets, or raw LLM input/output.

- [ ] **Step 3: Run full feature verification**

Run: `python -m pytest backend/tests/features/holdings -q`

Expected: all holdings tests pass.

Run: `python -m ruff check backend/app/features/holdings backend/tests/features/holdings`

Expected: Ruff exits 0.

Run: `python -m mypy backend/app/features/holdings`

Expected: all commands exit 0; every function is typed and every line is at most 100 characters.

Run: `npm --prefix web test -- --run src/features/holdings`

Expected: Vitest exits 0.

Run: `npm --prefix web run typecheck`

Expected: TypeScript exits 0.

Run: `npm --prefix web run build`

Expected: the production build exits 0.

Run: `rg -n "(/Users/bujiatang/workspace/LA|parse_markdown|auto_trade_enabled=True|llm_raw_output.*(action|quantity))" backend/app/features/holdings web/src/features/holdings`

Expected: no matches.

- [ ] **Step 4: Commit invariants and handoff**

```bash
git add backend/tests/features/holdings/test_invariants.py \
  backend/app/features/holdings/INTEGRATION.md
git commit -m "test(holdings): protect ledger and advisory invariants"
```

The branch is ready for review when it contains ten small Conventional Commits, all verification commands
pass, and it changes no global entry point, generated contract, shared strategy formula, or migration file.
