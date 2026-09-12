import type { Task } from "@/lib/types";

export const tasks: ReadonlyArray<Task> = [
  { id: "task-update-mrvl", title: "更新 MRVL 基本面笔记", status: "pending", priority: "HIGH", relatedType: "Asset", relatedId: "asset-mrvl", createdAt: "2026-09-10" },
  { id: "task-verify-power-thesis", title: "验证 AI × 电力 Thesis", status: "pending", priority: "MEDIUM", relatedType: "Topic", relatedId: "topic-ai-power", createdAt: "2026-09-10" },
  { id: "task-write-content", title: "写一条 X 内容", status: "pending", priority: "LOW", relatedType: "Content", relatedId: "content-mrvl-logic", createdAt: "2026-09-10" },
];

export const todayTaskIds = ["task-update-mrvl", "task-verify-power-thesis", "task-write-content"] as const;
