import { useState } from "react";

import type { ManualFill, PositionPage } from "./api";

interface Props {
    page: PositionPage;
    pending: boolean;
    onCancel: () => void;
    onSubmit: (request: ManualFill) => void;
}

export function ManualFillForm({ page, pending, onCancel, onSubmit }: Props): JSX.Element {
    const first = page.items[0];
    const [securityId, setSecurityId] = useState(first?.security_id ?? "");
    const [side, setSide] = useState<"buy" | "sell">("sell");
    const [quantity, setQuantity] = useState("1");
    const [price, setPrice] = useState("");
    const [fee, setFee] = useState("0");
    return (
        <form
            className="panel page-shell"
            onSubmit={(event) => {
                event.preventDefault();
                onSubmit({
                    portfolio_id: page.portfolio_id,
                    expected_version: page.version,
                    security_id: securityId,
                    side,
                    quantity: Number(quantity),
                    price,
                    fee,
                    executed_at: page.as_of_time,
                });
            }}
        >
            <div className="panel-title">
                <h2>记录实际成交</h2>
                <span>价格和费用来自真实成交回报</span>
            </div>
            <div className="control-grid">
                <label className="field">
                    证券
                    <select onChange={(event) => setSecurityId(event.target.value)} value={securityId}>
                        {page.items.map((item) => (
                            <option key={item.security_id} value={item.security_id}>{item.security_id}</option>
                        ))}
                    </select>
                </label>
                <label className="field">
                    方向
                    <select
                        onChange={(event) => setSide(event.target.value as "buy" | "sell")}
                        value={side}
                    >
                        <option value="sell">卖出</option>
                        <option value="buy">买入</option>
                    </select>
                </label>
                <label className="field">
                    实际数量
                    <input min="1" onChange={(event) => setQuantity(event.target.value)} type="number" value={quantity} />
                </label>
                <label className="field">
                    实际成交价
                    <input min="0.000001" onChange={(event) => setPrice(event.target.value)} required step="any" value={price} />
                </label>
                <label className="field">
                    实际费用
                    <input min="0" onChange={(event) => setFee(event.target.value)} required step="any" value={fee} />
                </label>
            </div>
            <div className="inline-actions">
                <button className="btn" disabled={pending} type="submit">保存实际成交</button>
                <button className="btn btn-secondary" onClick={onCancel} type="button">取消</button>
            </div>
        </form>
    );
}
