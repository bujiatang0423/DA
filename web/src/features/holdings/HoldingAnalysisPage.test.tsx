import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { HoldingAnalysisPage } from "./HoldingAnalysisPage";
import { holdingApi, type HoldingResult, type PositionPage, type RunRef } from "./api";

vi.mock("./api", () => ({
    holdingApi: {
        positions: vi.fn(),
        correctPositions: vi.fn(),
        recordManualFill: vi.fn(),
        latest: vi.fn(),
        submit: vi.fn(),
    },
}));

const positionPageFixture: PositionPage = {
    portfolio_id: "default",
    as_of_time: "2026-07-17T15:00:00+08:00",
    version: 7,
    cash: "350000",
    equity: "1000000",
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
    portfolio_id: "default",
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
            security_name: "平安银行",
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
    const client = new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
        <QueryClientProvider client={client}>
            <HoldingAnalysisPage />
        </QueryClientProvider>,
    );
}

beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(holdingApi.positions).mockResolvedValue(positionPageFixture);
    vi.mocked(holdingApi.latest).mockResolvedValue(holdingResultFixture);
});

afterEach(() => {
    cleanup();
});

test("shows risk action, T+1 quantity, evidence, and legacy semantics", async () => {
    renderPage();

    expect(await screen.findByText("全部退出")).toBeTruthy();
    expect(screen.getByText("可卖数量：0")).toBeTruthy();
    expect(screen.getByText("T+1 锁定，退出待执行")).toBeTruthy();
    expect(screen.getByText("历史期初持仓，未追认策略账本")).toBeTruthy();
    expect(screen.getByText("仅供人工确认，不自动下单")).toBeTruthy();
    expect(screen.getByText("market-close:000001.SZ:2026-07-17")).toBeTruthy();
});

test("submits an asynchronous analysis", async () => {
    vi.mocked(holdingApi.submit).mockResolvedValue(runRefFixture);
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "分析当前持仓" }));

    await waitFor(() => expect(holdingApi.submit).toHaveBeenCalledOnce());
    const link = screen.getByRole("link", { name: "查看运行进度" });
    expect(link.getAttribute("href")).toBe(`/runs/${runRefFixture.run_id}`);
});

test("sends version and audit reason for a position correction", async () => {
    vi.mocked(holdingApi.correctPositions).mockResolvedValue({
        ...positionPageFixture,
        version: 8,
    });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "校正持仓" }));
    fireEvent.change(screen.getByLabelText("校正原因"), {
        target: { value: "核对券商对账单后修正数量" },
    });
    fireEvent.click(screen.getByRole("button", { name: "确认人工校正" }));

    await waitFor(() =>
        expect(holdingApi.correctPositions).toHaveBeenCalledWith(
            expect.objectContaining({ expected_version: positionPageFixture.version }),
        ),
    );
});

test("records actual fill price and fee", async () => {
    vi.mocked(holdingApi.recordManualFill).mockResolvedValue({
        ...positionPageFixture,
        version: 8,
    });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "记录实际成交" }));
    fireEvent.change(screen.getByLabelText("实际成交价"), {
        target: { value: "10.35" },
    });
    fireEvent.change(screen.getByLabelText("实际费用"), {
        target: { value: "5.00" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存实际成交" }));

    await waitFor(() =>
        expect(holdingApi.recordManualFill).toHaveBeenCalledWith(
            expect.objectContaining({ price: "10.35", fee: "5.00" }),
        ),
    );
});
