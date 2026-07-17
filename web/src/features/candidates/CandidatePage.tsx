import { useState } from "react";
import { submitCandidate, type CandidateResult } from "./api";
import { bucketLabel } from "./viewModel";

export function CandidatePage(): JSX.Element {
  const [asOfTime, setAsOfTime] = useState(() => new Date().toISOString().slice(0, 16));
  const [result, setResult] = useState<CandidateResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const submit = async (): Promise<void> => { setLoading(true); setError(null); try { setResult(await submitCandidate(new Date(asOfTime).toISOString())); } catch (err) { setError(err instanceof Error ? err.message : "请求失败"); } finally { setLoading(false); } };
  return <section><h2>候选推荐</h2><p>提交一个时点快照以生成候选清单。</p>
    <label>分析时点 <input aria-label="分析时点" type="datetime-local" value={asOfTime} onChange={(e) => setAsOfTime(e.target.value)} /></label>
    <button onClick={() => void submit()} disabled={loading || !asOfTime}>{loading ? "计算中…" : "生成候选"}</button>
    {error && <p role="alert">{error}</p>}
    {result && <div>{result.run_id && <p>运行已提交：{result.run_id}（{String(result.status ?? "queued")}）</p>}<p>市场状态：{result.market_state ?? "未知"}（{result.market_confidence ?? "未知"}）</p><p>人工确认：{result.human_confirm_required === false ? "否" : "是"}</p>
      <table><thead><tr><th>代码</th><th>名称</th><th>分桶</th><th>状态</th><th>排名</th></tr></thead><tbody>{(result.items ?? []).map((item) => <tr key={item.security_id}><td>{item.security_id}</td><td>{item.security_name ?? "—"}</td><td>{bucketLabel(item.bucket)}</td><td>{item.state ?? "—"}</td><td>{item.percentile_rank == null ? "—" : `${(item.percentile_rank * 100).toFixed(1)}%`}</td></tr>)}</tbody></table>
    </div>}
  </section>;
}
