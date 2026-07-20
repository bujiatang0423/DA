import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { BacktestsPage } from "./index";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
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
  expect(screen.getByTestId("drawdown-series")).toBeTruthy();
  expect(screen.getByText("A-trade-1")).toBeTruthy();
  expect(screen.getByText("LIMIT_UP_LOCKED")).toBeTruthy();
  expect(screen.getByText("仅供研究和人工执行，不自动交易")).toBeTruthy();
  expect(fetch).toHaveBeenCalledWith(
    "/api/v1/backtests",
    expect.objectContaining({ method: "POST" }),
  );
});

test("checks queued runs without fetching unavailable result data", async () => {
  vi.mocked(fetch).mockImplementation(async (input) => {
    const url = String(input);
    if (url === "/api/v1/backtests") {
      return new Response(JSON.stringify({ run_id: "run-queued" }), { status: 202 });
    }
    if (url === "/api/v1/runs/run-queued") {
      return new Response(JSON.stringify({ run_id: "run-queued", status: "queued" }));
    }
    return new Response(null, { status: 500 });
  });

  render(<BacktestsPage />);
  fireEvent.click(screen.getByRole("button", { name: "开始回测" }));

  expect(await screen.findByText("任务已提交，正在等待持久回测结果...")).toBeTruthy();
  expect(fetch).toHaveBeenCalledWith("/api/v1/runs/run-queued");
  expect(fetch).not.toHaveBeenCalledWith(expect.stringContaining("/api/v1/backtests/run-queued"));
});

test("reloads an idempotent run when the same request is submitted again", async () => {
  vi.mocked(fetch).mockImplementation(async (input) => {
    const url = String(input);
    if (url === "/api/v1/backtests") {
      return new Response(JSON.stringify({ run_id: "same-run" }), { status: 202 });
    }
    if (url === "/api/v1/runs/same-run") {
      return new Response(JSON.stringify({ run_id: "same-run", status: "succeeded" }));
    }
    return new Response(JSON.stringify(resultResponse("A")));
  });

  render(<BacktestsPage />);
  const submit = screen.getByRole("button", { name: "开始回测" });
  fireEvent.click(submit);
  expect(await screen.findByText("A-only-metric")).toBeTruthy();

  fireEvent.click(submit);
  expect(screen.queryByText("A-only-metric")).toBeNull();
  expect(await screen.findByText("A-only-metric")).toBeTruthy();
  expect(fetch).toHaveBeenCalledTimes(6);
});

test("uses run status before results and stops safely when a run fails", async () => {
  vi.mocked(fetch).mockImplementation(async (input) => {
    const url = String(input);
    if (url === "/api/v1/backtests") {
      return new Response(JSON.stringify({ run_id: "run-2" }), { status: 202 });
    }
    if (url === "/api/v1/runs/run-2") {
      return new Response(JSON.stringify({
        run_id: "run-2",
        status: "failed",
        error_code: "PROVIDER_UNAVAILABLE",
      }), { status: 200 });
    }
    return new Response(null, { status: 500 });
  });

  render(<BacktestsPage />);
  fireEvent.click(screen.getByRole("button", { name: "开始回测" }));

  expect(await screen.findByText(/任务执行失败.*PROVIDER_UNAVAILABLE/)).toBeTruthy();
  expect(fetch).toHaveBeenCalledWith("/api/v1/runs/run-2");
  expect(fetch).not.toHaveBeenCalledWith(expect.stringContaining("/api/v1/backtests/run-2"));
});

test("switches group without retaining another group's result", async () => {
  vi.mocked(fetch).mockImplementation(async (input) => {
    const url = String(input);
    if (url === "/api/v1/backtests") {
      return new Response(JSON.stringify({ run_id: "run-3" }), { status: 202 });
    }
    if (url === "/api/v1/runs/run-3") {
      return new Response(JSON.stringify({ run_id: "run-3", status: "succeeded" }));
    }
    const group = url.includes("group=B") ? "B" : "A";
    return new Response(JSON.stringify(resultResponse(group)));
  });

  render(<BacktestsPage />);
  fireEvent.click(screen.getByRole("button", { name: "开始回测" }));
  expect(await screen.findByText("A-only-metric")).toBeTruthy();

  fireEvent.click(screen.getByRole("button", { name: "分组 B" }));
  expect(screen.queryByText("A-only-metric")).toBeNull();
  expect(await screen.findByText("B-only-metric")).toBeTruthy();
});

test("loads next cursor pages for trades and rejected attempts", async () => {
  vi.mocked(fetch).mockImplementation(async (input) => {
    const url = String(input);
    if (url === "/api/v1/backtests") {
      return new Response(JSON.stringify({ run_id: "run-4" }), { status: 202 });
    }
    if (url === "/api/v1/runs/run-4") {
      return new Response(JSON.stringify({ run_id: "run-4", status: "succeeded" }));
    }
    if (url.includes("trade_cursor=trade-2")) {
      return new Response(JSON.stringify(resultResponse("A", {
        trades: { items: [{ order_id: "trade-2" }], next_cursor: null },
      })));
    }
    if (url.includes("rejected_cursor=reject-2")) {
      return new Response(JSON.stringify(resultResponse("A", {
        rejected_attempts: { items: [{ order_id: "reject-2" }], next_cursor: null },
      })));
    }
    return new Response(JSON.stringify(resultResponse("A", {
      trades: { items: [{ order_id: "trade-1" }], next_cursor: "trade-2" },
      rejected_attempts: { items: [{ order_id: "reject-1" }], next_cursor: "reject-2" },
    })));
  });

  render(<BacktestsPage />);
  fireEvent.click(screen.getByRole("button", { name: "开始回测" }));
  expect(await screen.findByText("trade-1")).toBeTruthy();

  fireEvent.click(screen.getByRole("button", { name: "加载更多成交" }));
  expect(await screen.findByText("trade-2")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "加载更多拒单" }));
  expect(await screen.findByText("reject-2")).toBeTruthy();
  expect(fetch).toHaveBeenCalledWith(expect.stringContaining("trade_cursor=trade-2"));
  expect(fetch).toHaveBeenCalledWith(expect.stringContaining("rejected_cursor=reject-2"));
});

function resultResponse(
  group: string,
  pages: Partial<{ trades: object; rejected_attempts: object }> = {},
): object {
  return {
    run_id: "result-run",
    status: "succeeded",
    strategy_version: "v2.12",
    input_manifest_hash: "manifest",
    created_at: "2026-07-20T00:00:00Z",
    groups: ["A", "B"].map((item) => ({
      group: item,
      data_grade: "research",
      llm_grade: "not_used",
      input_manifest_hash: "manifest",
      metrics: {},
    })),
    group,
    metrics: { [`${group}-only-metric`]: "1" },
    metric_details: {},
    warnings: [],
    equity_curve: {
      items: [{ trade_date: "2023-01-02", equity: "100", drawdown: "-0.02" }],
      next_cursor: null,
    },
    trades: { items: [], next_cursor: null },
    rejected_attempts: { items: [], next_cursor: null },
    ...pages,
  };
}
