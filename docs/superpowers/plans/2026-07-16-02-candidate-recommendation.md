# Candidate Recommendation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the V2.12 candidate-recommendation vertical slice that returns persisted, structured executable/watchlist/excluded results and renders them in Web without allowing LLM output to create a trade action.

**Architecture:** The feature reads one point-in-time snapshot and one portfolio snapshot, delegates all shared P/F/R/T/V/S, market-regime, position-sizing, and portfolio-constraint mathematics to the frozen `V212StrategyEngine`, and owns only the candidate lifecycle state machine and feature orchestration. FastAPI, the worker, Markdown, and React consume the same persisted `CandidateRecommendationResult`; none parses Markdown or treats LLM prose as an order.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2, PostgreSQL, pytest, React 18, TypeScript, TanStack Query, Vitest, React Testing Library

---

## Dependencies, ownership, and frozen contracts

Complete `00-foundation-contracts` and `01-pit-and-legacy` before starting this plan. This plan owns only:

- `backend/app/features/candidates/**`;
- `backend/tests/features/candidates/**`;
- `web/src/features/candidates/**`.

It must not modify `backend/app/main.py`, `backend/app/core/**`, `backend/app/ports/**`,
`backend/app/contracts/**`, the Alembic revision chain, `contracts/openapi.json`,
`web/src/generated/**`, `web/src/app/featureRegistry.ts`, global routes, or global styles. The integration
agent performs those edits in plan 06.

The implementation imports these frozen dependencies:

```python
from backend.app.contracts.grades import DataGrade, LlmGrade
from backend.app.contracts.runs import Page, RunKind, RunRef
from backend.app.core.clock import Clock
from backend.app.core.market.strategy_inputs import StrategyInputBuilder
from backend.app.core.portfolio.models import PortfolioSnapshot
from backend.app.core.strategy.reason_codes import ReasonCode
from backend.app.core.strategy.service import V212StrategyEngine
from backend.app.core.strategy.types import StrategyEvaluation
from backend.app.infrastructure.tasks.handlers import JobContext, JobHandler
from backend.app.ports.point_in_time import PointInTimeWarehouse, SnapshotScope
from backend.app.ports.portfolio import PortfolioReader
from backend.app.ports.runs import RunSubmitter
```

`V212StrategyEngine.evaluate()` is the only source of P/F/R/T/V/S, market regime, risk-sized quantity,
initial stop, and portfolio constraint decisions. If the frozen names differ when plan 00 is merged, adapt
imports and field mapping once in `strategy_projection.py`; do not reproduce a formula inside this feature.

The feature requires `StrategyEvaluation.securities` entries to expose these already-determined facts:

```text
security_id, security_name, industry_id, theme_ids, strategy_book,
factors(p, f, r, t, v, s, percentile_rank), hard_filter_passed,
policy_sources_available, llm_factor_valid, financial_light, policy_direction,
breakout_confirmed, pullback_confirmed, strengthened_confirmed,
days_since_breakout, held, constraint.allowed, constraint.planned_quantity,
constraint.initial_stop, constraint.reason_codes, quality_codes, evidence_refs
```

`PointInTimeSnapshot` also exposes `llm_evidence_manifest` with `grade: LlmGrade`, `valid: bool`, and
`completed_at`. The feature derives the result grade from this manifest; no request field can override it.

The feature repository declares SQLAlchemy metadata, but this plan does not create a migration. Plan 06
generates the migration from the merged models and registers `build_candidate_feature()` in the global app.

## File map

| File | Responsibility |
| --- | --- |
| `backend/app/features/candidates/models.py` | Immutable feature input, state, item, and result models |
| `backend/app/features/candidates/state_machine.py` | Candidate-only lifecycle transitions and expiry |
| `backend/app/features/candidates/strategy_projection.py` | One mapping boundary from shared strategy output |
| `backend/app/features/candidates/quality.py` | Derives and validates LLM grade from PIT evidence manifest |
| `backend/app/features/candidates/repository.py` | Repository protocol and SQLAlchemy implementation |
| `backend/app/features/candidates/service.py` | Point-in-time orchestration and fail-closed result creation |
| `backend/app/features/candidates/markdown.py` | One-way Markdown projection |
| `backend/app/features/candidates/contracts.py` | Pydantic request/response DTOs local to the feature |
| `backend/app/features/candidates/router.py` | Feature router factory; submit and result queries |
| `backend/app/features/candidates/jobs.py` | Dependency-injected worker handler |
| `backend/app/features/candidates/module.py` | Feature module factory for plan 06 registration |
| `web/src/features/candidates/api.ts` | Calls shared HTTP client using generated OpenAPI types |
| `web/src/features/candidates/viewModel.ts` | Stable labels and presentation-only grouping |
| `web/src/features/candidates/CandidatePage.tsx` | Submit, progress link, latest result, and failure states |
| `web/src/features/candidates/CandidateTable.tsx` | Structured result table and evidence disclosure |
| `web/src/features/candidates/index.tsx` | Exports the feature definition for global registration |

### Task 1: Define immutable candidate result models

**Files:**
- Create: `backend/app/features/candidates/__init__.py`
- Create: `backend/app/features/candidates/models.py`
- Test: `backend/tests/features/candidates/test_models.py`

- [ ] **Step 1: Write the failing model test**

