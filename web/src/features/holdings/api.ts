export interface HoldingRequest {
  portfolio_id: string;
  as_of_time: string;
  import_batch_id?: string;
  import_manifest_sha256?: string;
}

export interface HoldingFactors {
  p: string;
  f: string;
  r: string;
  t: string;
  v: string;
  s: string;
  percentile_rank: string;
}

export interface HoldingItem {
  security_id: string;
  security_name: string;
  origin: string;
  strategy_book: string | null;
  quantity: number;
  available_to_sell: number;
  average_cost: string;
  close: string;
  market_state: string;
  factors: HoldingFactors;
  r_multiple: string | null;
  effective_stop: string | null;
  proposed_effective_stop: string | null;
  advised_action: string;
  planned_quantity: number;
  pending_target_action: string | null;
  reason_codes: string[];
  quality_codes: string[];
  evidence_refs: string[];
}

export interface HoldingResult {
  run_id: string;
  portfolio_id: string;
  as_of_time: string;
  strategy_version: "v2.12";
  manifest_hash: string;
  data_grade: string;
  llm_grade: string;
  auto_trade_enabled: false;
  human_confirm_required: true;
  summary: {
    equity: string;
    cash: string;
    gross_exposure_pct: string;
    portfolio_risk_pct: string;
    market_state: string;
  };
  items: HoldingItem[];
}

export interface PositionItem {
  security_id: string;
  origin: string;
  strategy_book: string | null;
  quantity: number;
  available_to_sell: number;
  average_cost: string;
  effective_stop: string | null;
  highest_close: string | null;
  entry_score: string | null;
  initial_risk_per_share: string | null;
  add_count: number;
}

export interface PositionPage {
  portfolio_id: string;
  as_of_time: string;
  version: number;
  cash: string;
  equity: string;
  items: PositionItem[];
  import_provenance: {
    batch_id: string;
    manifest_sha256: string;
  } | null;
}

export interface ImportProvenanceRequest {
  batchId: string;
  manifestSha256: string;
}

export interface PositionCorrection {
  portfolio_id: string;
  expected_version: number;
  reason: string;
  positions: Array<{
    security_id: string;
    quantity: number;
    average_cost: string;
    effective_at: string;
  }>;
}

export interface ManualFill {
  portfolio_id: string;
  expected_version: number;
  security_id: string;
  side: "buy" | "sell";
  quantity: number;
  price: string;
  fee: string;
  executed_at: string;
}

export interface RunRef {
  run_id: string;
  kind: string;
  status: string;
  submitted_at: string;
  auto_trade_enabled: false;
  human_confirm_required: true;
  links: { self: string; artifacts?: string | null };
}

export class HoldingApiError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(`request failed: ${status}`);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    throw new HoldingApiError(response.status);
  }
  return response.json() as Promise<T>;
}

function queryForPortfolio(
  portfolioId: string,
  asOfTime?: string,
  importProvenance?: ImportProvenanceRequest,
): string {
  const query = new URLSearchParams({ portfolio_id: portfolioId });
  if (asOfTime) {
    query.set("as_of_time", asOfTime);
  }
  if (importProvenance) {
    query.set("import_batch_id", importProvenance.batchId);
    query.set("import_manifest_sha256", importProvenance.manifestSha256);
  }
  return `?${query.toString()}`;
}

export const holdingApi = {
  positions: (
    portfolioId: string,
    asOfTime?: string,
    importProvenance?: ImportProvenanceRequest,
  ): Promise<PositionPage> =>
    request<PositionPage>(
      `/api/v1/portfolio/positions${queryForPortfolio(
        portfolioId,
        asOfTime,
        importProvenance,
      )}`,
    ),
  correctPositions: (requestBody: PositionCorrection): Promise<PositionPage> =>
    request<PositionPage>("/api/v1/portfolio/positions", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody),
    }),
  recordManualFill: (requestBody: ManualFill): Promise<PositionPage> =>
    request<PositionPage>("/api/v1/portfolio/fills", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody),
    }),
  latest: async (portfolioId: string, asOfTime?: string): Promise<HoldingResult | null> => {
    try {
      return await request<HoldingResult>(
        `/api/v1/holding-analyses/latest${queryForPortfolio(portfolioId, asOfTime)}`,
      );
    } catch (error) {
      if (error instanceof HoldingApiError && error.status === 404) {
        return null;
      }
      throw error;
    }
  },
  submit: (
    requestBody: HoldingRequest,
    idempotencyKey: string,
  ): Promise<RunRef> =>
    request<RunRef>("/api/v1/holding-analyses", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
      },
      body: JSON.stringify(requestBody),
    }),
};
