import { useEffect, useState } from "react";

import { legacyImportApi, type LegacyImportPreview, type LegacyImportResult, type LegacyImportSource } from "./api";

const DEFAULT_PORTFOLIO_ID = "main";

function asShanghaiIso(value: string): string {
  return `${value}:00+08:00`;
}

export function LegacyImportPage(): JSX.Element {
  const [sources, setSources] = useState<LegacyImportSource[]>([]);
  const [sourceId, setSourceId] = useState("");
  const [effectiveAt, setEffectiveAt] = useState("");
  const [preview, setPreview] = useState<LegacyImportPreview | null>(null);
  const [result, setResult] = useState<LegacyImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    void legacyImportApi.sources().then((value) => {
      setSources(value.items);
      setSourceId(value.items[0]?.source_id ?? "");
    }).catch(() => setError("导入来源加载失败。"));
  }, []);

  const requestPreview = async (): Promise<void> => {
    if (!sourceId || !effectiveAt) return;
    setPending(true);
    setError(null);
    setResult(null);
    try {
      setPreview(await legacyImportApi.preview({
        source_id: sourceId,
        portfolio_id: DEFAULT_PORTFOLIO_ID,
        effective_at: asShanghaiIso(effectiveAt),
      }));
    } catch {
      setError("预览失败，请核对来源和生效时间。");
    } finally {
      setPending(false);
    }
  };

  const confirm = async (): Promise<void> => {
    if (!preview) return;
    setPending(true);
    setError(null);
    try {
      setResult(await legacyImportApi.confirm({
        source_id: preview.source_id,
        portfolio_id: preview.portfolio_id,
        effective_at: preview.effective_at,
        confirmation_token: preview.confirmation_token,
      }));
      setPreview(null);
    } catch {
      setError("确认令牌已失效，请重新预览后确认。");
    } finally {
      setPending(false);
    }
  };

  return (
    <section className="page-shell">
      <div className="page-heading">
        <div>
          <h1>历史持仓导入</h1>
          <p>仅冻结已配置来源的原始数据，并生成 legacy opening balance。</p>
        </div>
      </div>
      <div className="alert">不自动触发持仓分析</div>
      {error ? <div className="alert" role="alert">{error}</div> : null}
      <div className="panel">
        <div className="form-grid">
          <label>导入来源
            <select value={sourceId} onChange={(event) => setSourceId(event.target.value)}>
              {sources.map((source) => <option key={source.source_id} value={source.source_id}>{source.label}</option>)}
            </select>
          </label>
          <label>生效时间
            <input aria-label="生效时间" type="datetime-local" value={effectiveAt} onChange={(event) => setEffectiveAt(event.target.value)} />
          </label>
        </div>
        <div className="heading-actions">
          <button className="btn" disabled={pending || !sourceId || !effectiveAt} onClick={() => void requestPreview()}>
            预览导入
          </button>
        </div>
      </div>
      {preview ? <div className="panel">
        <h2>只读预览</h2>
        <div className="metric-grid">
          <div className="metric-card"><span className="metric-label">当前持仓</span><div className="metric-value">{preview.current_position_count}</div></div>
          <div className="metric-card"><span className="metric-label">历史快照</span><div className="metric-value">{preview.historical_position_count}</div></div>
          <div className="metric-card"><span className="metric-label">源文件</span><div className="metric-value">{preview.source_file_count}</div></div>
        </div>
        <p className="muted">质量标签：{preview.quality_tags.length ? preview.quality_tags.join(", ") : "无"}</p>
        <button className="btn" disabled={pending} onClick={() => void confirm()}>确认冻结并导入</button>
      </div> : null}
      {result ? <div className="panel">
        <h2>导入结果</h2>
        <p className="code">{result.batch_id}</p>
        <p className="muted">Manifest {result.manifest_sha256}</p>
        <p>{result.idempotent ? "重复导入，已复用已有批次" : "首次导入"}</p>
        <p>原始文件 {result.raw_file_count} · opening positions {result.opening_position_count} · 历史快照 {result.historical_snapshot_count}</p>
      </div> : null}
    </section>
  );
}
