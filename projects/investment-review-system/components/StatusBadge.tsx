import { statusOf, type JudgmentRow } from "@/lib/types";

export default function StatusBadge({ row }: { row: Pick<JudgmentRow, "due_date" | "outcome"> }) {
  const status = statusOf(row);
  const cls = status === "已复盘" ? "done" : status === "待复盘" ? "pending" : "active";
  return <span className={`badge ${cls}`}>{status}</span>;
}
