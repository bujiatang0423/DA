import type { HoldingResult } from "./api";

export type HoldingItem = HoldingResult["items"][number];

const actionLabels: Record<string, string> = {
  hold: "继续持有",
  exit_all: "全部退出",
  reduce_half: "减仓一半",
  trim_one_third: "减仓三分之一",
  raise_stop: "上移止损",
  add: "允许加仓",
  pending_exit: "退出待执行",
  manual_review: "人工复核",
};

export function actionLabel(action: string): string {
  return actionLabels[action] ?? action;
}

export function positionSemantics(item: HoldingItem): string {
  if (item.origin === "legacy_opening_balance" && item.strategy_book === null) {
    return "历史期初持仓，未追认策略账本";
  }
  return item.strategy_book
    ? `策略账本：${item.strategy_book}`
    : "策略账本：未指定";
}

export function pendingExecutionLabel(item: HoldingItem): string | null {
  const exitActions = new Set(["exit_all", "reduce_half", "trim_one_third"]);
  if (item.available_to_sell === 0 && exitActions.has(item.advised_action)) {
    return "T+1 锁定，退出待执行";
  }
  return item.pending_target_action
    ? `待执行目标：${actionLabel(item.pending_target_action)}`
    : null;
}

export function displayValue(value: string | number | null): string {
  return value === null ? "-" : String(value);
}
