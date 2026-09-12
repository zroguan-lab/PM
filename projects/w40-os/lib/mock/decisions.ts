import type { Decision } from "@/lib/types";

export const decisions: ReadonlyArray<Decision> = [
  { id: "decision-mrvl-hold-aug", assetId: "asset-mrvl", action: "持有", position: "6%", reason: "Guidance 维持，等待新 ASIC 项目确认", result: "未验证", note: "", createdAt: "2026-08-28" },
  { id: "decision-mrvl-add-jun", assetId: "asset-mrvl", action: "加仓", position: "6%", reason: "数据中心收入超预期", result: "正确", note: "", createdAt: "2026-06-04" },
  { id: "decision-mrvl-watch-mar", assetId: "asset-mrvl", action: "观察", position: "4%", reason: "毛利率压力尚未解除", result: "错误", note: "", createdAt: "2026-03-12" },
];
