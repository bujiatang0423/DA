import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { RunsPage } from "./RunsPage";
import { listRuns } from "../../shared/api/client";

vi.mock("../../shared/api/client", () => ({ listRuns: vi.fn() }));

beforeEach(() => vi.clearAllMocks());

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
