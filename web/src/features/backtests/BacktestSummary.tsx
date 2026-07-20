import type { BacktestResult } from "./api";

interface BacktestSummaryProps {
  result: BacktestResult;
  onLoadMoreTrades: () => void;
  onLoadMoreRejected: () => void;
}

interface AcceptanceGate {
  name: string;
  passed: boolean;
  observed?: string | number | null;
  threshold?: string | number | null;
  reason?: string | null;
}

interface MetricDetail {
  name: string;
  value?: string | null;
  diagnostic?: string | null;
}

function drawdown(equity: string, peak: number): { peak: number; value: string } {
  const numericEquity = Number(equity);
  if (!Number.isFinite(numericEquity) || numericEquity <= 0) {
    return { peak, value: "-" };
  }
  const nextPeak = Math.max(peak, numericEquity);
  const ratio = numericEquity / nextPeak - 1;
  return { peak: nextPeak, value: Number(ratio.toFixed(6)).toString() };
}

function drawdowns(points: Array<Record<string, string>>): string[] {
  let peak = 0;
  return points.map((point) => {
    const computed = drawdown(point.equity ?? "", peak);
    peak = computed.peak;
    return computed.value;
  });
}

function gradeLabel(grade: string): string {
  return grade === "research" ? "研究级数据" : `数据等级：${grade}`;
}

function llmGradeLabel(grade: string): string {
  if (grade === "reconstructed") {
    return "重建 LLM 因子";
  }
  if (grade === "not_used") {
    return "未使用 LLM 因子";
  }
  return `LLM 等级：${grade}`;
}

function renderedValue(value: unknown): string | number | null | undefined {
  return typeof value === "string" || typeof value === "number" || value === null
    ? value
    : undefined;
}

function gates(details: Record<string, unknown>): AcceptanceGate[] {
  const raw = details.acceptance_gates;
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.flatMap((value) => {
    if (
      typeof value !== "object"
      || value === null
      || typeof value.name !== "string"
      || typeof value.passed !== "boolean"
    ) {
      return [];
    }
    return [{
      name: value.name,
      passed: value.passed,
      observed: renderedValue(value.observed),
      threshold: renderedValue(value.threshold),
      reason: typeof value.reason === "string" || value.reason === null
        ? value.reason
        : undefined,
    }];
  });
}

function metricDetails(details: Record<string, unknown>): MetricDetail[] {
  const values = details.values;
  if (typeof values !== "object" || values === null || Array.isArray(values)) {
    return [];
  }
  return Object.entries(values).flatMap(([name, value]) => {
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      return [];
    }
    return [{
      name,
      value: typeof value.value === "string" || value.value === null
        ? value.value
        : undefined,
      diagnostic: typeof value.diagnostic === "string" || value.diagnostic === null
        ? value.diagnostic
        : undefined,
    }];
  });
}

