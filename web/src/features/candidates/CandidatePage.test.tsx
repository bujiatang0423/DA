import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { CandidatePage } from "./CandidatePage";

beforeEach(() => { vi.stubGlobal("fetch", vi.fn()); });
test("submits snapshot and renders candidate rows", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(new Response(JSON.stringify({ run_id: "run-1" }), { status: 202 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ status: "succeeded" }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ market_state: "risk_on", items: [{ security_id: "600000", bucket: "executable", state: "selected", percentile_rank: 0.8 }] }), { status: 200 }));
  render(<CandidatePage />); fireEvent.click(screen.getByRole("button", { name: "生成候选" }));
  await waitFor(() => expect(screen.getByText("600000")).toBeTruthy());
  expect(screen.getAllByText("可执行").length).toBeGreaterThan(0);
});
