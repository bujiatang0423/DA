import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { BacktestsPage } from "./index";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

test("submits a manual-only research backtest and renders persisted audit evidence", async () => {
  vi.mocked(fetch).mockImplementation(async (input) => {
    const url = String(input);
    if (url === "/api/v1/backtests") {
      return new Response(JSON.stringify({
        run_id: "run-1",
        kind: "backtest",
        status: "queued",
        submitted_at: "2026-07-20T00:00:00Z",
        links: { self: "/api/v1/runs/run-1", result: "/api/v1/backtests/run-1" },
        auto_trade_enabled: false,
        human_confirm_required: true,
      }), { status: 202 });
    }
    return new Response(JSON.stringify({
      run_id: "run-1",
      status: "succeeded",
      strategy_version: "v2.12",
      input_manifest_hash: "manifest-1",
      created_at: "2026-07-20T00:00:00Z",
      groups: [
        {
          group: "A", data_grade: "research", llm_grade: "not_used",
          input_manifest_hash: "manifest-1", metrics: {},
        },
        {
          group: "B", data_grade: "research", llm_grade: "reconstructed",
          input_manifest_hash: "manifest-1", metrics: {},
        },
      ],
      group: "A",
      metrics: { profit_factor: "1.23", closed_trade_count: 1 },
      metric_details: {
        values: {
          profit_factor: { value: "1.23", diagnostic: "ZERO_DENOMINATOR" },
        },
        acceptance_gates: [
          {
            name: "net_profit_factor",
            observed: "1.23",
            threshold: "1.5",
            passed: false,
            reason: "INSUFFICIENT_CLOSED_TRADES",
          },
        ],
      },
      warnings: ["research_only"],
      equity_curve: {
        items: [{ trade_date: "2023-01-02", equity: "150000" }], next_cursor: null,
      },
      trades: {
        items: [{ order_id: "A-trade-1", trade_date: "2023-01-03", side: "buy", quantity: "100" }],
        next_cursor: null,
      },
      rejected_attempts: {
        items: [{ order_id: "A-reject-1", reason_code: "LIMIT_UP_LOCKED" }], next_cursor: null,
      },
    }), { status: 200 });
  });

  render(<BacktestsPage />);
  fireEvent.click(screen.getByRole("button", { name: "开始回测" }));

  await waitFor(() => expect(screen.getByText("研究级数据")).toBeTruthy());
  expect(screen.getByText(/重建 LLM 因子/)).toBeTruthy();
  expect(screen.getByText(/未通过：net_profit_factor/)).toBeTruthy();
  expect(screen.getByText(/ZERO_DENOMINATOR/)).toBeTruthy();
  expect(screen.getByText(/INSUFFICIENT_CLOSED_TRADES/)).toBeTruthy();
  expect(screen.getByText("1.23")).toBeTruthy();
  expect(screen.getByTestId("equity-series")).toBeTruthy();
  expect(screen.getByText("A-trade-1")).toBeTruthy();
  expect(screen.getByText("LIMIT_UP_LOCKED")).toBeTruthy();
  expect(screen.getByText("仅供研究和人工执行，不自动交易")).toBeTruthy();
  expect(fetch).toHaveBeenCalledWith(
    "/api/v1/backtests",
    expect.objectContaining({ method: "POST" }),
  );
});
