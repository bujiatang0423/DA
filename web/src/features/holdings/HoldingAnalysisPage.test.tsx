import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { HoldingAnalysisPage } from "./HoldingAnalysisPage";
import {
  HoldingApiError,
  holdingApi,
  type HoldingResult,
  type PositionPage,
  type RunRef,
} from "./api";

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  holdingApi: {
    positions: vi.fn(),
    correctPositions: vi.fn(),
    recordManualFill: vi.fn(),
    latest: vi.fn(),
    submit: vi.fn(),
  },
}));

const portfolioId = "default";
const positionPageFixture: PositionPage = {
  portfolio_id: portfolioId,
  as_of_time: "2026-07-17T15:00:00+08:00",
  version: 7,
  cash: "350000",
  equity: "1000000",
  import_provenance: null,
  items: [
    {
      security_id: "000001.SZ",
      origin: "legacy_opening_balance",
      strategy_book: null,
      quantity: 500,
      available_to_sell: 0,
      average_cost: "10.20",
      effective_stop: "9.50",
      highest_close: "11.00",
      entry_score: null,
      initial_risk_per_share: null,
      add_count: 0,
    },
  ],
};

const holdingResultFixture: HoldingResult = {
  run_id: "holding-run-1",
  portfolio_id: portfolioId,
  as_of_time: "2026-07-17T15:00:00+08:00",
  strategy_version: "v2.12",
  manifest_hash: "manifest-sha256-abc123",
  data_grade: "research",
  llm_grade: "not_used",
  auto_trade_enabled: false,
  human_confirm_required: true,
  summary: {
    equity: "1000000",
    cash: "350000",
    gross_exposure_pct: "65.00",
    portfolio_risk_pct: "1.25",
    market_state: "neutral",
  },
  items: [
    {
      security_id: "000001.SZ",
      security_name: "Ping An Bank",
      origin: "legacy_opening_balance",
      strategy_book: null,
      quantity: 500,
      available_to_sell: 0,
      average_cost: "10.20",
      close: "9.40",
      market_state: "neutral",
      factors: {
        p: "70",
        f: "65",
        r: "60",
        t: "55",
        v: "50",
        s: "62.5",
        percentile_rank: "0.80",
      },
      r_multiple: "-0.80",
      advised_action: "exit_all",
      planned_quantity: 0,
      pending_target_action: null,
      effective_stop: "9.50",
      proposed_effective_stop: "9.50",
      reason_codes: ["HARD_STOP"],
      quality_codes: ["LLM_FACTOR_INVALID"],
      evidence_refs: ["market-close:000001.SZ:2026-07-17"],
    },
  ],
};

const runRefFixture: RunRef = {
  run_id: "run-holding-2",
  kind: "holding_analysis",
  status: "queued",
  submitted_at: "2026-07-17T15:00:00+08:00",
  auto_trade_enabled: false,
  human_confirm_required: true,
  links: {
    self: "/api/v1/runs/run-holding-2",
    artifacts: "/api/v1/runs/run-holding-2/artifacts",
  },
};

function renderPage(): void {
  render(<HoldingAnalysisPage />);
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(holdingApi.positions).mockResolvedValue(positionPageFixture);
  vi.mocked(holdingApi.latest).mockResolvedValue(holdingResultFixture);
});

afterEach(() => {
  cleanup();
  window.history.replaceState({}, "", "/holdings");
});

test("renders risk-first, legacy, and manual-only semantics", async () => {
  renderPage();

  expect(await screen.findByText("全部退出")).toBeTruthy();
  expect(screen.getByText("可卖数量：0")).toBeTruthy();
  expect(screen.getByText("T+1 锁定，退出待执行")).toBeTruthy();
  expect(screen.getByText("历史期初持仓，未追认策略账本")).toBeTruthy();
  expect(screen.getByText("仅供人工确认，不自动下单")).toBeTruthy();
  expect(screen.getByLabelText("PIT 证据").textContent).toContain(
    "market-close:000001.SZ:2026-07-17",
  );
});

test("renders a not-yet-run state when latest analysis is absent", async () => {
  vi.mocked(holdingApi.latest).mockResolvedValue(null);
  renderPage();

  expect(await screen.findByText("尚未运行持仓分析。")).toBeTruthy();
});

