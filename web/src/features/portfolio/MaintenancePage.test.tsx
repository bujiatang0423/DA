import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { MaintenancePage } from "./MaintenancePage";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

test("loads imported opening positions from the unified portfolio endpoint", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => new Response(
      JSON.stringify({
        portfolio_id: "default",
        as_of_time: "2026-07-21T12:00:00+08:00",
        version: 0,
        cash: "100000",
        equity: "100000",
        items: [
          {
            security_id: "601899.SH",
            security_name: "紫金矿业",
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
    ));

  render(<MaintenancePage />);

  await waitFor(() => expect(screen.getByDisplayValue("601899.SH")).toBeTruthy());
  expect(screen.getByDisplayValue("1100")).toBeTruthy();
  expect(screen.getByDisplayValue("31.191")).toBeTruthy();
  expect(screen.getByDisplayValue("2026-03-05")).toBeTruthy();
  expect(screen.getByDisplayValue("紫金矿业")).toBeTruthy();
  expect(screen.queryByText("legacy_opening_balance:601899.SH")).toBeNull();
  expect(vi.mocked(fetch).mock.calls[0]?.[0]).toContain("/api/v1/portfolio/positions");
});

test("keeps the new-row code input focused while typing", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => new Response(
      JSON.stringify({
        portfolio_id: "default",
        as_of_time: "2026-07-21T12:00:00+08:00",
        version: 0,
        cash: "0",
        equity: "0",
        items: [],
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    ));

  render(<MaintenancePage />);
  await waitFor(() => expect(screen.getByRole("button", { name: "新增一行" })).toBeTruthy());
  fireEvent.click(screen.getByRole("button", { name: "新增一行" }));
  const codeInput = screen.getByRole("textbox", { name: "证券代码" });
  fireEvent.change(codeInput, { target: { value: "0" } });
  fireEvent.change(codeInput, { target: { value: "00" } });
  fireEvent.change(codeInput, { target: { value: "000425.SZ" } });
  expect((codeInput as HTMLInputElement).value).toBe("000425.SZ");
  const nameInput = screen.getByRole("textbox", { name: "中文名称" });
  fireEvent.change(nameInput, { target: { value: "徐工机械" } });
  expect((nameInput as HTMLInputElement).value).toBe("徐工机械");
});
