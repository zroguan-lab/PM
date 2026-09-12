import type { Metric } from "@/lib/types";

export const metrics: ReadonlyArray<Metric> = [
  { id: "metric-mrvl-dc-revenue", assetId: "asset-mrvl", name: "Data Center Revenue", value: "$1.10B", change: "+69% YoY", note: "AI 相关需求保持强劲", updatedAt: "2026-09-10" },
  { id: "metric-mrvl-asic-revenue", assetId: "asset-mrvl", name: "ASIC Revenue", value: "$420M", change: "+34% QoQ", note: "新项目进入放量阶段", updatedAt: "2026-09-10" },
  { id: "metric-mrvl-gross-margin", assetId: "asset-mrvl", name: "Gross Margin", value: "63.2%", change: "+40bps QoQ", note: "产品组合改善", updatedAt: "2026-09-10" },
  { id: "metric-mrvl-fcf", assetId: "asset-mrvl", name: "FCF", value: "$382M", change: "+18% YoY", note: "现金转化稳定", updatedAt: "2026-09-10" },
  { id: "metric-mrvl-guidance", assetId: "asset-mrvl", name: "Guidance", value: "$2.18B", change: "+6% vs. prior", note: "FY26 展望上调", updatedAt: "2026-09-10" },
];