test("submits an asynchronous analysis for the loaded portfolio", async () => {
  vi.mocked(holdingApi.submit).mockResolvedValue(runRefFixture);
  renderPage();

  fireEvent.click(await screen.findByRole("button", { name: "分析当前持仓" }));

  await waitFor(() => expect(holdingApi.submit).toHaveBeenCalledOnce());
  expect(holdingApi.submit).toHaveBeenCalledWith(
    expect.objectContaining({ portfolio_id: portfolioId }),
    expect.any(String),
  );
  expect(
    screen.getByRole("link", { name: "查看运行进度" }).getAttribute("href"),
  ).toBe(`/runs/${runRefFixture.run_id}`);
});

test("uses explicit imported portfolio context only after manual analysis submission", async () => {
  window.history.pushState(
    {},
    "",
    "/holdings?portfolio_id=main&as_of_time=2026-07-19T09%3A00%3A00Z&batch_id=batch-1&manifest_sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  );
  vi.mocked(holdingApi.positions).mockResolvedValue({
    ...positionPageFixture,
    portfolio_id: "main",
    as_of_time: "2026-07-19T09:00:00Z",
    import_provenance: {
      batch_id: "batch-1",
      manifest_sha256: "a".repeat(64),
    },
  });
  vi.mocked(holdingApi.submit).mockResolvedValue(runRefFixture);

  renderPage();

  await screen.findByText("导入批次：batch-1");
  expect(holdingApi.positions).toHaveBeenCalledWith("main", "2026-07-19T09:00:00Z", {
    batchId: "batch-1",
    manifestSha256: "a".repeat(64),
  });
  expect(holdingApi.latest).toHaveBeenCalledWith("main", "2026-07-19T09:00:00Z");
  expect(screen.getByText("尚未运行持仓分析。")).toBeTruthy();
  expect(screen.queryByText("全部退出")).toBeNull();
  expect(holdingApi.submit).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "分析当前持仓" }));

  await waitFor(() => expect(holdingApi.submit).toHaveBeenCalledOnce());
  expect(holdingApi.submit).toHaveBeenCalledWith(
    { portfolio_id: "main", as_of_time: "2026-07-19T09:00:00Z" },
    "holding:main:2026-07-19T09:00:00Z",
  );
});

test("masks a tampered import URL when the server rejects its provenance", async () => {
  const tamperedManifest = "b".repeat(64);
  window.history.pushState(
    {},
    "",
    `/holdings?portfolio_id=main&as_of_time=2026-07-19T09%3A00%3A00Z&batch_id=batch-1&manifest_sha256=${tamperedManifest}`,
  );
  vi.mocked(holdingApi.positions).mockRejectedValue(new HoldingApiError(409));

  renderPage();

  expect((await screen.findByRole("alert")).textContent).toContain("持仓分析数据加载失败");
  expect(document.body.textContent).not.toContain("导入批次：batch-1");
  expect(document.body.textContent).not.toContain(tamperedManifest);
  expect(holdingApi.submit).not.toHaveBeenCalled();
});

test("records the user-entered actual execution time", async () => {
  vi.mocked(holdingApi.recordManualFill).mockResolvedValue(positionPageFixture);
  renderPage();

  fireEvent.click(await screen.findByRole("button", { name: "记录实际成交" }));
  fireEvent.change(screen.getByLabelText("实际成交时间"), {
    target: { value: "2026-07-18T09:31" },
  });
  fireEvent.change(screen.getByLabelText("实际成交价"), {
    target: { value: "10.35" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存实际成交" }));

  await waitFor(() =>
    expect(holdingApi.recordManualFill).toHaveBeenCalledOnce(),
  );
  expect(holdingApi.recordManualFill).toHaveBeenCalledWith(
    expect.objectContaining({
      portfolio_id: portfolioId,
      executed_at: new Date("2026-07-18T09:31").toISOString(),
    }),
  );
});

test("keeps a correction form open and reloads positions after a version conflict", async () => {
  vi.mocked(holdingApi.correctPositions).mockRejectedValue(
    new HoldingApiError(409),
  );
  renderPage();

  fireEvent.click(await screen.findByRole("button", { name: "校正持仓" }));
  fireEvent.change(screen.getByLabelText("校正原因"), {
    target: { value: "broker reconciliation" },
  });
  fireEvent.click(screen.getByRole("button", { name: "确认人工校正" }));

  expect(
    await screen.findByText(
      "持仓版本已变化，已重新加载最新持仓。请核对后重新提交。",
    ),
  ).toBeTruthy();
  expect(screen.getByRole("button", { name: "确认人工校正" })).toBeTruthy();
  await waitFor(() => expect(holdingApi.positions).toHaveBeenCalledTimes(2));
});