```python
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from backend.app.contracts.grades import DataGrade, LlmGrade
from backend.app.core.portfolio.models import StrategyBook
from backend.app.core.strategy.reason_codes import ReasonCode
from backend.app.features.candidates.models import (
    CandidateBucket,
    CandidateFactors,
    CandidateItem,
    CandidateRecommendationResult,
    CandidateState,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_result_is_structured_and_always_requires_human_confirmation() -> None:
    item = CandidateItem(
        security_id="000001.SZ",
        security_name="平安银行",
        bucket=CandidateBucket.EXECUTABLE,
        state=CandidateState.PENDING_EXECUTION,
        strategy_book=StrategyBook.CORE,
        factors=CandidateFactors(
            p=Decimal("70"), f=Decimal("75"), r=Decimal("80"),
            t=Decimal("75"), v=Decimal("65"), s=Decimal("74.75"),
            percentile_rank=Decimal("0.08"),
        ),
        planned_quantity=100,
        initial_stop=Decimal("9.50"),
        trigger_condition="下一交易日开盘未高开超过3%且可成交",
        invalidation_condition="市场转弱、红灯或约束不再满足",
        reason_codes=(ReasonCode.ELIGIBLE,),
        quality_codes=(),
        evidence_refs=("sha256:policy-1",),
    )
    result = CandidateRecommendationResult(
        run_id="run-1",
        as_of_time=datetime(2026, 7, 16, 15, 30, tzinfo=SHANGHAI),
        strategy_version="v2.12",
        manifest_hash="sha256:manifest",
        data_grade=DataGrade.RESEARCH,
        llm_grade=LlmGrade.RECONSTRUCTED,
        market_state="strong",
        market_confidence="normal",
        quality_codes=(),
        items=(item,),
    )

    assert result.auto_trade_enabled is False
    assert result.human_confirm_required is True
    assert result.executable == (item,)
    assert result.watchlist == ()
    assert result.excluded == ()
```

- [ ] **Step 2: Run the test and verify the missing module failure**

Run: `python -m pytest backend/tests/features/candidates/test_models.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'backend.app.features.candidates'`.

- [ ] **Step 3: Implement the immutable models**

```python
# backend/app/features/candidates/models.py
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from backend.app.contracts.grades import DataGrade, LlmGrade
from backend.app.core.portfolio.models import StrategyBook
from backend.app.core.strategy.reason_codes import ReasonCode


class CandidateBucket(StrEnum):
    EXECUTABLE = "executable"
    WATCHLIST = "watchlist"
    EXCLUDED = "excluded"


class CandidateState(StrEnum):
    UNSELECTED = "unselected"
    SELECTED = "selected"
    BREAKOUT = "breakout"
    PULLBACK = "pullback"
    STRENGTHENED = "strengthened"
    PENDING_EXECUTION = "pending_execution"
    HELD = "held"


@dataclass(frozen=True, slots=True)
class CandidateFactors:
    p: Decimal
    f: Decimal
    r: Decimal
    t: Decimal
    v: Decimal
    s: Decimal
    percentile_rank: Decimal


@dataclass(frozen=True, slots=True)
class CandidateItem:
    security_id: str
    security_name: str
    bucket: CandidateBucket
    state: CandidateState
    strategy_book: StrategyBook | None
    factors: CandidateFactors
    planned_quantity: int
    initial_stop: Decimal | None
    trigger_condition: str
    invalidation_condition: str
    reason_codes: tuple[ReasonCode, ...]
    quality_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateRecommendationResult:
    run_id: str
    as_of_time: datetime
    strategy_version: Literal["v2.12"]
    manifest_hash: str
    data_grade: DataGrade
    llm_grade: LlmGrade
    market_state: str
    market_confidence: str
    quality_codes: tuple[str, ...]
    items: tuple[CandidateItem, ...]
    auto_trade_enabled: bool = False
    human_confirm_required: bool = True

    @property
    def executable(self) -> tuple[CandidateItem, ...]:
        return tuple(item for item in self.items if item.bucket is CandidateBucket.EXECUTABLE)

    @property
    def watchlist(self) -> tuple[CandidateItem, ...]:
        return tuple(item for item in self.items if item.bucket is CandidateBucket.WATCHLIST)

    @property
    def excluded(self) -> tuple[CandidateItem, ...]:
        return tuple(item for item in self.items if item.bucket is CandidateBucket.EXCLUDED)
```

Create an empty `backend/app/features/candidates/__init__.py` so imports remain explicit.

- [ ] **Step 4: Run the model test**

Run: `python -m pytest backend/tests/features/candidates/test_models.py -q`

Expected: `1 passed`.

- [ ] **Step 5: Commit the models**

```bash
git add backend/app/features/candidates/__init__.py \
  backend/app/features/candidates/models.py \
  backend/tests/features/candidates/test_models.py
git commit -m "feat(candidates): establish auditable result model"
```

### Task 2: Implement the candidate lifecycle state machine

**Files:**
- Create: `backend/app/features/candidates/state_machine.py`
- Test: `backend/tests/features/candidates/test_state_machine.py`

- [ ] **Step 1: Write table-driven failing tests for progression, expiry, and fail-closed reset**

```python
import pytest

from backend.app.features.candidates.models import CandidateState
from backend.app.features.candidates.state_machine import CandidateFacts, transition


@pytest.mark.parametrize(
    ("previous", "facts", "expected"),
    [
        (CandidateState.UNSELECTED, CandidateFacts(eligible=True), CandidateState.SELECTED),
        (
            CandidateState.SELECTED,
            CandidateFacts(eligible=True, breakout_confirmed=True),
            CandidateState.BREAKOUT,
        ),
        (
            CandidateState.BREAKOUT,
            CandidateFacts(eligible=True, pullback_confirmed=True, days_since_breakout=3),
            CandidateState.PULLBACK,
        ),
        (
            CandidateState.PULLBACK,
            CandidateFacts(eligible=True, strengthened_confirmed=True),
            CandidateState.STRENGTHENED,
        ),
        (
            CandidateState.STRENGTHENED,
            CandidateFacts(eligible=True, execution_allowed=True),
            CandidateState.PENDING_EXECUTION,
        ),
        (
            CandidateState.BREAKOUT,
            CandidateFacts(eligible=True, days_since_breakout=6),
            CandidateState.UNSELECTED,
        ),
        (
            CandidateState.PULLBACK,
            CandidateFacts(eligible=False, red_light=True),
            CandidateState.UNSELECTED,
        ),
        (
            CandidateState.PENDING_EXECUTION,
            CandidateFacts(eligible=True, held=True),
            CandidateState.HELD,
        ),
    ],
)
def test_candidate_transition(
    previous: CandidateState,
    facts: CandidateFacts,
    expected: CandidateState,
) -> None:
    assert transition(previous, facts) is expected
```

- [ ] **Step 2: Run the state-machine tests and verify failure**

Run: `python -m pytest backend/tests/features/candidates/test_state_machine.py -q`

