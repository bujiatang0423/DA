export interface LegacyImportSource {
  source_id: string;
  label: string;
}

export interface LegacyImportPreview {
  source_id: string;
  portfolio_id: string;
  effective_at: string;
  current_position_count: number;
  historical_position_count: number;
  source_file_count: number;
  quality_tags: string[];
  confirmation_token: string;
}

export interface LegacyImportResult {
  batch_id: string;
  portfolio_id: string;
  effective_at: string;
  manifest_sha256: string;
  raw_file_count: number;
  opening_position_count: number;
  historical_snapshot_count: number;
  idempotent: boolean;
  holding_analysis: {
    portfolio_id: string;
    as_of_time: string;
    import_batch_id: string;
    import_manifest_sha256: string;
    href: string;
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    throw new Error(`request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const legacyImportApi = {
  sources: (): Promise<{ items: LegacyImportSource[] }> => request("/api/v1/legacy-imports/sources"),
  preview: (body: {
    source_id: string;
    portfolio_id: string;
    effective_at: string;
  }): Promise<LegacyImportPreview> => request("/api/v1/legacy-imports/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }),
  confirm: (body: {
    source_id: string;
    portfolio_id: string;
    effective_at: string;
    confirmation_token: string;
  }): Promise<LegacyImportResult> => request("/api/v1/legacy-imports/confirm", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }),
  result: (batchId: string): Promise<LegacyImportResult> =>
    request(`/api/v1/legacy-imports/${encodeURIComponent(batchId)}`),
};