function AuditTable({
  title,
  rows,
  empty,
  nextCursor,
  loadMoreLabel,
  onLoadMore,
}: {
  title: string;
  rows: Array<Record<string, string>>;
  empty: string;
  nextCursor: string | null;
  loadMoreLabel: string;
  onLoadMore: () => void;
}): JSX.Element {
  const columns = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  return (
    <div className="panel">
      <div className="panel-title">
        <h2>{title}</h2>
        <span>{rows.length} 条</span>
      </div>
      {rows.length === 0 ? <div className="empty-state">{empty}</div> : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr>
            </thead>
            <tbody>{rows.map((row, index) => (
              <tr key={`${title}-${index}`}>
                {columns.map((column) => <td key={column}>{row[column] ?? "-"}</td>)}
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
      {nextCursor ? (
        <div className="inline-actions">
          <button className="btn btn-secondary" onClick={onLoadMore}>{loadMoreLabel}</button>
        </div>
      ) : null}
    </div>
  );
}

export function BacktestSummary({
  result,
  onLoadMoreTrades,
  onLoadMoreRejected,
}: BacktestSummaryProps): JSX.Element {
  const selected = result.groups.find((item) => item.group === result.group);
  const acceptanceGates = gates(result.metric_details);
  const details = metricDetails(result.metric_details);
  const drawdownSeries = drawdowns(result.equity_curve.items);
  return (
    <>
      <div className="notice">仅供研究和人工执行，不自动交易</div>
      <div className="metric-grid">
        <div className="metric-card">
          <span className="metric-label">数据等级</span>
          <div className="metric-value">{gradeLabel(selected?.data_grade ?? "unknown")}</div>
        </div>
        <div className="metric-card">
          <span className="metric-label">LLM 因子</span>
          <div className="metric-value">
            {llmGradeLabel(selected?.llm_grade ?? "unknown")}
          </div>
        </div>
        <div className="metric-card">
          <span className="metric-label">策略版本</span>
          <div className="metric-value">{result.strategy_version}</div>
        </div>
        <div className="metric-card">
          <span className="metric-label">输入 Manifest</span>
          <div className="metric-value">{result.input_manifest_hash}</div>
        </div>
      </div>
      <div className="panel">
        <div className="panel-title">
          <h2>分组数据等级</h2>
          <span>等级按回测分组保留</span>
        </div>
        <div className="reason-list">{result.groups.map((item) => (
          <span className="status-badge status-neutral" key={item.group}>
            {`分组 ${item.group}：${gradeLabel(item.data_grade)}；${llmGradeLabel(item.llm_grade)}`}
          </span>
        ))}</div>
      </div>
      <div className="panel">
        <div className="panel-title">
          <h2>指标与研究门槛</h2>
          <span>结果不构成策略验证</span>
        </div>
        <div className="mini-grid">{Object.entries(result.metrics).map(([name, value]) => (
          <div className="mini-stat" key={name}>
            <span>{name}</span>
            <strong>{value ?? "-"}</strong>
          </div>
        ))}</div>
        <div className="reason-list">{acceptanceGates.map((gate) => (
          <span
            className={gate.passed ? "status-badge status-success" : "status-badge status-danger"}
            key={gate.name}
          >
            {gate.passed ? `通过：${gate.name}` : `未通过：${gate.name}`}
            {gate.observed !== undefined ? `；观察值：${gate.observed ?? "-"}` : ""}
            {gate.threshold !== undefined ? `；阈值：${gate.threshold ?? "-"}` : ""}
            {gate.reason ? `；${gate.reason}` : ""}
          </span>
        ))}</div>
        <div className="reason-list">{details.map((detail) => (
          <span className="reason" key={detail.name}>
            {detail.name}：{detail.value ?? "-"}
            {detail.diagnostic ? `；${detail.diagnostic}` : ""}
          </span>
        ))}</div>
      </div>
      <div className="panel">
        <div className="panel-title">
          <h2>权益曲线审计</h2>
          <span>点时锁定的净值记录</span>
        </div>
        <div className="timeline" data-testid="equity-series">
          {result.equity_curve.items.map((point, index) => (
            <div className="timeline-row" key={`${point.trade_date ?? point.date ?? index}`}>
              <strong>{point.trade_date ?? point.date ?? "-"}</strong>
              <div className="timeline-bar"><span style={{ width: "100%" }} /></div>
              <strong>{point.equity ?? "-"}</strong>
            </div>
          ))}
        </div>
        <div className="timeline" data-testid="drawdown-series">
          {result.equity_curve.items.map((point, index) => (
            <div
              className="timeline-row"
              key={`${point.trade_date ?? point.date ?? index}-drawdown`}
            >
              <strong>{point.trade_date ?? point.date ?? "-"}</strong>
              <div className="timeline-bar"><span style={{ width: "100%" }} /></div>
              <strong>{drawdownSeries[index]}</strong>
            </div>
          ))}
        </div>
      </div>
      <AuditTable
        empty="没有成交记录。"
        loadMoreLabel="加载更多成交"
        nextCursor={result.trades.next_cursor}
        onLoadMore={onLoadMoreTrades}
        rows={result.trades.items}
        title="成交审计"
      />
      <AuditTable
        empty="没有拒单记录。"
        loadMoreLabel="加载更多拒单"
        nextCursor={result.rejected_attempts.next_cursor}
        onLoadMore={onLoadMoreRejected}
        rows={result.rejected_attempts.items}
        title="拒单审计"
      />
      {result.warnings.length > 0 ? (
        <div className="alert" role="alert">{result.warnings.join("；")}</div>
      ) : null}
    </>
  );
}
