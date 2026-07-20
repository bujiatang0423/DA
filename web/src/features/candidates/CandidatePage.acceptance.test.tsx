import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { CandidatePage } from "./CandidatePage";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

test("groups executable watchlist and excluded items with grades and safe evidence", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(new Response(JSON.stringify({ run_id: "run-1" }), { status: 202 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ status: "succeeded" }), { status: 200 }))
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          data_grade: "research",
          llm_grade: "not_used",
          items: [
            {
              security_id: "600000",
              security_name: "Exec",
              bucket: "executable",
              evidence_refs: ["pit:bar:abc"],
            },
            {
              security_id: "600001",
              security_name: "Watch",
              bucket: "watchlist",
              evidence_refs: [],
            },
            {
              security_id: "600002",
              security_name: "Excluded",
              bucket: "excluded",
              evidence_refs: ["pit:policy:def"],
            },
          ],
        }),
        { status: 200 },
      ),
    );

  render(<CandidatePage />);
  fireEvent.click(screen.getByRole("button", { name: "生成候选" }));

  await waitFor(() => expect(screen.getByRole("heading", { name: "可执行" })).toBeTruthy());
  expect(screen.getByRole("heading", { name: "观察列表" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "排除" })).toBeTruthy();
  expect(screen.getByText("数据等级：research")).toBeTruthy();
  expect(screen.getByText("研究级数据，不代表正式历史验证")).toBeTruthy();
  expect(screen.getByText("LLM 等级：not_used")).toBeTruthy();
  expect(screen.getByText("pit:bar:abc")).toBeTruthy();
  expect(screen.getByText("仅供人工确认，不自动下单")).toBeTruthy();
  expect(screen.queryByText("自动下单")).toBeNull();
});
