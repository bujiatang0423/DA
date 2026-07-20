import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { RunsPage } from "./RunsPage";
import { listRuns, retryRun } from "../../shared/api/client";

vi.mock("../../shared/api/client", () => ({ listRuns: vi.fn(), retryRun: vi.fn() }));

beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

test("renders runs returned by the API", async () => {
  vi.mocked(listRuns).mockResolvedValue({
    items: [{ run_id: "r1", kind: "backtest", status: "succeeded" }],
    next_cursor: null,
  } as never);
  render(<RunsPage />);
  await waitFor(() => expect(screen.getByText("backtest · succeeded")).toBeTruthy());
});

test("shows result and artifact links only when the run kind has an available result route", async () => {
  vi.mocked(listRuns).mockResolvedValue({
    items: [
      {
        run_id: "candidate-1",
        kind: "candidate_recommendation",
        status: "succeeded",
        submitted_at: "2026-07-19T09:00:00+08:00",
        links: {
          self: "/api/v1/runs/candidate-1",
          result: "/api/v1/candidates/candidate-1",
          artifacts: "/api/v1/runs/candidate-1/artifacts",
        },
      },
      {
        run_id: "holding-1",
        kind: "holding_analysis",
        status: "succeeded",
        submitted_at: "2026-07-19T09:01:00+08:00",
        links: {
          self: "/api/v1/runs/holding-1",
          result: "/api/v1/holding-analyses/holding-1",
          artifacts: "/api/v1/runs/holding-1/artifacts",
        },
      },
      {
        run_id: "backtest-1",
        kind: "backtest",
        status: "succeeded",
        submitted_at: "2026-07-19T09:02:00+08:00",
        links: {
          self: "/api/v1/runs/backtest-1",
          artifacts: "/api/v1/runs/backtest-1/artifacts",
          result: null,
        },
      },
    ],
    next_cursor: null,
  });

  render(<RunsPage />);

  const candidateResult = await screen.findByRole("link", { name: "查看候选结果" });
  expect(candidateResult.getAttribute("href")).toBe("/api/v1/candidates/candidate-1");
  expect(screen.getByRole("link", { name: "查看持仓结果" }).getAttribute("href")).toBe(
    "/api/v1/holding-analyses/holding-1",
  );
  expect(screen.getAllByRole("link", { name: "查看产物" })).toHaveLength(3);
  expect(screen.queryByRole("link", { name: "查看回测结果" })).toBeNull();
});

test("shows safe execution status fields without rendering raw failure text", async () => {
  vi.mocked(listRuns).mockResolvedValue({
    items: [{
      run_id: "backtest-1",
      kind: "backtest",
      status: "failed",
      submitted_at: "2026-07-19T09:00:00+08:00",
      links: { self: "/api/v1/runs/backtest-1" },
      stage: "loading_market_data",
      progress: 40,
      heartbeat_at: "2026-07-19T09:05:00+08:00",
      retry_count: 2,
      error_code: "PROVIDER_UNAVAILABLE",
      error_message: "upstream diagnostic: connection reset",
    }],
    next_cursor: null,
  } as never);

  render(<RunsPage />);

  await waitFor(() => {
    expect(document.body.textContent).toContain("loading_market_data");
  });
  expect(document.body.textContent).toContain("40%");
  expect(document.body.textContent).toContain("心跳");
  expect(document.body.textContent).toContain("PROVIDER_UNAVAILABLE");
  expect(document.body.textContent).toContain("已重试 2 次");
  expect(document.body.textContent).not.toContain("connection reset");
});

test("retries only failed runs and refreshes the safe run state", async () => {
  vi.mocked(listRuns)
    .mockResolvedValueOnce({
      items: [{
        run_id: "failed-1",
        kind: "backtest",
        status: "failed",
        submitted_at: "2026-07-20T09:00:00Z",
        links: { self: "/api/v1/runs/failed-1" },
        retry_count: 0,
        error_code: "PROVIDER_UNAVAILABLE",
      }],
      next_cursor: null,
    } as never)
    .mockResolvedValueOnce({
      items: [{
        run_id: "failed-1",
        kind: "backtest",
        status: "queued",
        submitted_at: "2026-07-20T09:00:00Z",
        links: { self: "/api/v1/runs/failed-1" },
        retry_count: 1,
      }],
      next_cursor: null,
    } as never);
  vi.mocked(retryRun).mockResolvedValue({ run_id: "failed-1", status: "queued" } as never);

  render(<RunsPage />);
  fireEvent.click(await screen.findByRole("button", { name: "重试任务" }));

  await waitFor(() => expect(retryRun).toHaveBeenCalledWith("failed-1"));
  await waitFor(() => expect(screen.getByText("已重试 1 次")).toBeTruthy());
  expect(screen.queryByRole("button", { name: "重试任务" })).toBeNull();
});