Expected: FAIL because `state_machine.py` does not exist.

- [ ] **Step 3: Implement the deterministic transition function**

```python
# backend/app/features/candidates/state_machine.py
from dataclasses import dataclass

from backend.app.features.candidates.models import CandidateState


@dataclass(frozen=True, slots=True)
class CandidateFacts:
    eligible: bool
    breakout_confirmed: bool = False
    pullback_confirmed: bool = False
    strengthened_confirmed: bool = False
    execution_allowed: bool = False
    days_since_breakout: int = 0
    red_light: bool = False
    market_weak: bool = False
    held: bool = False


def transition(previous: CandidateState, facts: CandidateFacts) -> CandidateState:
    if facts.held:
        return CandidateState.HELD
    if not facts.eligible or facts.red_light or facts.market_weak:
        return CandidateState.UNSELECTED
    if previous is CandidateState.BREAKOUT and facts.days_since_breakout > 5:
        return CandidateState.UNSELECTED
    if previous is CandidateState.STRENGTHENED and facts.execution_allowed:
        return CandidateState.PENDING_EXECUTION
    if previous is CandidateState.PULLBACK and facts.strengthened_confirmed:
        return CandidateState.STRENGTHENED
    if previous is CandidateState.BREAKOUT and facts.pullback_confirmed:
        return CandidateState.PULLBACK
    if previous is CandidateState.SELECTED and facts.breakout_confirmed:
        return CandidateState.BREAKOUT
    if previous is CandidateState.UNSELECTED:
        return CandidateState.SELECTED
    return previous
```

This file deliberately consumes booleans calculated by the shared strategy core. It must not calculate
breakout prices, moving averages, ATR, factor thresholds, risk quantity, or concentration limits.

- [ ] **Step 4: Run the state-machine tests**

Run: `python -m pytest backend/tests/features/candidates/test_state_machine.py -q`

Expected: `8 passed`.

- [ ] **Step 5: Commit the lifecycle state machine**

```bash
git add backend/app/features/candidates/state_machine.py \
  backend/tests/features/candidates/test_state_machine.py
git commit -m "feat(candidates): persist deterministic signal lifecycle"
```

### Task 3: Map shared strategy evaluations into candidate items

**Files:**
- Create: `backend/app/features/candidates/strategy_projection.py`
- Test: `backend/tests/features/candidates/test_strategy_projection.py`

- [ ] **Step 1: Write the failing projection tests**

```python
from backend.app.features.candidates.models import CandidateBucket, CandidateState
from backend.app.features.candidates.strategy_projection import project_security
from backend.tests.factories.strategy import strategy_security_evaluation


def test_only_rule_approved_pending_execution_is_executable() -> None:
    evaluation = strategy_security_evaluation(
        policy_sources_available=True,
        llm_factor_valid=True,
        constraint_allowed=True,
        planned_quantity=100,
        strengthened_confirmed=True,
    )

    item = project_security(evaluation, CandidateState.STRENGTHENED)

    assert item.state is CandidateState.PENDING_EXECUTION
    assert item.bucket is CandidateBucket.EXECUTABLE
    assert item.planned_quantity == 100


def test_invalid_llm_factor_cannot_create_an_executable_candidate() -> None:
    evaluation = strategy_security_evaluation(
        policy_sources_available=True,
        llm_factor_valid=False,
        constraint_allowed=True,
        planned_quantity=100,
        strengthened_confirmed=True,
    )

    item = project_security(evaluation, CandidateState.STRENGTHENED)

    assert item.bucket is CandidateBucket.EXCLUDED
    assert item.planned_quantity == 0


def test_valid_llm_factor_cannot_override_a_rule_constraint_denial() -> None:
    evaluation = strategy_security_evaluation(
        llm_factor_valid=True,
        constraint_allowed=False,
        planned_quantity=0,
        strengthened_confirmed=True,
    )

    item = project_security(evaluation, CandidateState.STRENGTHENED)

    assert item.bucket is not CandidateBucket.EXECUTABLE
    assert item.planned_quantity == 0
```

Use the plan-00 test factory `backend/tests/factories/strategy.py`; extend only that factory through an
integration-agent contract request if a newly required frozen field is absent.

- [ ] **Step 2: Run the projection tests and verify failure**

Run: `python -m pytest backend/tests/features/candidates/test_strategy_projection.py -q`

Expected: FAIL because `project_security` is not defined.

- [ ] **Step 3: Implement the single shared-core mapping boundary**

```python
# backend/app/features/candidates/strategy_projection.py
from backend.app.core.strategy.reason_codes import ReasonCode
from backend.app.core.strategy.types import SecurityEvaluation
from backend.app.features.candidates.models import (
    CandidateBucket,
    CandidateFactors,
    CandidateItem,
    CandidateState,
)
from backend.app.features.candidates.state_machine import CandidateFacts, transition


def project_security(
    evaluation: SecurityEvaluation,
    previous_state: CandidateState,
) -> CandidateItem:
    red_light = (
        evaluation.financial_light == "red"
        or evaluation.policy_direction == "restrictive"
    )
    text_factors_valid = (
        evaluation.policy_sources_available and evaluation.llm_factor_valid
    )
    eligible = evaluation.hard_filter_passed and text_factors_valid
    facts = CandidateFacts(
        eligible=eligible,
        breakout_confirmed=evaluation.breakout_confirmed,
        pullback_confirmed=evaluation.pullback_confirmed,
        strengthened_confirmed=evaluation.strengthened_confirmed,
        execution_allowed=evaluation.constraint.allowed,
        days_since_breakout=evaluation.days_since_breakout,
        red_light=red_light,
        market_weak=evaluation.market_state == "weak",
        held=evaluation.held,
    )
    state = transition(previous_state, facts)
    executable = (
        state is CandidateState.PENDING_EXECUTION
        and evaluation.constraint.allowed
        and text_factors_valid
        and not red_light
    )
    if executable:
        bucket = CandidateBucket.EXECUTABLE
    elif state in {
        CandidateState.SELECTED,
        CandidateState.BREAKOUT,
        CandidateState.PULLBACK,
        CandidateState.STRENGTHENED,
    }:
        bucket = CandidateBucket.WATCHLIST
    else:
        bucket = CandidateBucket.EXCLUDED
    quantity = evaluation.constraint.planned_quantity if executable else 0
    reason_codes = evaluation.constraint.reason_codes
    if not text_factors_valid:
        reason_codes = (*reason_codes, ReasonCode.LLM_FACTOR_INVALID)
    return CandidateItem(
        security_id=evaluation.security_id,
        security_name=evaluation.security_name,
        bucket=bucket,
        state=state,
        strategy_book=evaluation.strategy_book,
        factors=CandidateFactors(
            p=evaluation.factors.p,
            f=evaluation.factors.f,
            r=evaluation.factors.r,
            t=evaluation.factors.t,
            v=evaluation.factors.v,
            s=evaluation.factors.s,
            percentile_rank=evaluation.factors.percentile_rank,
        ),
        planned_quantity=quantity,
        initial_stop=evaluation.constraint.initial_stop if executable else None,
        trigger_condition="下一交易日开盘未高开超过3%且可成交",
        invalidation_condition="市场转弱、红灯、信号过期或组合约束不再满足",
        reason_codes=reason_codes,
        quality_codes=evaluation.quality_codes,
        evidence_refs=evaluation.evidence_refs,
    )
```

