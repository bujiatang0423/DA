import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { LegacyImportPage } from "./LegacyImportPage";
import { legacyImportApi } from "./api";

vi.mock("./api", () => ({
  legacyImportApi: {
    sources: vi.fn(),
    preview: vi.fn(),
    confirm: vi.fn(),
    result: vi.fn(),
  },
}));

beforeEach(() => vi.clearAllMocks());

test("requires explicit confirmation before showing a frozen import batch", async () => {
  vi.mocked(legacyImportApi.sources).mockResolvedValue({
    items: [{ source_id: "broker-a", label: "broker-a" }],
  });
  vi.mocked(legacyImportApi.preview).mockResolvedValue({
    source_id: "broker-a",
    portfolio_id: "main",
    effective_at: "2026-07-19T09:00:00+08:00",
    current_position_count: 1,
    historical_position_count: 2,
    source_file_count: 3,
    quality_tags: ["checksum_mismatch"],
    confirmation_token: "once",
  });
  vi.mocked(legacyImportApi.confirm).mockResolvedValue({
    batch_id: "batch-1",
    manifest_sha256: "a".repeat(64),
    raw_file_count: 3,
    opening_position_count: 1,
    historical_snapshot_count: 2,
    idempotent: false,
  });

  render(<LegacyImportPage />);
  await screen.findByRole("option", { name: "broker-a" });
  fireEvent.change(screen.getByLabelText("生效时间"), {
    target: { value: "2026-07-19T09:00" },
  });
  fireEvent.click(screen.getByRole("button", { name: "预览导入" }));

  await waitFor(() => expect(document.body.textContent).toContain("checksum_mismatch"));
  expect(legacyImportApi.confirm).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "确认冻结并导入" }));

  await waitFor(() => expect(screen.getByText("batch-1")).toBeTruthy());
  expect(screen.getByText("首次导入")).toBeTruthy();
  expect(screen.getByText("不自动触发持仓分析")).toBeTruthy();
});
