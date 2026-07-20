import { expect, expectTypeOf, test, vi } from "vitest";

import { retryRun, type RunRef } from "./client";

test("retryRun returns the run reference emitted by the retry endpoint", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          run_id: "run-1",
          kind: "backtest",
          status: "queued",
          submitted_at: "2026-07-20T09:30:00Z",
          links: { self: "/api/v1/runs/run-1" },
          auto_trade_enabled: false,
          human_confirm_required: true,
        }),
        { status: 202 },
      ),
    ),
  );

  const result = await retryRun("run-1");

  expect(result).toEqual({
    run_id: "run-1",
    kind: "backtest",
    status: "queued",
    submitted_at: "2026-07-20T09:30:00Z",
    links: { self: "/api/v1/runs/run-1" },
    auto_trade_enabled: false,
    human_confirm_required: true,
  });
});

expectTypeOf(retryRun).returns.toEqualTypeOf<Promise<RunRef>>();
