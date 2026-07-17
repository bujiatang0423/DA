export interface CandidateResult { run_id?: string; as_of_time?: string; market_state?: string; market_confidence?: string; items?: CandidateItem[]; quality_codes?: string[]; auto_trade_enabled?: boolean; human_confirm_required?: boolean; [key: string]: unknown }
export interface CandidateItem { security_id: string; security_name?: string; bucket: string; state?: string; percentile_rank?: number; factors?: Record<string, number>; trigger_condition?: string; invalidation_condition?: string; reason_codes?: string[] }

export async function submitCandidate(asOfTime: string): Promise<CandidateResult> {
  const response = await fetch("/api/v1/candidates", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ as_of_time: asOfTime }) });
  if (!response.ok) throw new Error(`候选推荐请求失败（${response.status}）`);
  return response.json() as Promise<CandidateResult>;
}