The `llm_raw_output` field is intentionally never read. LLM policy and financial text affects validated
P/F facts only; quantity and action come from `evaluation.constraint` and the feature state machine.

- [ ] **Step 4: Run the projection tests**

Run: `python -m pytest backend/tests/features/candidates/test_strategy_projection.py -q`

Expected: `3 passed`.

- [ ] **Step 5: Commit the strategy projection**

```bash
git add backend/app/features/candidates/strategy_projection.py \
  backend/tests/features/candidates/test_strategy_projection.py
git commit -m "feat(candidates): project rule-owned executable decisions"
```

### Task 4: Persist candidate results and lifecycle state

**Files:**
- Create: `backend/app/features/candidates/repository.py`
- Create: `backend/tests/features/candidates/factories.py`
- Create: `backend/tests/features/candidates/fakes.py`
- Test: `backend/tests/features/candidates/test_repository.py`

- [ ] **Step 1: Write a failing PostgreSQL repository round-trip test**

```python
from backend.app.features.candidates.repository import SqlCandidateRepository
from backend.tests.features.candidates.factories import candidate_result
from sqlalchemy.orm import Session, sessionmaker


def test_repository_saves_result_and_latest_state(session: Session) -> None:
    repository = SqlCandidateRepository(session_factory)
    result = candidate_result(run_id="run-2", security_id="000001.SZ")

    repository.save(result)

    assert repository.get("run-2") == result
    assert repository.latest() == result
    assert repository.states_before(result.as_of_time) == {
        "000001.SZ": result.items[0].state
    }
```

- [ ] **Step 2: Run the repository test and verify failure**

Run: `python -m pytest backend/tests/features/candidates/test_repository.py -q`

Expected: FAIL because `SqlCandidateRepository` does not exist.

- [ ] **Step 3: Implement the repository protocol, ORM rows, and lossless JSON codec**

Create `CandidateRepository` with these typed synchronous methods:

```python
class CandidateRepository(Protocol):
    def save(self, result: CandidateRecommendationResult) -> None:
        raise NotImplementedError

    def get(self, run_id: str) -> CandidateRecommendationResult | None:
        raise NotImplementedError

    def latest(self) -> CandidateRecommendationResult | None:
        raise NotImplementedError

    def states_before(self, as_of_time: datetime) -> dict[str, CandidateState]:
        raise NotImplementedError
```

Define feature-local SQLAlchemy models `CandidateResultRow`, `CandidateItemRow`, and
`CandidateStateEventRow` for tables `candidate_results`, `candidate_items`, and
`candidate_state_events`. Store decimals as strings in JSON, enum values as stable English strings,
timestamps as timezone-aware values, and items sorted by `(bucket, factors.percentile_rank, security_id)`.
Use SQLAlchemy `insert()`, `select()`, and bound values only; do not interpolate SQL text. `save()` must use
the run id as its idempotency key: a retry either observes the same manifest hash and returns successfully,
or raises `CandidateResultConflict` when the hash differs.

The complete codec must round-trip every field declared in Task 1. Keep the row declarations and codec in
this feature file so the integration agent can import their metadata when generating the plan-06 migration.

The concrete repository constructor is synchronous and session-injected:

```python
from sqlalchemy.orm import Session


class SqlCandidateRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, result: CandidateRecommendationResult) -> None:
        with self._session_factory.begin() as session:
            self._save_idempotently(session, result)

    def get(self, run_id: str) -> CandidateRecommendationResult | None:
        with self._session_factory() as session:
            return self._decode_result(session.get(CandidateResultRow, run_id))

    def latest(self) -> CandidateRecommendationResult | None:
        with self._session_factory() as session:
            return self._decode_result(self._latest_row(session))
```

`_save_idempotently`, `_latest_row`, and `_decode_result` must use the declared SQLAlchemy rows and bound
parameters; they cannot read files or call the LA project.

- [ ] **Step 4: Run repository tests against temporary PostgreSQL**

Run: `python -m pytest backend/tests/features/candidates/test_repository.py -q`

Expected: `1 passed` and no SQLite fallback.

- [ ] **Step 5: Commit persistence**

```bash
git add backend/app/features/candidates/repository.py \
  backend/tests/features/candidates/factories.py \
  backend/tests/features/candidates/fakes.py \
  backend/tests/features/candidates/test_repository.py
git commit -m "feat(candidates): persist results and signal state idempotently"
```

### Task 5: Orchestrate one replayable candidate recommendation

**Files:**
- Create: `backend/app/features/candidates/service.py`
- Test: `backend/tests/features/candidates/test_service.py`

- [ ] **Step 1: Write failing orchestration and fail-closed tests**

