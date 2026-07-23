# Real PIT Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a source-traceable real-data ingestion path for current research and historical PIT
backtests, without allowing fixtures into normal runtime.

**Architecture:** Runtime providers obtain current evidence from AkShare and official source stores.
An ingestion command persists real source artifacts and time-bounded records in PostgreSQL; strict
backtests consume only those persisted, coverage-audited records. DeepSeek remains optional until a
local key is configured, and then only extracts structured evidence from persisted inputs.

**Tech Stack:** Python, FastAPI, SQLAlchemy, PostgreSQL, AkShare, requests, pytest.

---

### Task 1: Real AkShare market and financial adapter

**Files:**
- Create: `backend/app/infrastructure/market/akshare_research_provider.py`
- Modify: `backend/app/bootstrap/composition.py`
- Test: `backend/tests/infrastructure/market/test_akshare_research_provider.py`

- [ ] **Step 1: Write failing adapter tests**

```python
def test_provider_returns_unadjusted_daily_bars_with_source_hash() -> None:
    provider = AkShareResearchProvider(fake_akshare_response)
    bar = provider.daily_bars("000568.SZ", AS_OF)[0]
    assert bar.price_adjustment == "none"
    assert len(bar.source_hash) == 64

def test_provider_rejects_financial_rows_without_publication_time() -> None:
    assert provider.financials("000568.SZ", AS_OF) == ()
```

- [ ] **Step 2: Run the test and verify failure**

Run: `python -m pytest backend/tests/infrastructure/market/test_akshare_research_provider.py -q`

- [ ] **Step 3: Implement the adapter**

Implement `ResearchMarketDataPort` methods with AkShare public calls for requested securities,
normalize exchange suffixes, reject zero/adjusted prices, hash canonical raw responses, and return
only records whose source publication/observation time is no later than `as_of_time`.

- [ ] **Step 4: Run the adapter tests**

Run: `python -m pytest backend/tests/infrastructure/market/test_akshare_research_provider.py -q`

### Task 2: Official financial and policy evidence stores

**Files:**
- Create: `backend/app/infrastructure/financial/announcement_evidence.py`
- Create: `backend/app/infrastructure/policy/official_policy_store.py`
- Create: `backend/migrations/versions/20260723_0023_live_evidence.py`
- Test: `backend/tests/infrastructure/policy/test_official_policy_store.py`
- Test: `backend/tests/infrastructure/financial/test_announcement_evidence.py`

- [ ] **Step 1: Write failing evidence-time tests**

```python
def test_policy_document_is_hidden_before_publication_time() -> None:
    assert store.materials(as_of_time=before_publication) == ()

def test_financial_fact_requires_matching_official_announcement() -> None:
    assert evidence.match_financial_fact(fact) is None
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest backend/tests/infrastructure/policy/test_official_policy_store.py backend/tests/infrastructure/financial/test_announcement_evidence.py -q`

- [ ] **Step 3: Implement persisted evidence**

Persist official URLs, issuer, report period, publication time, first-observed time, text/raw hash
and review state.  Permit only CSRC, gov.cn, SSE and SZSE policy hosts.  Expose only reviewed,
time-visible policy material and financial facts linked to official announcements.

- [ ] **Step 4: Run evidence tests**

Run: `python -m pytest backend/tests/infrastructure/policy/test_official_policy_store.py backend/tests/infrastructure/financial/test_announcement_evidence.py -q`

### Task 3: Real historical ingestion and PIT certification

**Files:**
- Create: `backend/app/features/pit_ingestion/service.py`
- Create: `backend/app/features/pit_ingestion/cli.py`
- Modify: `backend/app/infrastructure/market/strict_ingest.py`
- Test: `backend/tests/features/pit_ingestion/test_real_source_ingestion.py`

- [ ] **Step 1: Write failing ingestion tests**

```python
def test_real_ingestion_persists_source_lineage_before_strict_records() -> None:
    result = service.ingest(request)
    assert result.lineage_provider == "akshare"
    assert strict_reader.daily_bars("000568.SZ", date(2026, 7, 22), AS_OF)

def test_fixture_artifact_is_rejected_by_real_ingestion() -> None:
    with pytest.raises(RealSourceRequiredError):
        service.ingest(fixture_request)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest backend/tests/features/pit_ingestion/test_real_source_ingestion.py -q`

- [ ] **Step 3: Implement ingestion and certification inputs**

Fetch the requested historical date range, write raw source artifacts and lineage, then persist
daily bars, disclosures, policy and availability times.  Reject source names/paths associated with
fixtures.  Invoke existing coverage audit/certificate flow only after persistence succeeds.

- [ ] **Step 4: Run ingestion tests**

Run: `python -m pytest backend/tests/features/pit_ingestion/test_real_source_ingestion.py -q`

### Task 4: DeepSeek structured-factor provider

**Files:**
- Create: `backend/app/infrastructure/llm/deepseek_provider.py`
- Modify: `backend/app/bootstrap/composition.py`
- Test: `backend/tests/infrastructure/llm/test_deepseek_provider.py`

- [ ] **Step 1: Write failing provider tests**

```python
def test_deepseek_provider_rejects_missing_key() -> None:
    with pytest.raises(ProviderUnavailableError):
        provider.extract(...)

def test_deepseek_provider_validates_json_factor_and_hashes_inputs() -> None:
    factor = provider.extract(...)
    assert factor.input_hash and factor.output_hash
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest backend/tests/infrastructure/llm/test_deepseek_provider.py -q`

- [ ] **Step 3: Implement the provider**

Read `DEEPSEEK_API_KEY` and model from environment only, use JSON output mode, bounded retries for
429/empty output, validate with `validate_factor`, and never log the key or source document body.

- [ ] **Step 4: Run provider tests**

Run: `python -m pytest backend/tests/infrastructure/llm/test_deepseek_provider.py -q`

### Task 5: Normal-runtime factory and end-to-end verification

**Files:**
- Create: `backend/app/bootstrap/local_real_provider_factory.py`
- Modify: `.env.example`
- Test: `backend/tests/system/test_real_provider_factory.py`

- [ ] **Step 1: Write failing normal-runtime tests**

```python
def test_factory_never_loads_fixture_paths() -> None:
    providers = build(Settings(...))
    assert providers.market.provider_name == "akshare"

def test_missing_deepseek_key_fails_closed_without_fixture() -> None:
    snapshot = warehouse.snapshot(as_of_time=AS_OF, scope=scope)
    assert "REQUIRED_DATASET_MISSING" in quality_codes(snapshot)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest backend/tests/system/test_real_provider_factory.py -q`

- [ ] **Step 3: Implement configuration and verification**

Document non-secret environment variable names, require the factory in normal runtime, and verify
current analysis records real source lineage.  Keep backtest composition strictly SQL/PIT-only.

- [ ] **Step 4: Run all relevant verification**

Run: `python -m pytest backend/tests/infrastructure/market backend/tests/features/pit_ingestion backend/tests/infrastructure/llm backend/tests/system/test_real_provider_factory.py -q`
