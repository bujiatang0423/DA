export interface BacktestRunRef {
  run_id: string;
  status: string;
  auto_trade_enabled: false;
  human_confirm_required: true;
}

export interface BacktestGroup {
  group: string;
  data_grade: string;
  llm_grade: string;
  input_manifest_hash: string;
  metrics: Record<string, string | number | null>;
}

export interface CursorPage {
  items: Array<Record<string, string>>;
  next_cursor: string | null;
}

export interface BacktestResult {
  run_id: string;
  status: string;
  strategy_version: string;
  input_manifest_hash: string;
  created_at: string;
  groups: BacktestGroup[];
  group: string;
  metrics: Record<string, string | number | null>;
  metric_details: Record<string, unknown>;
  warnings: string[];
  equity_curve: CursorPage;
  trades: CursorPage;
  rejected_attempts: CursorPage;
}

export class BacktestApiError extends Error {
  constructor(readonly status: number) {
    super(`回测请求失败（${status}）`);
  }
}

export interface BacktestRequest {
  strategy_version: string;
  start_date: string;
  end_date: string;
  initial_cash: string;
  groups: string[];
}

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new BacktestApiError(response.status);
  }
  return response.json() as Promise<T>;
}

export async function submitBacktest(request: BacktestRequest): Promise<BacktestRunRef> {
  const response = await fetch("/api/v1/backtests", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "Idempotency-Key": [
        "backtest",
        request.strategy_version,
        request.start_date,
        request.end_date,
      ].join(":"),
    },
    body: JSON.stringify(request),
  });
  return parse<BacktestRunRef>(response);
}

export async function getBacktest(runId: string, group: string): Promise<BacktestResult> {
  const response = await fetch(`/api/v1/backtests/${encodeURIComponent(runId)}?group=${group}`);
  return parse<BacktestResult>(response);
}
