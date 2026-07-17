import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { BacktestsPage } from "./index";

beforeEach(() => { vi.stubGlobal("fetch", vi.fn()); });
test("submits backtest parameters and renders walk-forward holdout", async () => {
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ strategy_version: "v2.12", holdout: { start: "2025-01-01", end: "2025-12-31" }, windows: [], groups: ["A", "B"] }), { status: 200 }));
  render(<BacktestsPage />); fireEvent.click(screen.getByRole("button", { name: "生成回测计划" }));
  await waitFor(() => expect(screen.getByText(/Holdout：2025-01-01/)).toBeTruthy());
});
