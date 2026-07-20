import type { RunDetail, RunPage } from "../../generated/schema";
export type { RunDetail } from "../../generated/schema";

export interface RunRef {
  run_id: string;
  kind: string;
  status: string;
  submitted_at: string;
  links: RunDetail["links"];
  auto_trade_enabled: false;
  human_confirm_required: true;
}

export async function listRuns(cursor?: string): Promise<RunPage> {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
  const response = await fetch(`/api/v1/runs${query}`);
  if (!response.ok) throw new Error(`request failed: ${response.status}`);
  return response.json() as Promise<RunPage>;
}

export async function retryRun(runId: string): Promise<RunRef> {
  const response = await fetch(`/api/v1/runs/${encodeURIComponent(runId)}/retry`, {
    method: "POST",
  });
  if (!response.ok) throw new Error("retry request was rejected");
  return response.json() as Promise<RunRef>;
}
