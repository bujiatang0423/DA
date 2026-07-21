import type { HoldingItem } from "./viewModel";
import {
    actionLabel,
    displayValue,
    pendingExecutionLabel,
    positionSemantics,
} from "./viewModel";

export function HoldingCard({ item }: { item: HoldingItem }): JSX.Element {
    const pending = pendingExecutionLabel(item);
    const factorEntries = [
        ["P", item.factors.p],
        ["F", item.factors.f],
        ["R", item.factors.r],
        ["T", item.factors.t],
        ["V", item.factors.v],
        ["S", item.factors.s],
    ] as const;
    return (
        <article className="entity-card">
            <div className="entity-header">
                <div className="entity-title">
                    <strong>{item.security_name || item.security_id}</strong>
                    <span>{item.security_id}</span>
                </div>
                <span className="status-badge status-danger">
                    {actionLabel(item.advised_action)}
                </span>
            </div>
            <div className="entity-body">
                <div className="notice">{positionSemantics(item)}</div>
                {pending ? <div className="alert">{pending}</div> : null}
                <div className="mini-grid">
                    <div className="mini-stat">
                        <span>持仓数量</span>
                        <strong>{item.quantity}</strong>
                    </div>
                    <div className="mini-stat">
                        <span>可卖数量</span>
                        <strong>可卖数量：{item.available_to_sell}</strong>
                    </div>
                    <div className="mini-stat">
                        <span>计划数量</span>
                        <strong>{item.planned_quantity}</strong>
                    </div>
                    <div className="mini-stat">
                        <span>平均成本 / 收盘</span>
                        <strong>{item.average_cost} / {item.close}</strong>
                    </div>
                    <div className="mini-stat">
                        <span>有效 / 建议止损</span>
                        <strong>
                            {displayValue(item.effective_stop)} / {displayValue(item.proposed_effective_stop)}
                        </strong>
                    </div>
                    <div className="mini-stat">
                        <span>R 倍数 / 百分位</span>
                        <strong>
                            {displayValue(item.r_multiple)} / {item.factors.percentile_rank}
                        </strong>
                    </div>
                </div>
                <div className="factor-grid" aria-label="六维因子">
                    {factorEntries.map(([name, value]) => (
                        <div className="factor" key={name}>
                            <small>{name}</small>
                            <strong>{value}</strong>
                        </div>
                    ))}
                </div>
                <div className="reason-list">
                    {item.reason_codes.map((code) => <span className="reason" key={code}>{code}</span>)}
                    {item.quality_codes.map((code) => <span className="reason" key={code}>{code}</span>)}
                </div>
                {item.evidence_refs.length > 0 ? (
                    <div className="disclosure">
                        <strong>证据：</strong>
                        {item.evidence_refs.map((ref) => <div key={ref}>{ref}</div>)}
                    </div>
                ) : null}
            </div>
        </article>
    );
}
