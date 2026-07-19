export interface CandidateResult {
  run_id?: string;
  as_of_time?: string;
  market_state?: string;
  market_confidence?: string;
  data_grade?: string;
  llm_grade?: string;
  items?: CandidateItem[];
  quality_codes?: string[];
  auto_trade_enabled?: false;
  human_confirm_required?: true;
}

export interface CandidateItem {
  security_id: string;
  security_name?: string;
  bucket: string;
  state?: string;
  percentile_rank?: number;
  factors?: Record<string, number>;
  planned_quantity?: number;
  initial_stop?: string | number | null;
  trigger_condition?: string;
  invalidation_condition?: string;
  reason_codes?: string[];
  quality_codes?: string[];
  evidence_refs?: string[];
}

export async function submitCandidate(asOfTime: string): Promise<CandidateResult> {
  const response = await fetch("/api/v1/candidates", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ as_of_time: asOfTime }) });
  if (!response.ok) throw new Error(`候选推荐请求失败（${response.status}）`);
  const run = await response.json() as { run_id: string };
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const statusResponse = await fetch(`/api/v1/runs/${run.run_id}`);
    if (!statusResponse.ok) throw new Error(`读取候选任务失败（${statusResponse.status}）`);
    const status = await statusResponse.json() as { status: string };
    if (status.status === "succeeded") {
      const resultResponse = await fetch(`/api/v1/candidates/${run.run_id}`);
      if (!resultResponse.ok) throw new Error(`读取候选结果失败（${resultResponse.status}）`);
      return resultResponse.json() as Promise<CandidateResult>;
    }
    if (status.status === "failed" || status.status === "cancelled") {
      throw new Error(`候选任务${status.status === "failed" ? "失败" : "已取消"}`);
    }
    await new Promise((resolve) => window.setTimeout(resolve, 500));
  }
  throw new Error("候选任务超时，请到运行中心查看状态");
}
