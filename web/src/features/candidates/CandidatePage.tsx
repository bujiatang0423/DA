import { useState } from "react";
import { submitCandidate, type CandidateResult, type CandidateItem } from "./api";
import { bucketLabel } from "./viewModel";

const stateLabel: Record<string, string> = { selected: "已入选", pending_execution: "待执行", held: "已持有", watchlist: "观察" };
const factorNames: Record<string, string> = { p: "政策", f: "财报", r: "强度", t: "趋势", v: "量价", s: "综合" };
const factorValue = (item: CandidateItem, key: string): string => item.factors?.[key] == null ? "—" : Number(item.factors[key]).toFixed(2);

function CandidateCard({ item }: { item: CandidateItem }): JSX.Element {
  const executable = item.bucket === "executable";
  return <article className="entity-card"><div className="entity-header"><div className="entity-title"><strong>{item.security_name ?? "未命名证券"}</strong><span>{item.security_id}</span></div><div className="entity-meta"><span className={`status-badge ${executable ? "status-success" : item.bucket === "excluded" ? "status-danger" : "status-warning"}`}>{bucketLabel(item.bucket)}</span><span className="status-badge status-neutral">{stateLabel[item.state ?? ""] ?? item.state ?? "—"}</span></div></div>
    <div className="entity-body"><div className="factor-grid">{Object.entries(factorNames).map(([key, label]) => <div className="factor" key={key}><small>{label}</small><strong>{factorValue(item, key)}</strong></div>)}</div>
      <div className="mini-grid"><div className="mini-stat"><span>横截面排名</span><strong>{item.percentile_rank == null ? "—" : `${(item.percentile_rank * 100).toFixed(1)}%`}</strong></div><div className="mini-stat"><span>计划数量</span><strong>{item.planned_quantity ?? "—"}</strong></div><div className="mini-stat"><span>初始止损</span><strong>{item.initial_stop ?? "—"}</strong></div></div>
      <div className="disclosure"><strong>触发：</strong>{item.trigger_condition ?? "等待点时信号"}<br /><strong>失效：</strong>{item.invalidation_condition ?? "风险条件改变"}</div>
      {(item.reason_codes?.length || item.quality_codes?.length) ? <div className="reason-list">{[...(item.reason_codes ?? []), ...(item.quality_codes ?? [])].map((reason) => <span className="reason" key={reason}>{reason}</span>)}</div> : null}
    </div></article>;
}

export function CandidatePage(): JSX.Element {
  const [asOfTime, setAsOfTime] = useState(() => new Date().toISOString().slice(0, 16));
  const [result, setResult] = useState<CandidateResult | null>(null); const [error, setError] = useState<string | null>(null); const [loading, setLoading] = useState(false);
  const submit = async (): Promise<void> => { setLoading(true); setError(null); try { setResult(await submitCandidate(new Date(asOfTime).toISOString())); } catch (err) { setError(err instanceof Error ? err.message : "请求失败"); } finally { setLoading(false); } };
  const items = result?.items ?? [];
  return <section className="page-shell"><div className="page-heading"><div><h1>候选推荐</h1><p>基于政策、财报、相对强度和趋势量价的 V2.12 点时筛选。</p></div><div className="heading-actions"><span className="status-badge status-warning">人工确认</span><button className="btn" onClick={() => void submit()} disabled={loading || !asOfTime}>{loading ? "计算中…" : "生成候选"}</button></div></div>
    <div className="panel"><div className="control-grid"><label className="field">分析时点<input aria-label="分析时点" type="datetime-local" value={asOfTime} onChange={(event) => setAsOfTime(event.target.value)} /></label><div className="field"><span>策略版本</span><strong>四维盾剑 v2.12</strong></div><div className="field"><span>数据范围</span><strong>点时快照 · 横截面排名</strong></div><div className="field"><span>执行约束</span><strong>只生成建议，不自动下单</strong></div></div></div>
    {error && <div className="alert" role="alert">{error}</div>}
    {result && <><div className="metric-grid"><div className="metric-card"><span className="metric-label">市场状态</span><div className="metric-value">{result.market_state ?? "未知"}</div><span className="metric-note">置信度：{result.market_confidence ?? "—"}</span></div><div className="metric-card"><span className="metric-label">可执行</span><div className="metric-value metric-positive">{items.filter((item) => item.bucket === "executable").length}</div><span className="metric-note">满足硬过滤与约束</span></div><div className="metric-card"><span className="metric-label">观察列表</span><div className="metric-value">{items.filter((item) => item.bucket === "watchlist").length}</div><span className="metric-note">等待触发</span></div><div className="metric-card"><span className="metric-label">质量码</span><div className="metric-value metric-negative">{result.quality_codes?.length ?? 0}</div><span className="metric-note">数据需复核</span></div></div><div className="panel"><div className="panel-title"><h2>候选清单</h2><span>{items.length} 个证券 · Run {result.run_id ?? "—"}</span></div>{items.length === 0 ? <div className="empty-state">任务已提交，等待 worker 返回候选结果。</div> : <div className="candidate-grid">{items.map((item) => <CandidateCard item={item} key={item.security_id} />)}</div>}</div></>}
  </section>;
}
