import { useEffect, useState } from "react";

import {
  HoldingApiError,
  holdingApi,
  type HoldingResult,
  type ManualFill,
  type PositionCorrection,
  type PositionPage,
  type RunRef,
} from "./api";
import { HoldingCard } from "./HoldingCard";
import { ManualFillForm } from "./ManualFillForm";
import { PositionCorrectionForm } from "./PositionCorrectionForm";

const DEFAULT_PORTFOLIO_ID = "default";

export function HoldingAnalysisPage(): JSX.Element {
  const [positionPage, setPositionPage] = useState<PositionPage | null>(null);
  const [result, setResult] = useState<HoldingResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [run, setRun] = useState<RunRef | null>(null);
  const [showCorrection, setShowCorrection] = useState(false);
  const [showFill, setShowFill] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);

  const load = async (): Promise<void> => {
    setLoading(true);
    setLoadError(false);
    try {
      const [positions, latest] = await Promise.all([
        holdingApi.positions(DEFAULT_PORTFOLIO_ID),
        holdingApi.latest(DEFAULT_PORTFOLIO_ID),
      ]);
      setPositionPage(positions);
      setResult(latest);
    } catch {
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const reloadPositions = async (): Promise<void> => {
    const positions = await holdingApi.positions(DEFAULT_PORTFOLIO_ID);
    setPositionPage(positions);
  };

  const handleCorrection = async (
    request: PositionCorrection,
  ): Promise<void> => {
    setSubmitting(true);
    setConflict(false);
    setMutationError(null);
    try {
      setPositionPage(await holdingApi.correctPositions(request));
      setShowCorrection(false);
    } catch (error) {
      if (error instanceof HoldingApiError && error.status === 409) {
        setConflict(true);
        await reloadPositions();
      } else {
        setMutationError("校正失败，请重新加载最新版本。");
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleFill = async (request: ManualFill): Promise<void> => {
    setSubmitting(true);
    setConflict(false);
    setMutationError(null);
    try {
      setPositionPage(await holdingApi.recordManualFill(request));
      setShowFill(false);
    } catch (error) {
      if (error instanceof HoldingApiError && error.status === 409) {
        setConflict(true);
        await reloadPositions();
      } else {
        setMutationError("实际成交保存失败，请核对可卖数量和版本。");
      }
    } finally {
      setSubmitting(false);
    }
  };

  const submit = async (): Promise<void> => {
    const asOfTime = positionPage?.as_of_time ?? new Date().toISOString();
    setSubmitting(true);
    try {
      setRun(
        await holdingApi.submit(
          { portfolio_id: DEFAULT_PORTFOLIO_ID, as_of_time: asOfTime },
          `holding:${DEFAULT_PORTFOLIO_ID}:${asOfTime}`,
        ),
      );
    } catch {
      setMutationError("分析任务提交失败。");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return <div className="empty-state">正在加载点时持仓与最新分析...</div>;
  }
  if (loadError) {
    return (
      <div className="alert" role="alert">
        持仓分析数据加载失败，请稍后重试。
      </div>
    );
  }

  return (
    <section className="page-shell">
      <div className="page-heading">
        <div>
          <h1>持仓分析</h1>
          <p>V2.12 风险优先建议；所有动作必须由人工核对后执行。</p>
        </div>
        <div className="heading-actions">
          <button
            className="btn"
            disabled={submitting}
            onClick={() => void submit()}
          >
            分析当前持仓
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => setShowCorrection(true)}
          >
            校正持仓
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => setShowFill(true)}
          >
            记录实际成交
          </button>
        </div>
      </div>
      <div className="alert">仅供人工确认，不自动下单</div>
      {mutationError ? (
        <div className="alert" role="alert">
          {mutationError}
        </div>
      ) : null}
      {run ? <a href={`/runs/${run.run_id}`}>查看运行进度</a> : null}
      {conflict ? (
        <div className="alert" role="alert">
          持仓版本已变化，已重新加载最新持仓。请核对后重新提交。
        </div>
      ) : null}
      {positionPage && showCorrection ? (
        <PositionCorrectionForm
          onCancel={() => setShowCorrection(false)}
          onSubmit={(request) => void handleCorrection(request)}
          page={positionPage}
          pending={submitting}
        />
      ) : null}
      {positionPage && showFill ? (
        <ManualFillForm
          onCancel={() => setShowFill(false)}
          onSubmit={(request) => void handleFill(request)}
          page={positionPage}
          pending={submitting}
        />
      ) : null}
      {result ? (
        <>
          {result.data_grade === "research" ? (
            <div className="alert">研究级数据，不能作为自动交易指令。</div>
          ) : null}
          <div className="metric-grid">
            <div className="metric-card">
              <span className="metric-label">组合权益</span>
              <div className="metric-value">{result.summary.equity}</div>
            </div>
            <div className="metric-card">
              <span className="metric-label">总敞口</span>
              <div className="metric-value">
                {result.summary.gross_exposure_pct}%
              </div>
            </div>
            <div className="metric-card">
              <span className="metric-label">组合风险</span>
              <div className="metric-value metric-negative">
                {result.summary.portfolio_risk_pct}%
              </div>
            </div>
            <div className="metric-card">
              <span className="metric-label">市场状态</span>
              <div className="metric-value">{result.summary.market_state}</div>
            </div>
          </div>
          <div className="holding-grid">
            {result.items.map((item) => (
              <HoldingCard item={item} key={item.security_id} />
            ))}
          </div>
        </>
      ) : (
        <div className="empty-state">尚未运行持仓分析。</div>
      )}
    </section>
  );
}
