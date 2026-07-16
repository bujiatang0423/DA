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
