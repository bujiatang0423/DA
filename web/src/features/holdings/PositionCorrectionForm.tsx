import { useState } from "react";

import type { PositionCorrection, PositionPage } from "./api";

interface Props {
  page: PositionPage;
  pending: boolean;
  onCancel: () => void;
  onSubmit: (request: PositionCorrection) => void;
}

export function PositionCorrectionForm({
  page,
  pending,
  onCancel,
  onSubmit,
}: Props): JSX.Element {
  const [reason, setReason] = useState("");
  const [quantities, setQuantities] = useState<Record<string, string>>(
    Object.fromEntries(
      page.items.map((item) => [item.security_id, String(item.quantity)]),
    ),
  );
  return (
    <form
      className="panel page-shell"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit({
          portfolio_id: page.portfolio_id,
          expected_version: page.version,
          reason,
          positions: page.items.map((item) => ({
            security_id: item.security_id,
            quantity: Number(quantities[item.security_id]),
            average_cost: item.average_cost,
            effective_at: page.as_of_time,
          })),
        });
      }}
    >
      <div className="panel-title">
        <h2>人工校正，不是历史成交</h2>
        <span>当前版本 {page.version}</span>
      </div>
      {page.items.map((item) => (
        <label className="field" key={item.security_id}>
          {item.security_id} 校正数量
          <input
            min="0"
            onChange={(event) =>
              setQuantities({
                ...quantities,
                [item.security_id]: event.target.value,
              })
            }
            type="number"
            value={quantities[item.security_id]}
          />
        </label>
      ))}
      <label className="field">
        校正原因
        <textarea
          minLength={5}
          onChange={(event) => setReason(event.target.value)}
          required
          value={reason}
        />
      </label>
      <div className="inline-actions">
        <button className="btn" disabled={pending} type="submit">
          确认人工校正
        </button>
        <button className="btn btn-secondary" onClick={onCancel} type="button">
          取消
        </button>
      </div>
    </form>
  );
}
