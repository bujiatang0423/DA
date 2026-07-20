import { expectTypeOf, test } from "vitest";

import type { components, operations } from "./schema";

type RunRef = components["schemas"]["RunRef"];

type CandidateAccepted = (
  operations["submit_candidate_api_v1_candidates_post"]["responses"]
)[202]["content"]["application/json"];
type HoldingAccepted = (
  operations["submit_analysis_api_v1_holding_analyses_post"]["responses"]
)[202]["content"]["application/json"];
type LegacyHoldingAccepted = (
  operations["submit_legacy_analysis_api_v1_holdings_analysis_submit_post"]["responses"]
)[202]["content"]["application/json"];
type BacktestAccepted = (
  operations["submit_backtest_api_v1_backtests_post"]["responses"]
)[202]["content"]["application/json"];
type RetryAccepted = (
  operations["retry_run_api_v1_runs__run_id__retry_post"]["responses"]
)[202]["content"]["application/json"];
type RunAccepted = (
  operations["submit_run_api_v1_runs_post"]["responses"]
)[202]["content"]["application/json"];
type CandidateHeaders = (
  operations["submit_candidate_api_v1_candidates_post"]["responses"]
)[202]["headers"];
type HoldingHeaders = (
  operations["submit_analysis_api_v1_holding_analyses_post"]["responses"]
)[202]["headers"];
type LegacyHoldingHeaders = (
  operations["submit_legacy_analysis_api_v1_holdings_analysis_submit_post"]["responses"]
)[202]["headers"];
type BacktestHeaders = (
  operations["submit_backtest_api_v1_backtests_post"]["responses"]
)[202]["headers"];
type RetryHeaders = (
  operations["retry_run_api_v1_runs__run_id__retry_post"]["responses"]
)[202]["headers"];
type RunHeaders = (
  operations["submit_run_api_v1_runs_post"]["responses"]
)[202]["headers"];

test("generated long-running operations share the RunRef and Location contract", () => {
  expectTypeOf<CandidateAccepted>().toEqualTypeOf<RunRef>();
  expectTypeOf<HoldingAccepted>().toEqualTypeOf<RunRef>();
  expectTypeOf<LegacyHoldingAccepted>().toEqualTypeOf<RunRef>();
  expectTypeOf<BacktestAccepted>().toEqualTypeOf<RunRef>();
  expectTypeOf<RetryAccepted>().toEqualTypeOf<RunRef>();
  expectTypeOf<RunAccepted>().toEqualTypeOf<RunRef>();
  expectTypeOf<CandidateHeaders["Location"]>().toEqualTypeOf<string | undefined>();
  expectTypeOf<HoldingHeaders["Location"]>().toEqualTypeOf<string | undefined>();
  expectTypeOf<LegacyHoldingHeaders["Location"]>().toEqualTypeOf<string | undefined>();
  expectTypeOf<BacktestHeaders["Location"]>().toEqualTypeOf<string | undefined>();
  expectTypeOf<RetryHeaders["Location"]>().toEqualTypeOf<string | undefined>();
  expectTypeOf<RunHeaders["Location"]>().toEqualTypeOf<string | undefined>();
});
