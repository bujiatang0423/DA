import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

interface FixtureRun {
  run_id: string;
  kind: string;
  status: string;
  submitted_at: string;
  auto_trade_enabled: false;
  human_confirm_required: true;
  progress: number;
  retry_count: number;
  links: { self: string; artifacts: string; result: string };
}

const E2E_TIME = "2026-07-20T00:00:00Z";

function sendJson(response: import("node:http").ServerResponse, status: number, body: unknown): void {
  response.writeHead(status, { "content-type": "application/json" });
  response.end(JSON.stringify(body));
}

function fixtureApi(): Plugin {
  const runs = new Map<string, FixtureRun>();
  const addRun = (runId: string, kind: string, result: string): FixtureRun => {
    const run: FixtureRun = {
      run_id: runId, kind, status: "succeeded", submitted_at: E2E_TIME,
      auto_trade_enabled: false, human_confirm_required: true, progress: 100, retry_count: 0,
      links: { self: `/api/v1/runs/${runId}`, artifacts: `/api/v1/runs/${runId}/artifacts`, result },
    };
    runs.set(runId, run);
    return run;
  };
  const candidateResult = {
    run_id: "candidate-e2e", as_of_time: E2E_TIME, market_state: "strengthened",
    market_confidence: "0.91", data_grade: "research", llm_grade: "not_used",
    auto_trade_enabled: false, human_confirm_required: true,
    items: [{
      security_id: "600000.SH", security_name: "浦发银行", bucket: "executable",
      factors: { p: 0.8, f: 0.7, r: 0.9, t: 0.8, v: 0.6, s: 0.8 },
      trigger_condition: "收盘确认后人工复核", invalidation_condition: "金融风险信号",
      reason_codes: ["FINANCIAL_RED_FLAG"], quality_codes: ["PIT_FROZEN"],
      evidence_refs: ["e2e-candidate-evidence"],
    }],
  };
  const positions = {
    portfolio_id: "default", as_of_time: E2E_TIME, version: 1, cash: "500000", equity: "1000000",
    items: [{
      security_id: "600000.SH", origin: "manual", strategy_book: "core", quantity: 100,
      available_to_sell: 100, average_cost: "10.00", effective_stop: "9.50",
      highest_close: "10.00", entry_score: "0.80", initial_risk_per_share: "0.50", add_count: 0,
    }],
    import_provenance: null,
  };
  const backtestResult = {
    run_id: "backtest-e2e", status: "succeeded", strategy_version: "v2.12",
    input_manifest_hash: "e2e-frozen-manifest", created_at: E2E_TIME,
    groups: [{
      group: "A", data_grade: "research", llm_grade: "reconstructed",
      input_manifest_hash: "e2e-frozen-manifest", metrics: { profit_factor: "1.10" },
    }],
    group: "A", metrics: { profit_factor: "1.10", closed_trade_count: 1 },
    metric_details: { acceptance_gates: [], values: {} }, warnings: ["research_only"],
    equity_curve: {
      items: [{ trade_date: "2025-01-02", equity: "1000000" }, { trade_date: "2025-01-03", equity: "1010000" }],
      next_cursor: null,
    },
    trades: { items: [{ order_id: "e2e-order", side: "buy", quantity: "100" }], next_cursor: null },
    rejected_attempts: { items: [], next_cursor: null },
  };
  return {
    name: "local-e2e-fixture-api",
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const path = new URL(request.url ?? "/", "http://127.0.0.1").pathname;
        if (!path.startsWith("/api/v1/")) {
          next();
          return;
        }
        if (request.method === "POST" && path === "/api/v1/candidates") {
          sendJson(response, 202, addRun("candidate-e2e", "candidate_recommendation", path));
          return;
        }
        if (request.method === "GET" && path === "/api/v1/candidates/candidate-e2e") {
          sendJson(response, 200, candidateResult);
          return;
        }
        if (request.method === "GET" && path === "/api/v1/portfolio/positions") {
          sendJson(response, 200, positions);
          return;
        }
        if (request.method === "GET" && path === "/api/v1/holding-analyses/latest") {
          sendJson(response, 404, { code: "HOLDING_ANALYSIS_NOT_FOUND" });
          return;
        }
        if (request.method === "POST" && path === "/api/v1/holding-analyses") {
          sendJson(response, 202, addRun("holding-e2e", "holding_analysis", path));
          return;
        }
        if (request.method === "POST" && path === "/api/v1/backtests") {
          sendJson(response, 202, addRun("backtest-e2e", "backtest", path));
          return;
        }
        if (request.method === "GET" && path === "/api/v1/backtests/backtest-e2e") {
          sendJson(response, 200, backtestResult);
          return;
        }
        if (request.method === "GET" && path === "/api/v1/runs") {
          sendJson(response, 200, { items: [...runs.values()], next_cursor: null });
          return;
        }
        if (request.method === "GET" && path.startsWith("/api/v1/runs/")) {
          const run = runs.get(path.split("/").at(-1) ?? "");
          if (run) {
            sendJson(response, 200, run);
            return;
          }
        }
        sendJson(response, 404, { code: "NOT_FOUND" });
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), ...(process.env.DA_E2E_FIXTURES === "1" ? [fixtureApi()] : [])],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
  test: { environment: "jsdom", exclude: ["node_modules/**", "e2e/**"] },
});
