import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { MaintenancePage } from "./MaintenancePage";

afterEach(() => vi.restoreAllMocks());

test("loads imported opening positions from the unified portfolio endpoint", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify({
        portfolio_id: "default",
        as_of_time: "2026-07-21T12:00:00+08:00",
        version: 0,
        cash: "100000",
        equity: "100000",
        items: [
          {
            security_id: "601899.SH",
            buy_date: "2026-03-05",
            origin: "legacy_opening_balance",
            quantity: 1100,
            available_to_sell: 0,
            average_cost: "31.191000",
            effective_stop: null,
            highest_close: null,
            strategy_book: null,
          },
        ],
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    ),
  );

  render(<MaintenancePage />);

  await waitFor(() => expect(screen.getByDisplayValue("601899.SH")).toBeTruthy());
  expect(screen.getByDisplayValue("1100")).toBeTruthy();
  expect(screen.getByDisplayValue("31.191")).toBeTruthy();
  expect(screen.getByDisplayValue("2026-03-05")).toBeTruthy();
  expect(vi.mocked(fetch).mock.calls[0]?.[0]).toContain("/api/v1/portfolio/positions");
});
