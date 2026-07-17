# Production Provider Composition Design

## Goal

Make the production composition root construct one complete research evidence chain for candidate
recommendations and holding analysis. The chain must use real provider adapters when configured and
must fail closed when any required input is unavailable, invalid, or later than the requested as-of
time.

This work covers Candidate Integration Tasks 1-4 and Provider Tasks 3-10 only. It does not add
strict PIT certification, backtest execution, Web screens, or automatic trading.

## Decisions

- Production market data uses AkShare as the primary source. BaoStock is used only as a daily-bar
  fallback when AkShare returns no bars or raises a provider availability error.
- The production market adapter supplies the existing `ResearchMarketDataPort`: trading calendar,
  universe and status, daily and index bars, quotes, financial disclosures and facts, and fee
  schedules. All records carry a source hash and an explicit `available_at` timestamp.
- Policy documents come from a configured official JSON feed. Every document must include a source
  identifier, official source identifier, publication time, first-observed time, grade, and text.
  Documents without valid official evidence or with future availability are excluded.
- DeepSeek is accessed through its OpenAI-compatible chat-completions endpoint. The client uses
  `DA_DEEPSEEK_API_KEY`, `DA_DEEPSEEK_BASE_URL`, and `DA_DEEPSEEK_MODEL`; the key is never logged,
  stored in the repository, or returned through an API.
- DeepSeek responses are parsed as JSON and passed through the existing structured-factor validator.
  Any forbidden trading field, invalid enum or score, unavailable evidence, identity mismatch, or
  malformed response rejects the factor.
- Production snapshots remain `DataGrade.RESEARCH`. They never receive `pit_verified` merely because
  a provider returns historical rows.

## Architecture

`build_components()` remains the only application composition root. In fake mode it requires an
explicit frozen warehouse. In production mode it constructs a market port, policy port, and LLM port,
then calls `build_point_in_time_warehouse(market=..., policy=..., llm=...)`.

The resulting warehouse is injected unchanged into both `CandidateService` and
`V212HoldingAnalysisService`. Strategy formulas continue to run exclusively through
`StrategyInputBuilder` and `V212StrategyEngine`.

The evidence source converts provider port output into the existing PIT records and lineage. A
provider failure is represented as a stable snapshot quality error, rather than a partial strategy
input. The candidate service then persists an empty result with no executable items. The worker can
surface a safe error code without exposing provider response bodies, policy text, holdings, or secrets.

## Configuration

Production configuration adds explicit settings for the policy feed and DeepSeek endpoint. Optional
provider packages are imported only when production mode is selected, so fake-mode tests and local
development do not need network access or production credentials.

Required production settings are `DA_PROVIDER_MODE=production`, an HTTPS
`DA_OFFICIAL_POLICY_FEED_URL` owned by an official-source normalizer, `DA_DEEPSEEK_API_KEY`,
`DA_DEEPSEEK_BASE_URL=https://api.deepseek.com`, and `DA_DEEPSEEK_MODEL=deepseek-chat`. The policy
feed URL has no repository default: deployment must explicitly select and provide it.

The API key belongs in an untracked local environment file or the deployment secret store. Its value
is not needed for unit tests.

## Failure Handling

- A missing configuration value, unavailable provider, empty required dataset, invalid JSON, or
  invalid LLM factor produces a stable quality code and prevents executable recommendations.
- Records whose event or availability time is after the requested as-of time are rejected by the
  existing snapshot gate.
- The daily-bar fallback is limited to an availability failure. It never hides validation errors or
  silently mixes incompatible identifiers.
- No provider, LLM, or policy error may enable automatic trading. Result invariants remain
  `auto_trade_enabled=false` and `human_confirm_required=true`.

## Verification

Tests will cover:

1. Production composition creates exactly one complete evidence warehouse and shares it with both
   services; fake mode still requires an explicit fake warehouse.
2. Market normalization, canonical security identifiers, lineage hashes, and AkShare-to-BaoStock
   daily-bar fallback.
3. Policy publication and first-observed time filtering.
4. DeepSeek request construction and validation of valid, malformed, future, and trading-like output.
5. Complete fake evidence yields a deterministic candidate result; each missing or failed provider
   yields a persisted empty, non-executable result with a quality code.

Live connectivity is a separately marked smoke test. It runs only when the required local environment
variables are set and is not part of the default test suite.