```python
from backend.app.features.candidates.models import CandidateBucket
from backend.app.features.candidates.service import CandidateService
from backend.app.ports.point_in_time import SnapshotScope
from backend.tests.features.candidates.factories import candidate_command
from backend.tests.features.candidates.fakes import FakeCandidateRepository
from backend.tests.fakes.pit import FakePointInTimeWarehouse
from backend.tests.fakes.portfolio import FakePortfolioReader
from backend.tests.fakes.strategy import FakeStrategyDecisionPort
from backend.tests.fakes.strategy_inputs import FakeStrategyInputBuilder


def test_service_uses_the_same_as_of_for_all_inputs() -> None:
    command = candidate_command(run_id="run-3")
    warehouse = FakePointInTimeWarehouse()
    portfolios = FakePortfolioReader()
    input_builder = FakeStrategyInputBuilder()
    strategy = FakeStrategyDecisionPort.with_executable_security()
    repository = FakeCandidateRepository()
    service = CandidateService(
        warehouse,
        portfolios,
        input_builder,
        strategy,
        repository,
    )

    result = service.run(command)

    assert warehouse.requests == [
        (command.as_of_time, SnapshotScope.candidate_recommendation())
    ]
    assert portfolios.requests == [(command.portfolio_id, command.as_of_time)]
    assert input_builder.requests == [
        (warehouse.snapshot_value, portfolios.snapshot_value, command.strategy_version)
    ]
    assert strategy.requests == [input_builder.prepared_value]
    assert result.manifest_hash == warehouse.snapshot_value.manifest_hash
    assert repository.saved == [result]


def test_policy_source_failure_closes_all_new_positions() -> None:
    command = candidate_command(run_id="run-4")
    strategy = FakeStrategyDecisionPort.with_executable_security(
        policy_sources_available=False,
    )
    service = CandidateService(
        FakePointInTimeWarehouse(),
        FakePortfolioReader(),
        FakeStrategyInputBuilder(),
        strategy,
        FakeCandidateRepository(),
    )

    result = service.run(command)

    assert result.executable == ()
    assert all(item.bucket is CandidateBucket.EXCLUDED for item in result.items)
```

- [ ] **Step 2: Run service tests and verify failure**

Run: `python -m pytest backend/tests/features/candidates/test_service.py -q`

Expected: FAIL because `CandidateService` does not exist.

- [ ] **Step 3: Implement the application service**

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

An invalid manifest yields `LlmGrade.NOT_USED`; the shared strategy still marks text factors invalid and
prevents executable new positions. A future-dated manifest raises `InvalidLlmEvidence`; no client value can
override either result.

```python
# backend/app/features/candidates/service.py
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from backend.app.core.market.strategy_inputs import StrategyInputBuilder
from backend.app.features.candidates.models import CandidateRecommendationResult, CandidateState
from backend.app.features.candidates.quality import derive_llm_grade
from backend.app.features.candidates.repository import CandidateRepository
from backend.app.features.candidates.strategy_projection import project_security
from backend.app.ports.point_in_time import PointInTimeWarehouse, SnapshotScope
from backend.app.ports.portfolio import PortfolioReader
from backend.app.ports.strategy import StrategyDecisionPort


@dataclass(frozen=True, slots=True)
class CandidateRecommendationCommand:
    run_id: str
    portfolio_id: str
    as_of_time: datetime
    strategy_version: Literal["v2.12"] = "v2.12"


class CandidateService:
    def __init__(
        self,
        warehouse: PointInTimeWarehouse,
        portfolios: PortfolioReader,
        input_builder: StrategyInputBuilder,
        strategy: StrategyDecisionPort,
        repository: CandidateRepository,
    ) -> None:
        self._warehouse = warehouse
        self._portfolios = portfolios
        self._input_builder = input_builder
        self._strategy = strategy
        self._repository = repository

    def run(
        self,
        command: CandidateRecommendationCommand,
    ) -> CandidateRecommendationResult:
        snapshot = self._warehouse.snapshot(
            as_of_time=command.as_of_time,
            scope=SnapshotScope.candidate_recommendation(),
        )
        portfolio = self._portfolios.snapshot(
            portfolio_id=command.portfolio_id,
            as_of_time=command.as_of_time,
        )
        previous = self._repository.states_before(command.as_of_time)
        prepared = self._input_builder.build(
            snapshot=snapshot,
            portfolio=portfolio,
            strategy_version=command.strategy_version,
        )
        evaluation = self._strategy.evaluate(prepared)
        llm_grade = derive_llm_grade(snapshot)
        items = tuple(
            sorted(
                (
                    project_security(
                        security,
                        previous.get(security.security_id, CandidateState.UNSELECTED),
                    )
                    for security in evaluation.securities
                ),
                key=lambda item: (
                    item.bucket.value,
                    item.factors.percentile_rank,
                    item.security_id,
                ),
            )
        )
        result = CandidateRecommendationResult(
            run_id=command.run_id,
            as_of_time=command.as_of_time,
            strategy_version=command.strategy_version,
            manifest_hash=snapshot.manifest_hash,
            data_grade=snapshot.data_grade,
            llm_grade=llm_grade,
            market_state=evaluation.market_state,
            market_confidence=evaluation.market_confidence,
            quality_codes=tuple(issue.code for issue in snapshot.quality.issues),
            items=items,
        )
        self._repository.save(result)
        return result
```

The implementation must assert `snapshot.as_of_time == command.as_of_time`, then verify the builder output
contains the same as-of time, strategy version, and manifest hash before evaluation. It must never assemble
`MarketRegimeInput`, `PortfolioView`, or `SecurityEvaluationInput` inside the feature, read a provider
directly, or read `/Users/bujiatang/workspace/LA`.

- [ ] **Step 4: Run service tests**

Run: `python -m pytest backend/tests/features/candidates/test_service.py -q`

Expected: `2 passed`.

- [ ] **Step 5: Commit the replayable use case**

```bash
git add backend/app/features/candidates/service.py \
  backend/tests/features/candidates/test_service.py
git commit -m "feat(candidates): orchestrate one point-in-time recommendation"
```

### Task 6: Add a one-way Markdown projection

**Files:**
- Create: `backend/app/features/candidates/markdown.py`
- Test: `backend/tests/features/candidates/test_markdown.py`

