import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError } from "../../shared/api/client";
import {
  holdingApi,
  type ManualFill,
  type PositionCorrection,
  type RunRef,
} from "./api";
import { HoldingCard } from "./HoldingCard";
import { ManualFillForm } from "./ManualFillForm";
import { PositionCorrectionForm } from "./PositionCorrectionForm";

const DEFAULT_PORTFOLIO_ID = "default";

export function HoldingAnalysisPage(): JSX.Element {
  const queryClient = useQueryClient();
  const [run, setRun] = useState<RunRef | null>(null);
  const [showCorrection, setShowCorrection] = useState(false);
  const [showFill, setShowFill] = useState(false);
  const [conflict, setConflict] = useState(false);
  const positions = useQuery({
    queryKey: ["holding-positions", DEFAULT_PORTFOLIO_ID],
    queryFn: () => holdingApi.positions(DEFAULT_PORTFOLIO_ID),
  });
  const portfolioId = positions.data?.portfolio_id ?? DEFAULT_PORTFOLIO_ID;
  const latest = useQuery({
    queryKey: ["holding-latest", portfolioId],
    queryFn: () => holdingApi.latest(portfolioId),
  });
  const reloadPositions = async (): Promise<void> => {
    await queryClient.invalidateQueries({
      queryKey: ["holding-positions", DEFAULT_PORTFOLIO_ID],
    });
  };
  const submit = useMutation({
    mutationFn: () => {
      const asOfTime = positions.data?.as_of_time ?? new Date().toISOString();
      return holdingApi.submit(
        { portfolio_id: portfolioId, as_of_time: asOfTime },
        `holding:${portfolioId}:${asOfTime}`,
      );
    },
    onSuccess: setRun,
  });
  const correction = useMutation({
    mutationFn: (request: PositionCorrection) =>
      holdingApi.correctPositions(request),
    onSuccess: async (page) => {
      queryClient.setQueryData(
        ["holding-positions", DEFAULT_PORTFOLIO_ID],
        page,
      );
      setShowCorrection(false);
      setConflict(false);
    },
    onError: async (error) => {
      if (error instanceof ApiError && error.status === 409) {
        setConflict(true);
        await reloadPositions();
      }
    },
  });
  const fill = useMutation({
    mutationFn: (request: ManualFill) => holdingApi.recordManualFill(request),
    onSuccess: async (page) => {
      queryClient.setQueryData(
        ["holding-positions", DEFAULT_PORTFOLIO_ID],
        page,
      );
      setShowFill(false);
      setConflict(false);
    },
    onError: async (error) => {
      if (error instanceof ApiError && error.status === 409) {
        setConflict(true);
        await reloadPositions();
      }
    },
  });

  if (positions.isLoading || latest.isLoading) {
    return <div className="empty-state">正在加载点时持仓与最新分析...</div>;
  }
  if (positions.isError || latest.isError) {
    return (
      <div className="alert" role="alert">
        持仓分析数据加载失败，请稍后重试。
      </div>
    );
  }

  const positionPage = positions.data;
  const result = latest.data;
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
            disabled={submit.isPending}
            onClick={() => submit.mutate()}
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
      {submit.isError ? (
        <div className="alert" role="alert">
          分析任务提交失败。
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
          onSubmit={(request) => correction.mutate(request)}
          page={positionPage}
          pending={correction.isPending}
        />
      ) : null}
      {positionPage && showFill ? (
        <ManualFillForm
          onCancel={() => setShowFill(false)}
          onSubmit={(request) => fill.mutate(request)}
          page={positionPage}
          pending={fill.isPending}
        />
      ) : null}
      {correction.isError && !conflict ? (
        <div className="alert" role="alert">
          校正失败，请重新加载最新版本。
        </div>
      ) : null}
      {fill.isError && !conflict ? (
        <div className="alert" role="alert">
          实际成交保存失败，请核对可卖数量和版本。
        </div>
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
