import { useEffect, useMemo, useRef, useState } from "react";

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
  const [availableGroups, setAvailableGroups] = useState<string[]>([]);
  const [result, setResult] = useState<BacktestResult>();
  const [runStatus, setRunStatus] = useState<string>();
  const [requestVersion, setRequestVersion] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState<string>();
  const activeRequestVersion = useRef(0);
  const activeRunId = useRef<string>();
  const activeGroup = useRef(group);
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

  const advanceRequestVersion = (): number => {
    const nextVersion = activeRequestVersion.current + 1;
    activeRequestVersion.current = nextVersion;
    setRequestVersion(nextVersion);
    return nextVersion;
  };

  const isCurrentRequest = (
    version: number,
    expectedRunId: string,
    expectedGroup: string,
  ): boolean => {
    return activeRequestVersion.current === version
      && activeRunId.current === expectedRunId
      && activeGroup.current === expectedGroup;
  };

  useEffect(() => {
    if (!runId) {
      return undefined;
    }
    const version = requestVersion;
    const expectedGroup = group;
    let cancelled = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    const checkStatus = async (): Promise<void> => {
      try {
        const run = await getRun(runId);
        if (cancelled || !isCurrentRequest(version, runId, expectedGroup)) {
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
        if (cancelled || !isCurrentRequest(version, runId, expectedGroup)) {
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
  }, [group, requestVersion, runId]);

  useEffect(() => {
    if (!runId || runStatus !== "succeeded") {
      return;
    }
    const version = requestVersion;
    let cancelled = false;
    const loadResult = async (): Promise<void> => {
      try {
        const next = await getBacktest(runId, group);
        if (!cancelled && isCurrentRequest(version, runId, group) && next.group === group) {
          setResult(next);
          setAvailableGroups(next.groups.map((summary) => summary.group));
        }
      } catch (loadError) {
        if (cancelled || !isCurrentRequest(version, runId, group)) {
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
  }, [group, requestVersion, runId, runStatus]);

  const submit = async (): Promise<void> => {
    const version = advanceRequestVersion();
    setSubmitting(true);
    setError(undefined);
    setResult(undefined);
    setRunStatus(undefined);
    setWaiting(false);
    setAvailableGroups([]);
    activeRunId.current = undefined;
    setRunId(undefined);
    try {
      const run = await submitBacktest(request);
      if (activeRequestVersion.current !== version) {
        return;
      }
      activeRunId.current = run.run_id;
      setRunId(run.run_id);
    } catch {
      if (activeRequestVersion.current === version) {
        setError("回测任务提交失败，请检查研究参数后重试。");
      }
    } finally {
      if (activeRequestVersion.current === version) {
        setSubmitting(false);
      }
    }
  };

  const selectGroup = (nextGroup: string): void => {
    if (nextGroup === group) {
      return;
    }
    advanceRequestVersion();
    activeGroup.current = nextGroup;
    setResult(undefined);
    setError(undefined);
    setGroup(nextGroup);
  };

  const loadMore = async (kind: "trades" | "rejected_attempts"): Promise<void> => {
    if (!runId || !result) {
      return;
    }
    const version = requestVersion;
    const expectedRunId = runId;
    const expectedGroup = group;
    const cursor = result[kind].next_cursor;
    if (!cursor) {
      return;
    }
    try {
      const next = await getBacktest(
        expectedRunId,
        expectedGroup,
        kind === "trades" ? { tradeCursor: cursor } : { rejectedCursor: cursor },
      );
      if (
        next.group !== expectedGroup
        || !isCurrentRequest(version, expectedRunId, expectedGroup)
      ) {
        return;
      }
      setResult((current) => {
        if (
          !current
          || current.group !== expectedGroup
          || !isCurrentRequest(version, expectedRunId, expectedGroup)
        ) {
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
      if (isCurrentRequest(version, expectedRunId, expectedGroup)) {
        setError("审计记录加载失败，请稍后重试。");
      }
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
      {availableGroups.length > 0 ? (
        <>
          <div className="heading-actions">{GROUPS.filter((item) => (
            availableGroups.includes(item)
          )).map((item) => (
            <button
              className={item === group ? "btn" : "btn btn-secondary"}
              key={item}
              onClick={() => selectGroup(item)}
            >
              分组 {item}
            </button>
          ))}</div>
          {result ? (
            <BacktestSummary
              onLoadMoreRejected={() => void loadMore("rejected_attempts")}
              onLoadMoreTrades={() => void loadMore("trades")}
              result={result}
            />
          ) : <div className="empty-state">正在加载所选分组的回测结果...</div>}
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
