import { useEffect, useMemo, useState } from "react";

import {
  BacktestApiError,
  getBacktest,
  getRun,
  submitBacktest,
  type BacktestResult,
} from "./api";
import { BacktestSummary } from "./BacktestSummary";

const GROUPS = ["A", "B", "C", "D"];

export function BacktestsPage(): JSX.Element {
  const [start, setStart] = useState("2020-01-01");
  const [end, setEnd] = useState("2025-12-31");
  const [runId, setRunId] = useState<string>();
  const [group, setGroup] = useState("A");
  const [result, setResult] = useState<BacktestResult>();
  const [runStatus, setRunStatus] = useState<string>();
  const [submitting, setSubmitting] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState<string>();
  const request = useMemo(
    () => ({
      strategy_version: "v2.12",
      start_date: start,
      end_date: end,
      initial_cash: "1000000",
      groups: GROUPS,
    }),
    [start, end],
  );

  useEffect(() => {
    if (!runId) {
      return undefined;
    }
    let cancelled = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    const checkStatus = async (): Promise<void> => {
      try {
        const run = await getRun(runId);
        if (cancelled) {
          return;
        }
        setRunStatus(run.status);
        if (run.status === "queued" || run.status === "running") {
          setWaiting(true);
          retry = setTimeout(() => void checkStatus(), 1500);
          return;
        }
        setWaiting(false);
        if (run.status === "failed") {
          setError(`任务执行失败${run.error_code ? `（${run.error_code}）` : ""}。`);
          return;
        }
        if (run.status !== "succeeded") {
          setError("任务已结束，未生成可展示的回测结果。");
        }
      } catch {
        if (cancelled) {
          return;
        }
        setWaiting(false);
        setError("运行状态加载失败，请稍后重试。");
      }
    };
    void checkStatus();
    return () => {
      cancelled = true;
      if (retry) {
        clearTimeout(retry);
      }
    };
  }, [runId]);

  useEffect(() => {
    if (!runId || runStatus !== "succeeded") {
      return;
    }
    let cancelled = false;
    const loadResult = async (): Promise<void> => {
      try {
        const next = await getBacktest(runId, group);
        if (!cancelled && next.group === group) {
          setResult(next);
        }
      } catch (loadError) {
        if (cancelled) {
          return;
        }
        if (loadError instanceof BacktestApiError && loadError.status === 404) {
          setError("回测已完成，但结果暂不可用，请在运行中心复核。");
          return;
        }
        setError("回测结果加载失败，请稍后重试。");
      }
    };
    void loadResult();
    return () => {
      cancelled = true;
    };
  }, [group, runId, runStatus]);

  const submit = async (): Promise<void> => {
    setSubmitting(true);
    setError(undefined);
    setResult(undefined);
    setRunStatus(undefined);
    try {
      const run = await submitBacktest(request);
      setRunId(run.run_id);
    } catch {
      setError("回测任务提交失败，请检查研究参数后重试。");
    } finally {
      setSubmitting(false);
    }
  };

  const selectGroup = (nextGroup: string): void => {
    if (nextGroup === group) {
      return;
    }
    setResult(undefined);
    setError(undefined);
    setGroup(nextGroup);
  };

  const loadMore = async (kind: "trades" | "rejected_attempts"): Promise<void> => {
    if (!runId || !result) {
      return;
    }
    const cursor = result[kind].next_cursor;
    if (!cursor) {
      return;
    }
    try {
      const next = await getBacktest(
        runId,
        group,
        kind === "trades" ? { tradeCursor: cursor } : { rejectedCursor: cursor },
      );
      if (next.group !== group) {
        return;
      }
      setResult((current) => {
        if (!current || current.group !== group) {
          return current;
        }
        return {
          ...current,
          [kind]: {
            ...next[kind],
            items: [...current[kind].items, ...next[kind].items],
          },
        };
      });
    } catch {
      setError("审计记录加载失败，请稍后重试。");
    }
  };

  return (
    <section className="page-shell">
      <div className="page-heading">
        <div>
          <h1>历史回测</h1>
          <p>点时数据驱动的 V2.12 walk-forward 研究，不把未来数据带入过去。</p>
        </div>
        <button className="btn" onClick={() => void submit()} disabled={submitting}>
          {submitting ? "提交中..." : "开始回测"}
        </button>
      </div>
      <div className="panel">
        <div className="panel-title"><h2>研究参数</h2><span>Research only</span></div>
        <div className="control-grid">
          <label className="field">
            开始日期
            <input type="date" value={start} onChange={(event) => setStart(event.target.value)} />
          </label>
          <label className="field">
            结束日期
            <input type="date" value={end} onChange={(event) => setEnd(event.target.value)} />
          </label>
          <div className="field"><span>策略版本</span><strong>四维盾剑 v2.12</strong></div>
          <div className="field"><span>初始资金 / 分组</span><strong>¥1,000,000 · A/B/C/D</strong></div>
        </div>
      </div>
      {error ? <div className="alert" role="alert">{error}</div> : null}
      {waiting ? <div className="empty-state">任务已提交，正在等待持久回测结果...</div> : null}
      {result ? (
        <>
          <div className="heading-actions">{GROUPS.filter((item) => (
            result.groups.some((summary) => summary.group === item)
          )).map((item) => (
            <button
              className={item === group ? "btn" : "btn btn-secondary"}
              key={item}
              onClick={() => selectGroup(item)}
            >
              分组 {item}
            </button>
          ))}</div>
          <BacktestSummary
            onLoadMoreRejected={() => void loadMore("rejected_attempts")}
            onLoadMoreTrades={() => void loadMore("trades")}
            result={result}
          />
        </>
      ) : null}
    </section>
  );
}

export const backtestsFeature = {
  id: "backtests",
  path: "/backtests",
  label: "历史回测",
  element: <BacktestsPage />,
} as const;
