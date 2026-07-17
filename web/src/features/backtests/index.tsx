import { useState } from "react";
interface BacktestPlan { strategy_version: string; holdout: { start: string; end: string }; windows: Array<{ development_start: string; development_end: string; validation_start: string; validation_end: string }>; groups: string[] }
export async function submitBacktest(payload: object): Promise<BacktestPlan> { const response = await fetch("/api/v1/backtests/plan", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); if (!response.ok) throw new Error(`回测请求失败（${response.status}）`); return response.json() as Promise<BacktestPlan>; }
export function BacktestsPage(): JSX.Element {
  const [start, setStart] = useState("2020-01-01"); const [end, setEnd] = useState("2025-12-31"); const [plan, setPlan] = useState<BacktestPlan | null>(null); const [error, setError] = useState<string | null>(null); const [loading, setLoading] = useState(false);
  const submit = async (): Promise<void> => { setLoading(true); setError(null); try { setPlan(await submitBacktest({ strategy_version: "v2.12", start_date: start, end_date: end, initial_cash: "1000000", groups: ["A", "B", "C", "D"] })); } catch (err) { setError(err instanceof Error ? err.message : "请求失败"); } finally { setLoading(false); } };
  return <section><h2>历史回测</h2><p>使用点时数据运行 V2.12 walk-forward 回测。</p><label>开始日期 <input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></label><label>结束日期 <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></label><button onClick={() => void submit()} disabled={loading}>{loading ? "规划中…" : "生成回测计划"}</button>{error && <p role="alert">{error}</p>}{plan && <div><p>策略：{plan.strategy_version}　Holdout：{plan.holdout.start} 至 {plan.holdout.end}</p><p>分组：{plan.groups.join("、")}</p><ol>{plan.windows.map((window, index) => <li key={`${window.development_start}-${index}`}>开发 {window.development_start}–{window.development_end}；验证 {window.validation_start}–{window.validation_end}</li>)}</ol></div>}</section>;
}

export const backtestsFeature = {
  id: "backtests", path: "/backtests", label: "历史回测", element: <BacktestsPage />,
} as const;
