import { useEffect, useState } from "react";
import { listRuns, type RunDetail } from "../../shared/api/client";

const labels: Record<string, string> = { candidate_recommendation: "候选推荐", holding_analysis: "持仓分析", backtest: "历史回测", legacy_import: "历史导入" };
const statusNames: Record<string, string> = { queued: "排队中", running: "执行中", succeeded: "已完成", failed: "失败", cancelled: "已取消" };
const statusClass = (status: string): string => status === "succeeded" ? "status-success" : status === "failed" ? "status-danger" : status === "running" ? "status-warning" : "status-neutral";

export function RunsPage(): JSX.Element {
  const [runs, setRuns] = useState<RunDetail[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState("all");
  const [error, setError] = useState<string | null>(null);
  const refresh = async (): Promise<void> => {
    setLoading(true); setError(null);
    try { setRuns((await listRuns()).items); } catch (err) { setError(err instanceof Error ? err.message : "加载失败"); } finally { setLoading(false); }
  };
  useEffect(() => { void refresh(); }, []);
  const visible = filter === "all" ? runs : runs.filter((run) => run.status === filter);
  const count = (status: string): number => runs.filter((run) => run.status === status).length;
  return <section className="page-shell">
    <div className="page-heading"><div><h1>运行中心</h1><p>所有候选、持仓和回测任务的统一执行记录。</p></div><button className="btn btn-secondary" onClick={() => void refresh()}>{loading ? "刷新中…" : "重新加载"}</button></div>
    <div className="metric-grid">
      <div className="metric-card"><span className="metric-label">全部任务</span><div className="metric-value">{runs.length}</div><span className="metric-note">当前返回页</span></div>
      <div className="metric-card"><span className="metric-label">执行中</span><div className="metric-value metric-positive">{count("running")}</div><span className="metric-note">实时任务</span></div>
      <div className="metric-card"><span className="metric-label">排队中</span><div className="metric-value">{count("queued")}</div><span className="metric-note">等待 worker</span></div>
      <div className="metric-card"><span className="metric-label">失败任务</span><div className="metric-value metric-negative">{count("failed")}</div><span className="metric-note">需要复核</span></div>
    </div>
    {error && <div className="alert" role="alert">{error}</div>}
    <div className="panel"><div className="panel-title"><h2>任务记录</h2><span>{visible.length} 条记录</span></div><div className="inline-actions" style={{ marginBottom: 14 }}>
      {[['all','全部'],['queued','排队中'],['running','执行中'],['succeeded','已完成'],['failed','失败']].map(([value, label]) => <button key={value} className={`btn ${filter === value ? "" : "btn-secondary"}`} onClick={() => setFilter(value)}>{label}</button>)}
    </div><div className="table-wrap"><table className="data-table"><thead><tr><th>任务</th><th>状态</th><th>提交时间</th><th>进度</th><th>确认要求</th></tr></thead><tbody>
      {visible.length === 0 ? <tr><td colSpan={5}><div className="empty-state">{loading ? "正在加载任务…" : "暂无运行记录"}</div></td></tr> : visible.map((run) => <tr key={run.run_id}><td><span className="code">{labels[run.kind] ?? run.kind}</span><div className="muted">Run {run.run_id}</div><span className="sr-only">{run.kind} · {run.status}</span></td><td><span className={`status-badge ${statusClass(run.status)}`}>{statusNames[run.status] ?? run.status}</span></td><td>{new Date(run.submitted_at).toLocaleString("zh-CN")}</td><td>{run.progress ?? 0}%{run.stage && <span className="muted"> · {run.stage}</span>}</td><td><span className="status-badge status-warning">人工确认</span></td></tr>)}
    </tbody></table></div></div>
  </section>;
}
