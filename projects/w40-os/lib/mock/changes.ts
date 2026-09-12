import type { Change } from "@/lib/types";

export const changes: ReadonlyArray<Change> = [
  { id: "change-mrvl-guidance", relatedType: "Asset", relatedId: "asset-mrvl", title: "FY26 Guidance 上调", description: "数据中心业务展望改善，需要更新基本面判断与核心 KPI。", direction: "positive", type: "GUIDANCE", happenedAt: "2026-09-10T09:40:00+08:00" },
  { id: "change-ai-power-update", relatedType: "Topic", relatedId: "topic-ai-power", title: "研究更新", description: "新增数据中心电力需求材料，核心 Thesis 仍需进一步验证。", direction: "neutral", type: "RESEARCH", happenedAt: "2026-09-10T08:25:00+08:00" },
  { id: "change-btc-volatility", relatedType: "Asset", relatedId: "asset-btc", title: "波动率明显上升", description: "30 日波动率扩大，短期风险暴露需要重新检查。", direction: "negative", type: "RISK", happenedAt: "2026-09-10T07:50:00+08:00" },
  { id: "change-mrvl-asic-project", relatedType: "Asset", relatedId: "asset-mrvl", title: "新增 ASIC 项目", description: "新项目进入验证阶段。", direction: "positive", type: "PROJECT", happenedAt: "2026-09-06T10:00:00+08:00" },
  { id: "change-mrvl-margin", relatedType: "Asset", relatedId: "asset-mrvl", title: "毛利率目标维持", description: "毛利率目标维持不变。", direction: "neutral", type: "MARGIN", happenedAt: "2026-08-30T10:00:00+08:00" },
  { id: "change-mrvl-concentration", relatedType: "Asset", relatedId: "asset-mrvl", title: "客户集中度风险上升", description: "单一客户收入占比继续上升。", direction: "negative", type: "RISK", happenedAt: "2026-08-22T10:00:00+08:00" },
];

export const todayChangeIds = ["change-mrvl-guidance", "change-ai-power-update", "change-btc-volatility"] as const;
