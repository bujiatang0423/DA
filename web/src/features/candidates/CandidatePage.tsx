import { useState } from "react";
import { submitCandidate, type CandidateItem, type CandidateResult } from "./api";
import { bucketLabel } from "./viewModel";

const factorNames: Record<string, string> = {
  p: "政策", f: "财报", r: "强度", t: "趋势", v: "量价", s: "综合",
};

function factorValue(item: CandidateItem, key: string): string {
  const value = item.factors?.[key];
  return value == null ? "—" : Number(value).toFixed(2);
}

function CandidateCard({ item }: { item: CandidateItem }): JSX.Element {
  return <article className="entity-card">
    <div className="entity-header">
      <div className="entity-title"><strong>{item.security_name ?? "未命名证券"}</strong><span>{item.security_id}</span></div>
      <span className="status-badge status-neutral">{bucketLabel(item.bucket)}</span>
    </div>
    <div className="entity-body">
      <div className="factor-grid">{Object.entries(factorNames).map(([key, label]) => <div className="factor" key={key}><small>{label}</small><strong>{factorValue(item, key)}</strong></div>)}</div>
      <div className="disclosure"><strong>触发：</strong>{item.trigger_condition ?? "等待点时信号"}<br /><strong>失效：</strong>{item.invalidation_condition ?? "风险条件改变"}</div>
      {(item.reason_codes?.length || item.quality_codes?.length) ? <div className="reason-list">{[...(item.reason_codes ?? []), ...(item.quality_codes ?? [])].map((reason) => <span className="reason" key={reason}>{reason}</span>)}</div> : null}
      {item.evidence_refs?.length ? <details className="disclosure"><summary>证据链</summary><ul>{item.evidence_refs.map((ref) => <li key={ref}>{ref}</li>)}</ul></details> : null}
    </div>
  </article>;
}

function BucketSection({ bucket, items }: { bucket: string; items: CandidateItem[] }): JSX.Element {
  const title = bucket === "watchlist" ? "观察列表" : bucketLabel(bucket);
  return <section className="panel" aria-label={title}>
    <div className="panel-title"><h2>{title}</h2><span>{items.length} 个证券</span></div>
    {items.length ? <div className="candidate-grid">{items.map((item) => <CandidateCard item={item} key={item.security_id} />)}</div> : <div className="empty-state">当前没有该类候选。</div>}
  </section>;
}

export function CandidatePage(): JSX.Element {
  const [asOfTime, setAsOfTime] = useState(() => new Date().toISOString().slice(0, 16));
  const [result, setResult] = useState<CandidateResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const submit = async (): Promise<void> => {
    setLoading(true); setError(null);
    try { setResult(await submitCandidate(new Date(asOfTime).toISOString())); }
    catch (err) { setError(err instanceof Error ? err.message : "请求失败"); }
    finally { setLoading(false); }
  };
  const items = result?.items ?? [];
  return <section className="page-shell">
    <div className="page-heading"><div><h1>候选推荐</h1><p>基于点时数据的 V2.12 筛选结果。</p></div><div className="heading-actions"><span className="status-badge status-warning">人工确认</span><button className="btn" onClick={() => void submit()} disabled={loading || !asOfTime}>{loading ? "计算中…" : "生成候选"}</button></div></div>
    <div className="panel"><div className="control-grid"><label className="field">分析时点<input aria-label="分析时点" type="datetime-local" value={asOfTime} onChange={(event) => setAsOfTime(event.target.value)} /></label><div className="field"><span>策略版本</span><strong>四维盾剑 v2.12</strong></div><div className="field"><span>执行约束</span><strong>仅建议，人工确认</strong></div></div></div>
    {error && <div className="alert" role="alert">{error}</div>}
    {result && <><div className="metric-grid"><div className="metric-card"><span className="metric-label">市场状态</span><div className="metric-value">{result.market_state ?? "未知"}</div><span className="metric-note">置信度：{result.market_confidence ?? "—"}</span></div><div className="metric-card"><span className="metric-label">数据等级</span><div className="metric-value">数据等级：{result.data_grade ?? "—"}</div></div><div className="metric-card"><span className="metric-label">LLM 等级</span><div className="metric-value">LLM 等级：{result.llm_grade ?? "—"}</div></div></div><BucketSection bucket="executable" items={items.filter((item) => item.bucket === "executable")} /><BucketSection bucket="watchlist" items={items.filter((item) => item.bucket === "watchlist")} /><BucketSection bucket="excluded" items={items.filter((item) => item.bucket === "excluded")} /></>}
  </section>;
}
