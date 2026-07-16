import { useEffect, useState } from "react";
import { listRuns, type RunDetail } from "../../shared/api/client";

export function RunsPage(): JSX.Element {
  const [runs, setRuns] = useState<RunDetail[]>([]);
  const [loading, setLoading] = useState(false);
  const refresh = async (): Promise<void> => {
    setLoading(true);
    try { setRuns((await listRuns()).items); } finally { setLoading(false); }
  };
  useEffect(() => { void refresh(); }, []);
  return <section><h2>运行中心</h2><button onClick={() => void refresh()}>{loading ? "加载中…" : "刷新"}</button>
    {runs.length === 0 ? <p>暂无运行记录</p> : <ul>{runs.map((run) => <li key={run.run_id}>{run.kind} · {run.status}</li>)}</ul>}</section>;
}
