# Runtime Market Data Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent normal runtime flows from using checked-in fixture market data.

**Architecture:** Split the quote scheduler into an external provider reader and a
database fallback reader.  The normal worker receives no fixture path; the explicit
E2E entry point owns fixture use.  PIT-backed candidate and backtest construction keeps
its existing provider boundary and fails closed for fixture sources outside E2E mode.

**Tech Stack:** Python, FastAPI, SQLAlchemy, PostgreSQL, pytest.

---

### Task 1: Make normal quote refresh external-only

**Files:**
- Modify: `backend/app/infrastructure/market/portfolio_quote_scheduler.py`
- Modify: `backend/app/worker_main.py`
- Test: `backend/tests/infrastructure/market/test_portfolio_quote_scheduler.py`

- [ ] **Step 1: Write failing tests**

```python
def test_refresh_uses_external_latest_close_outside_trading_hours(...):
    ...
    assert stored.source == "sina_latest_close"

def test_refresh_keeps_last_external_quote_when_provider_is_unavailable(...):
    ...
    assert quote_count_after == quote_count_before
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest backend/tests/infrastructure/market/test_portfolio_quote_scheduler.py -q`

- [ ] **Step 3: Implement external source selection and database fallback**

Remove the fixture parameter from the normal scheduler.  Query realtime or latest-close
external providers according to market session; only use the latest previously stored
external-source quote when the provider returns no price.

- [ ] **Step 4: Run the targeted tests**

Run: `pytest backend/tests/infrastructure/market/test_portfolio_quote_scheduler.py -q`

### Task 2: Keep fixtures exclusive to explicit E2E startup

**Files:**
- Modify: `backend/app/e2e_main.py`
- Modify: `backend/app/bootstrap/e2e.py`
- Test: `backend/tests/infrastructure/market/test_runtime_fixture_isolation.py`

- [ ] **Step 1: Write failing source-boundary tests**

```python
def test_normal_worker_does_not_reference_local_market_fixture() -> None:
    assert "fixtures/local_market" not in worker_source
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest backend/tests/infrastructure/market/test_runtime_fixture_isolation.py -q`

- [ ] **Step 3: Keep fixture paths in E2E-only construction**

Wire the fixture scheduler only from `e2e_main.py`, guarded by `DA_E2E_MODE`; normal
worker startup has no fixture dependency.

- [ ] **Step 4: Run the targeted tests**

Run: `pytest backend/tests/infrastructure/market/test_runtime_fixture_isolation.py -q`

### Task 3: Audit runtime research paths and validate the real database

**Files:**
- Test: `backend/tests/infrastructure/market/test_runtime_fixture_isolation.py`

- [ ] **Step 1: Add an allowlist scan for runtime imports**

```python
def test_fixture_paths_only_exist_in_e2e_and_test_modules() -> None:
    ...
```

- [ ] **Step 2: Run full affected tests and source scan**

Run: `pytest backend/tests/infrastructure/market backend/tests/infrastructure/persistence/test_portfolio_maintenance.py -q`

- [ ] **Step 3: Remove fixture-sourced quote rows and refresh real quotes**

Run: query `portfolio_position_quotes`, delete only `source IN ('latest_close', 'local_frozen_seed', 'fixture')`, then refresh and verify each current lot has an external source or is explicitly missing.
