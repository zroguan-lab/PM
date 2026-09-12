export type Decision = "buy" | "add" | "hold" | "reduce" | "sell" | "abandon";
export type Outcome = "correct" | "partially_correct" | "incorrect" | "indeterminate";
export type Attribution = "skill" | "beta" | "luck" | "mixed";

export const decisionLabels: Record<Decision, string> = {
  buy: "买入", add: "加仓", hold: "持有", reduce: "减仓", sell: "卖出", abandon: "放弃"
};
export const outcomeLabels: Record<Outcome, string> = {
  correct: "正确", partially_correct: "部分正确", incorrect: "错误", indeterminate: "无法判断"
};
export const attributionLabels: Record<Attribution, string> = {
  skill: "能力", beta: "市场 Beta", luck: "运气", mixed: "混合"
};

export type JudgmentRow = {
  id: string; judgment_date: string; symbol: string; asset_type: string; thesis: string;
  evidence: string; decision: Decision; confidence: number; horizon_type: string; due_date: string;
  reference_price: number | null; benchmark: string | null; created_at: string; updated_at: string;
  archived_at: string | null; tags?: string; outcome?: Outcome | null; actual_return?: number | null;
  excess_return?: number | null;
};

export function statusOf(row: Pick<JudgmentRow, "due_date" | "outcome">, today = localDate()) {
  if (row.outcome) return "已复盘";
  return row.due_date <= today ? "待复盘" : "验证中";
}

export function localDate(date = new Date()) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function dueDate(from: string, horizon: string, custom?: string) {
  if (horizon === "custom") return custom || from;
  const date = new Date(`${from}T12:00:00`);
  if (horizon === "1y") date.setFullYear(date.getFullYear() + 1);
  else date.setDate(date.getDate() + Number(horizon.replace("d", "")));
  return localDate(date);
}