- [ ] **Step 1: Write a failing projection test**

```python
from backend.app.features.candidates.markdown import render_candidate_markdown
from backend.tests.features.candidates.factories import candidate_result


def test_markdown_is_a_projection_with_a_research_warning() -> None:
    result = candidate_result(run_id="run-5", data_grade="research")

    markdown = render_candidate_markdown(result)

    assert "研究级数据" in markdown
    assert "仅供人工确认，不自动下单" in markdown
    assert "000001.SZ" in markdown
    assert result.manifest_hash in markdown
```

- [ ] **Step 2: Run the projection test and verify failure**

Run: `python -m pytest backend/tests/features/candidates/test_markdown.py -q`

Expected: FAIL because `render_candidate_markdown` is missing.

- [ ] **Step 3: Implement rendering from the structured result only**

```python
# backend/app/features/candidates/markdown.py
from backend.app.contracts.grades import DataGrade
from backend.app.features.candidates.models import CandidateRecommendationResult


def render_candidate_markdown(result: CandidateRecommendationResult) -> str:
    warning = "研究级数据，不代表正式历史验证" if result.data_grade is DataGrade.RESEARCH else "PIT 数据已验证"
    lines = [
        "# 候选推荐",
        "",
        f"> {warning}；仅供人工确认，不自动下单。",
        "",
        f"- 策略版本：{result.strategy_version}",
        f"- as_of_time：{result.as_of_time.isoformat()}",
        f"- 输入 manifest：{result.manifest_hash}",
        f"- 市场状态：{result.market_state}（{result.market_confidence}）",
        "",
    ]
    for title, items in (
        ("可执行", result.executable),
        ("观察", result.watchlist),
        ("排除", result.excluded),
    ):
        lines.extend((f"## {title}", ""))
        if not items:
            lines.extend(("无", ""))
            continue
        for item in items:
            reasons = ", ".join(code.value for code in item.reason_codes)
            lines.extend(
                (
                    f"### {item.security_id} {item.security_name}",
                    "",
                    f"- 状态：{item.state.value}",
                    f"- S / 排名：{item.factors.s} / {item.factors.percentile_rank}",
                    f"- 规则计划数量：{item.planned_quantity}",
                    f"- 原因码：{reasons}",
                    "",
                )
            )
    return "\n".join(lines)
```

No parser from this Markdown back into domain or API objects may be added.

- [ ] **Step 4: Run the Markdown test**

Run: `python -m pytest backend/tests/features/candidates/test_markdown.py -q`

Expected: `1 passed`.

- [ ] **Step 5: Commit the projection**

```bash
git add backend/app/features/candidates/markdown.py \
  backend/tests/features/candidates/test_markdown.py
git commit -m "feat(candidates): render advice from structured results"
```

### Task 7: Expose feature-local worker and API factories

**Files:**
- Create: `backend/app/features/candidates/contracts.py`
- Create: `backend/app/features/candidates/jobs.py`
- Create: `backend/app/features/candidates/router.py`
- Create: `backend/app/features/candidates/module.py`
- Test: `backend/tests/features/candidates/test_api.py`
- Test: `backend/tests/features/candidates/test_jobs.py`

- [ ] **Step 1: Write failing worker and API contract tests**

```python
import pytest
from pydantic import ValidationError

from backend.app.features.candidates.contracts import CandidateRecommendationRequest


def test_request_rejects_client_owned_strategy_and_llm_grade() -> None:
    with pytest.raises(ValidationError):
        CandidateRecommendationRequest.model_validate(
            {
                "portfolio_id": "default",
                "as_of_time": "2026-07-16T15:30:00+08:00",
                "strategy_version": "v9.99",
                "llm_grade": "forward_observed",
            }
        )


def test_submit_returns_202_run_ref(candidate_api_client) -> None:
    response = candidate_api_client.post(
        "/api/v1/candidate-recommendations",
        headers={"Idempotency-Key": "candidate-20260716"},
        json={
            "portfolio_id": "default",
            "as_of_time": "2026-07-16T15:30:00+08:00",
        },
    )

    assert response.status_code == 202
    assert response.json()["kind"] == "candidate_recommendation"
    assert response.headers["location"].endswith(response.json()["run_id"])


def test_latest_returns_structured_result(candidate_api_client, saved_candidate_result) -> None:
    response = candidate_api_client.get(
        "/api/v1/candidate-recommendations/latest"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["bucket"] == "executable"
    assert body["auto_trade_enabled"] is False
    assert body["human_confirm_required"] is True


def test_job_handler_heartbeats_and_runs_service(fake_job_context, candidate_service) -> None:
    handler = CandidateJobHandler(candidate_service)

    handler(fake_job_context)

    assert fake_job_context.heartbeats == [("evaluating_candidates", 20), ("persisted", 100)]
    assert candidate_service.commands[0].run_id == fake_job_context.run_id
```

- [ ] **Step 2: Run API and worker tests and verify failure**

Run: `python -m pytest backend/tests/features/candidates/test_api.py backend/tests/features/candidates/test_jobs.py -q`

Expected: FAIL because the feature contracts, router, and handler are absent; the RED validation test also
fails because client-owned fields are currently accepted.

- [ ] **Step 3: Implement request/response DTOs from the domain models**

Implement `contracts.py` as follows:

