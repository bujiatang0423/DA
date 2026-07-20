import type { RunDetail, RunPage } from "../../generated/schema";
export type { RunDetail } from "../../generated/schema";
export async function listRuns(cursor?: string): Promise<RunPage> {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
  const response = await fetch(`/api/v1/runs${query}`);
  if (!response.ok) throw new Error(`request failed: ${response.status}`);
  return response.json() as Promise<RunPage>;
}

export async function retryRun(runId: string): Promise<RunDetail> {
  const response = await fetch(`/api/v1/runs/${encodeURIComponent(runId)}/retry`, {
    method: "POST",
  });
  if (!response.ok) throw new Error("retry request was rejected");
  return response.json() as Promise<RunDetail>;
}
