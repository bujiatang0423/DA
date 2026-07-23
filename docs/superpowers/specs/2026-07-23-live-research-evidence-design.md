# Live Research Evidence Design

## Goal

Run local holding and candidate analysis only from live, externally obtained evidence, while
keeping historical backtests restricted to persisted and certified point-in-time data.

## Source responsibilities

- **Market and financials:** an AkShare adapter fetches unadjusted daily bars, current quotes,
  security metadata and public financial statements for requested securities.  Each response is
  normalized with provider name, retrieval time and SHA-256 lineage.
- **Financial evidence:** a low-rate CNINFO/exchange-announcement collector stores the official
  announcement URL, report period, publication time and content hash.  AkShare facts are usable
  only when tied to an announcement publication time; a missing announcement is an explicit
  quality error.
- **Policy evidence:** a reviewed local evidence store receives documents only from a fixed
  official-source allowlist: CSRC, China Government Network, SSE and SZSE.  It records source URL,
  issuer, publication/effective time, first observation time, text and hash.  No search-engine or
  fixture material is accepted.
- **LLM evidence:** a DeepSeek adapter calls the configured OpenAI-compatible endpoint only with
  already stored financial and policy evidence.  It requests the existing factor schema, validates
  it, records model/prompt/input/output hashes, and fails closed on a missing key, invalid model,
  non-JSON response, 429 or schema failure.  The model identifier is configurable rather than
  hard-coded.

## Runtime and point-in-time rules

`DA_RESEARCH_PROVIDER_FACTORY` creates the market, policy and LLM ports for normal local runtime.
No normal component reads `backend/fixtures/**`.  Holding/candidate analysis fails closed when any
required source is unavailable, rather than synthesizing facts or scores.

Live data is for current holding/candidate research.  Backtests continue to read only the
PostgreSQL strict PIT warehouse.  A separate ingestion and certification step must persist live
evidence before it is eligible for historical backtests; no backtest calls AkShare, CNINFO, policy
sites or DeepSeek directly.

## Configuration

The implementation adds documented, Git-ignored local environment variables for source settings.
Secrets are never committed or logged.  The user supplies `DEEPSEEK_API_KEY` later; until then the
LLM adapter reports an unavailable required dataset and blocks analysis safely.

## Acceptance criteria

1. A normal holding analysis reads no fixture and records external lineage for every accepted
   market, financial, policy and LLM record.
2. AkShare/CNINFO/policy failure or absence of a DeepSeek key produces a precise quality failure,
   never a fixture fallback.
3. A successful DeepSeek response passes the existing factor-schema and forbidden-field checks.
4. Normal candidate/holding runtime uses the configured provider factory; strict backtests remain
   database/PIT-only.
