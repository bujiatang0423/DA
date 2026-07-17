import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { HoldingsPage } from "./index";

beforeEach(() => { vi.stubGlobal("fetch", vi.fn()); });
test("submits holding analysis and shows risk", async () => {
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ portfolio_id: "p1", equity: 100, exposure_ratio: 0.5, portfolio_drawdown: 0, warnings: [], risks: [{ security_id: "600000", quantity: 10, market_value: 100, risk_status: "ok", stop_breached: false, reasons: [] }] }), { status: 200 }));
  render(<HoldingsPage />); fireEvent.change(screen.getByLabelText("组合 ID"), { target: { value: "p1" } }); fireEvent.click(screen.getByRole("button", { name: "运行分析" }));
  await waitFor(() => expect(screen.getByText("600000")).toBeTruthy());
});
