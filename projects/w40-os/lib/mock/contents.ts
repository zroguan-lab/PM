import type { Content } from "@/lib/types";

export const contents: ReadonlyArray<Content> = [
  { id: "content-mrvl-logic", title: "MRVL 财报后的投资逻辑变化", body: "## 核心变化\n\nMRVL 最新指引上调后，市场关注点正在从短期订单验证转向 ASIC 项目的持续放量。\n\n### 当前判断\n\n- 数据中心收入仍是主要增长来源\n- 毛利率维持稳定，产品组合继续改善\n- 客户集中度风险需要持续跟踪\n\n这次变化增强了基本面判断，但还不足以改变当前持有动作。", status: "DRAFT", sourceType: "Asset", sourceId: "asset-mrvl", createdAt: "2026-09-10 10:00", updatedAt: "10 MIN AGO" },
  { id: "content-ai-power", title: "AI × 电力的长期机会", body: "## 核心观点\n\n电力需求增长只是起点，更重要的是识别供给约束最强、订单能见度最高的基础设施环节。", status: "DRAFT", sourceType: "Topic", sourceId: "topic-ai-power", createdAt: "2026-09-10 09:00", updatedAt: "1 HOUR AGO" },
  { id: "content-memory-cycle", title: "存储周期是否重新启动", body: "## 待验证\n\n需要区分传统存储周期修复与 AI 服务器带来的结构性需求，避免把短期价格上涨等同于长期景气反转。", status: "DRAFT", sourceType: "Manual", sourceId: null, createdAt: "2026-09-09", updatedAt: "YESTERDAY" },
  { id: "content-btc-liquidity", title: "BTC 当前流动性变化", body: "BTC 波动率重新上升，但现阶段更重要的是判断流动性来源是否具有持续性。", status: "PUBLISHED", sourceType: "Asset", sourceId: "asset-btc", createdAt: "2026-09-08", updatedAt: "SEP 08", publishedAt: "2026-09-08 18:30" },
];

export const contentIdeas = [
  { id: "idea-mrvl", title: "MRVL 财报后的投资逻辑变化", sourceType: "Asset", sourceId: "asset-mrvl", tag: "SEMICONDUCTOR" },
  { id: "idea-power", title: "AI × 电力的长期机会", sourceType: "Topic", sourceId: "topic-ai-power", tag: "INFRASTRUCTURE" },
  { id: "idea-memory", title: "存储周期是否重新启动", sourceType: "Asset", sourceId: "asset-mu", tag: "MEMORY" },
  { id: "idea-agent", title: "AI Agent 会不会重塑 SaaS", sourceType: "Manual", sourceId: null, tag: "SOFTWARE" },
  { id: "idea-btc", title: "BTC 当前流动性变化", sourceType: "Asset", sourceId: "asset-btc", tag: "CRYPTO" },
] as const;