```python
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from backend.app.features.candidates.models import (
    CandidateRecommendationResult,
    CandidateItem,
)


class CandidateRecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portfolio_id: str = Field(min_length=1)
    as_of_time: AwareDatetime


class CandidateFactorsResponse(BaseModel):
    p: Decimal
    f: Decimal
    r: Decimal
    t: Decimal
    v: Decimal
    s: Decimal
    percentile_rank: Decimal


class CandidateItemResponse(BaseModel):
    security_id: str
    security_name: str
    bucket: str
    state: str
    strategy_book: str | None
    factors: CandidateFactorsResponse
    planned_quantity: int
    initial_stop: Decimal | None
    trigger_condition: str
    invalidation_condition: str
    reason_codes: tuple[str, ...]
    quality_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    @classmethod
    def from_domain(cls, item: CandidateItem) -> "CandidateItemResponse":
        return cls(
            security_id=item.security_id,
            security_name=item.security_name,
            bucket=item.bucket.value,
            state=item.state.value,
            strategy_book=item.strategy_book.value if item.strategy_book else None,
            factors=CandidateFactorsResponse(
                p=item.factors.p,
                f=item.factors.f,
                r=item.factors.r,
                t=item.factors.t,
                v=item.factors.v,
                s=item.factors.s,
                percentile_rank=item.factors.percentile_rank,
            ),
            planned_quantity=item.planned_quantity,
            initial_stop=item.initial_stop,
            trigger_condition=item.trigger_condition,
            invalidation_condition=item.invalidation_condition,
            reason_codes=tuple(code.value for code in item.reason_codes),
            quality_codes=item.quality_codes,
            evidence_refs=item.evidence_refs,
        )


class CandidateRecommendationResponse(BaseModel):
    run_id: str
    as_of_time: datetime
    strategy_version: Literal["v2.12"]
    manifest_hash: str
    data_grade: str
    llm_grade: str
    market_state: str
    market_confidence: str
    quality_codes: tuple[str, ...]
    items: tuple[CandidateItemResponse, ...]
    auto_trade_enabled: Literal[False] = False
    human_confirm_required: Literal[True] = True

    @classmethod
    def from_domain(cls, result: CandidateRecommendationResult) -> "CandidateRecommendationResponse":
        return cls(
            run_id=result.run_id,
            as_of_time=result.as_of_time,
            strategy_version="v2.12",
            manifest_hash=result.manifest_hash,
            data_grade=result.data_grade.value,
            llm_grade=result.llm_grade.value,
            market_state=result.market_state,
            market_confidence=result.market_confidence,
            quality_codes=result.quality_codes,
            items=tuple(CandidateItemResponse.from_domain(item) for item in result.items),
        )
```

The request has no strategy-version or LLM-grade field. Explicit `from_domain()` constructors are required;
do not serialize with `__dict__` and do not accept an LLM action or quantity field.

- [ ] **Step 4: Implement the injected worker handler**

```python
# backend/app/features/candidates/jobs.py
from backend.app.features.candidates.contracts import CandidateRecommendationRequest
from backend.app.features.candidates.service import CandidateRecommendationCommand, CandidateService
from backend.app.infrastructure.tasks.handlers import JobContext


class CandidateJobHandler:
    def __init__(self, service: CandidateService) -> None:
        self._service = service

    def __call__(self, context: JobContext) -> None:
        request = CandidateRecommendationRequest.model_validate(context.payload)
        context.heartbeat("evaluating_candidates", 20)
        self._service.run(
            CandidateRecommendationCommand(
                run_id=context.run_id,
                portfolio_id=request.portfolio_id,
                as_of_time=request.as_of_time,
            )
        )
        context.heartbeat("persisted", 100)
```

- [ ] **Step 5: Implement router and module factories without global registration**

`create_candidate_router(run_submitter, repository, clock)` must create these routes:

```text
POST /candidate-recommendations              -> 202 RunRef + Location
GET  /candidate-recommendations/latest       -> CandidateRecommendationResponse
GET  /candidate-recommendations/{run_id}     -> CandidateRecommendationResponse
```

The POST route passes `Idempotency-Key` to the plan-00 run service and enqueues
`RunKind.CANDIDATE_RECOMMENDATION` with `submitted_at=clock.now()`; it never calls
`CandidateService.run()` in the request process. Missing
results return the common `ErrorResponse` with code `CANDIDATE_RESULT_NOT_FOUND`. `module.py` exports:

```python
@dataclass(frozen=True, slots=True)
class CandidateDependencies:
    run_submitter: RunSubmitter
    repository: CandidateRepository
    clock: Clock
    input_builder: StrategyInputBuilder
    job_handler: CandidateJobHandler


def build_candidate_feature(dependencies: CandidateDependencies) -> FeatureModule:
    return FeatureModule(
        name="candidates",
        router=create_candidate_router(
            dependencies.run_submitter,
            dependencies.repository,
            dependencies.clock,
        ),
        job_handlers=((RunKind.CANDIDATE_RECOMMENDATION, dependencies.job_handler),),
    )
```

Do not import or modify `main.py`; plan 06 calls this factory.

- [ ] **Step 6: Run API and worker tests**

Run: `python -m pytest backend/tests/features/candidates/test_api.py backend/tests/features/candidates/test_jobs.py -q`

Expected: `4 passed`; POST completes without invoking the strategy service in-process.

- [ ] **Step 7: Commit the async feature boundary**

```bash
git add backend/app/features/candidates/contracts.py \
  backend/app/features/candidates/jobs.py \
  backend/app/features/candidates/router.py \
  backend/app/features/candidates/module.py \
  backend/tests/features/candidates/test_api.py \
  backend/tests/features/candidates/test_jobs.py
git commit -m "feat(candidates): expose persistent async recommendation API"
```

### Task 8: Build the candidate Web feature from generated types

**Files:**
- Create: `web/src/features/candidates/api.ts`
- Create: `web/src/features/candidates/viewModel.ts`
- Create: `web/src/features/candidates/CandidateTable.tsx`
- Create: `web/src/features/candidates/CandidatePage.tsx`
- Create: `web/src/features/candidates/index.tsx`
- Test: `web/src/features/candidates/CandidatePage.test.tsx`

- [ ] **Step 1: Write failing component tests for all three buckets and submission**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CandidatePage } from "./CandidatePage";
import { candidateApi } from "./api";

vi.mock("./api", () => ({
    candidateApi: { latest: vi.fn(), submit: vi.fn() },
}));

test("shows executable, watchlist, excluded, evidence, and research warning", async () => {
    vi.mocked(candidateApi.latest).mockResolvedValue(candidateResultFixture);
    render(
        <QueryClientProvider client={new QueryClient()}>
            <CandidatePage />
        </QueryClientProvider>,
    );

    expect(await screen.findByText("研究级数据，不代表正式历史验证")).toBeVisible();
    expect(screen.getByRole("tab", { name: "可执行 1" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "观察 1" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "排除 1" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "查看证据" }));
    expect(screen.getByText("sha256:policy-1")).toBeVisible();
});

