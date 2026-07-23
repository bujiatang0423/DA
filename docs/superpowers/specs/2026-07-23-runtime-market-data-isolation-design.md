# Runtime Market Data Isolation Design

## Goal

Ensure normal local operation uses only externally sourced market data and never reads
checked-in test fixtures for holdings, candidate research, or backtests.

## Boundaries

`backend/fixtures/**` is test-only.  It may be read only by the explicit E2E bootstrap
entry point after `DA_E2E_MODE` is enabled.  The normal API, worker, and start script
must not pass a fixture path to any runtime data service.

For a normal holdings quote refresh, the source order is: realtime provider during the
trading session, external latest-close provider outside it, then the most recent stored
quote whose source is an external provider.  A fixture quote is never an eligible
fallback.  Missing prices remain missing and must not change portfolio equity.

Candidate recommendation and backtest use their configured provider/PIT data sources.
They must reject fixture-backed providers unless E2E mode is explicitly enabled.

## Verification

Regression tests cover that normal quote refresh does not require or read a fixture,
records external price sources, and preserves the last external quote when providers
are unavailable.  A repository scan verifies fixture paths are isolated to the E2E
bootstrap and tests.
