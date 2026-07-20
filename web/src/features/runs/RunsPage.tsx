import { useEffect, useState } from "react";

import { listRuns, retryRun, type RunDetail } from "../../shared/api/client";

const labels: Record<string, string> = {
  candidate_recommendation: "候选推荐",
  holding_analysis: "持仓分析",
  backtest: "历史回测",
  legacy_import: "历史导入",
};

const resultLabels: Record<string, string> = {
  candidate_recommendation: "查看候选结果",
  holding_analysis: "查看持仓结果",
};

const statusNames: Record<string, string> = {
  queued: "排队中",
  running: "执行中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

function statusClass(status: string): string {
  if (status === "succeeded") return "status-success";
  if (status === "failed") return "status-danger";
  if (status === "running") return "status-warning";
  return "status-neutral";
}

function RunLinks({ run }: { run: RunDetail }): JSX.Element {
  const links = run.links ?? {};
  const resultLabel = resultLabels[run.kind] ?? "查看结果";

  return (
    <>
      {links.result ? <a href={links.result}>{resultLabel}</a> : null}
      {links.result && links.artifacts ? " · " : null}
      {links.artifacts ? <a href={links.artifacts}>查看产物</a> : null}
    </>
  );
}

export function RunsPage(): JSX.Element {
  const [runs, setRuns] = useState<RunDetail[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState("all");
  const [error, setError] = useState<string | null>(null);
  const [retryingRunId, setRetryingRunId] = useState<string | null>(null);

  const refresh = async (): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      setRuns((await listRuns()).items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  };

  const retry = async (runId: string): Promise<void> => {
    setRetryingRunId(runId);
    setError(null);
    try {
      await retryRun(runId);
      await refresh();
    } catch {
      setError("重试请求未被接受，请刷新后确认任务状态。");
    } finally {
      setRetryingRunId(null);
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const visible = filter === "all" ? runs : runs.filter((run) => run.status === filter);
  const count = (status: string): number => runs.filter((run) => run.status === status).length;

  return (
    <section className="page-shell">
      <div className="page-heading">
        <div>
          <h1>运行中心</h1>
          <p>所有候选、持仓和回测任务的统一执行记录。</p>
        </div>
        <button className="btn btn-secondary" onClick={() => void refresh()}>
          {loading ? "刷新中…" : "重新加载"}
        </button>
      </div>
      <div className="metric-grid">
        <div className="metric-card">
          <span className="metric-label">全部任务</span>
          <div className="metric-value">{runs.length}</div>
          <span className="metric-note">当前返回页</span>
        </div>
        <div className="metric-card">
          <span className="metric-label">执行中</span>
          <div className="metric-value metric-positive">{count("running")}</div>
          <span className="metric-note">实时任务</span>
        </div>
        <div className="metric-card">
          <span className="metric-label">排队中</span>
          <div className="metric-value">{count("queued")}</div>
          <span className="metric-note">等待 worker</span>
        </div>
        <div className="metric-card">
          <span className="metric-label">失败任务</span>
          <div className="metric-value metric-negative">{count("failed")}</div>
          <span className="metric-note">需要复核</span>
        </div>
      </div>
      {error ? <div className="alert" role="alert">{error}</div> : null}
      <div className="panel">
        <div className="panel-title">
          <h2>任务记录</h2>
          <span>{visible.length} 条记录</span>
        </div>
        <div className="inline-actions" style={{ marginBottom: 14 }}>
          {[
            ["all", "全部"],
            ["queued", "排队中"],
            ["running", "执行中"],
            ["succeeded", "已完成"],
            ["failed", "失败"],
          ].map(([value, label]) => (
            <button
              key={value}
              className={`btn ${filter === value ? "" : "btn-secondary"}`}
              onClick={() => setFilter(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>任务</th>
                <th>状态</th>
                <th>提交时间</th>
                <th>执行状态</th>
                <th>错误与重试</th>
                <th>结果与产物</th>
                <th>确认要求</th>
              </tr>
            </thead>
            <tbody>
              {visible.length === 0 ? (
                <tr>
                  <td colSpan={7}>
                    <div className="empty-state">
                      {loading ? "正在加载任务…" : "暂无运行记录"}
                    </div>
                  </td>
                </tr>
              ) : visible.map((run) => (
                <tr key={run.run_id}>
                  <td>
                    <span className="code">{labels[run.kind] ?? run.kind}</span>
                    <div className="muted">Run {run.run_id}</div>
                    <span className="sr-only">{run.kind} · {run.status}</span>
                  </td>
                  <td>
                    <span className={`status-badge ${statusClass(run.status)}`}>
                      {statusNames[run.status] ?? run.status}
                    </span>
                  </td>
                  <td>{new Date(run.submitted_at).toLocaleString("zh-CN")}</td>
                  <td>
                    <div>
                      {run.progress ?? 0}%
                      {run.stage ? <span className="muted"> · {run.stage}</span> : null}
                    </div>
                    {run.heartbeat_at ? (
                      <div className="muted">
                        心跳 {new Date(run.heartbeat_at).toLocaleString("zh-CN")}
                      </div>
                    ) : null}
                  </td>
                  <td>
                    {run.error_code ? <div className="code">{run.error_code}</div> : null}
                    {run.error_message ? <div className="muted">{run.error_message}</div> : null}
                    <div className="muted">
                      {run.retry_count ? `已重试 ${run.retry_count} 次` : "尚未重试"}
                    </div>
                  </td>
                  <td><RunLinks run={run} /></td>
                  <td>
                    <span className="status-badge status-warning">人工确认</span>
                    {run.status === "failed" ? (
                      <button
                        className="btn btn-secondary"
                        disabled={retryingRunId === run.run_id}
                        onClick={() => void retry(run.run_id)}
                      >
                        {retryingRunId === run.run_id ? "重试中…" : "重试任务"}
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