test("submits an asynchronous run and links to the run center", async () => {
    vi.mocked(candidateApi.latest).mockResolvedValue(candidateResultFixture);
    vi.mocked(candidateApi.submit).mockResolvedValue(runRefFixture);
    render(
        <QueryClientProvider client={new QueryClient()}>
            <CandidatePage />
        </QueryClientProvider>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "生成候选推荐" }));

    await waitFor(() => expect(candidateApi.submit).toHaveBeenCalledOnce());
    expect(screen.getByRole("link", { name: "查看运行进度" })).toHaveAttribute(
        "href",
        `/runs/${runRefFixture.run_id}`,
    );
});
```

- [ ] **Step 2: Run the Web test and verify failure**

Run: `npm --prefix web test -- --run src/features/candidates/CandidatePage.test.tsx`

Expected: FAIL because `CandidatePage` and `candidateApi` do not exist.

- [ ] **Step 3: Implement API calls using only generated schema types**

```ts
// web/src/features/candidates/api.ts
import type { components } from "@/generated/schema";
import { apiClient } from "@/shared/api/client";

export type CandidateRequest = components["schemas"]["CandidateRecommendationRequest"];
export type CandidateResult = components["schemas"]["CandidateRecommendationResponse"];
export type RunRef = components["schemas"]["RunRef"];

export const candidateApi = {
    latest: (): Promise<CandidateResult> =>
        apiClient.get("/api/v1/candidate-recommendations/latest"),
    submit: (request: CandidateRequest, idempotencyKey: string): Promise<RunRef> =>
        apiClient.post("/api/v1/candidate-recommendations", request, {
            headers: { "Idempotency-Key": idempotencyKey },
        }),
};
```

- [ ] **Step 4: Implement view models and accessible structured-result components**

`viewModel.ts` maps only stable enum values to Chinese labels and groups `items` by `bucket` without
changing scores, quantities, reasons, or grades. `CandidateTable.tsx` renders S and percentile rank,
planned quantity, initial stop, trigger, invalidation, reason codes, quality codes, and an expandable
evidence list. `CandidatePage.tsx` uses TanStack Query for `latest`, a mutation for `submit`, explicit loading,
empty, and error panels, and a visible `data_grade === "research"` warning. It must display
“仅供人工确认，不自动下单” beside every executable result.

`index.tsx` exports, but does not globally register:

```tsx
import type { FeatureDefinition } from "@/app/featureRegistry";
import { CandidatePage } from "./CandidatePage";

export const candidateFeature: FeatureDefinition = {
    id: "candidates",
    path: "/candidates",
    label: "候选推荐",
    element: <CandidatePage />,
};
```

- [ ] **Step 5: Run unit tests and TypeScript checks**

Run: `npm --prefix web test -- --run src/features/candidates/CandidatePage.test.tsx`

Expected: `2 passed`.

Run: `npm --prefix web run typecheck`

Expected: TypeScript exits 0 with no handwritten duplicate backend DTO.

- [ ] **Step 6: Commit the Web feature**

```bash
git add web/src/features/candidates
git commit -m "feat(candidates): visualize structured recommendation evidence"
```

### Task 9: Verify candidate-feature invariants and hand off integration inputs

**Files:**
- Create: `backend/tests/features/candidates/test_invariants.py`
- Create: `backend/app/features/candidates/INTEGRATION.md`

- [ ] **Step 1: Add invariant tests for determinism, ownership, and no Markdown parsing**

```python
from pathlib import Path

from backend.tests.features.candidates.factories import candidate_command


def test_same_manifest_and_state_produce_identical_result(candidate_service_fixture) -> None:
    first = candidate_service_fixture.run(candidate_command(run_id="run-a"))
    second = candidate_service_fixture.run(candidate_command(run_id="run-b"))

    assert first.items == second.items


def test_candidate_feature_has_no_markdown_input_parser() -> None:
    files = Path("backend/app/features/candidates").glob("*.py")
    joined = "\n".join(path.read_text(encoding="utf-8") for path in files)

    assert "parse_markdown" not in joined
    assert "/Users/bujiatang/workspace/LA" not in joined
    assert "llm_raw_output.action" not in joined
```

- [ ] **Step 2: Write the integration handoff document**

`INTEGRATION.md` must state these exact coordinator actions:

1. import feature SQLAlchemy metadata and generate candidate tables in one plan-06 Alembic revision;
2. construct `CandidateService` with PIT warehouse, portfolio reader, `StrategyInputBuilder`,
   `V212StrategyEngine`, and repository;
3. call `build_candidate_feature()` from the global feature registry;
4. export OpenAPI, regenerate `web/src/generated/schema.d.ts`, and confirm no diff after a second generation;
5. register `candidateFeature` in global Web navigation;
6. run the candidate API, worker, PostgreSQL, and Web E2E path.

- [ ] **Step 3: Run the complete feature verification**

Run: `python -m pytest backend/tests/features/candidates -q`

Expected: all candidate tests pass.

Run: `python -m ruff check backend/app/features/candidates backend/tests/features/candidates`

Expected: Ruff exits 0.

Run: `python -m mypy backend/app/features/candidates`

Expected: all commands exit 0; every function is typed and every line is at most 100 characters.

Run: `npm --prefix web test -- --run src/features/candidates`

Expected: Vitest exits 0.

Run: `npm --prefix web run typecheck`

Expected: TypeScript exits 0.

Run: `npm --prefix web run build`

Expected: the production build exits 0.

Run: `rg -n "(/Users/bujiatang/workspace/LA|parse_markdown|llm_raw_output.*(buy|sell|quantity))" backend/app/features/candidates web/src/features/candidates`

Expected: no matches.

- [ ] **Step 4: Commit verification and handoff**

```bash
git add backend/tests/features/candidates/test_invariants.py \
  backend/app/features/candidates/INTEGRATION.md
git commit -m "test(candidates): enforce deterministic advisory boundary"
```

The candidate branch is ready for review when it contains nine small Conventional Commits, all commands
above pass, and no global entry point, generated contract, or migration file has changed.
