import type { Topic } from "@/lib/types";

export const topics: ReadonlyArray<Topic> = [
  { id: "topic-ai-power", name: "AI × 电力", thesis: "AI 算力扩张将推动未来 3–5 年全球电力需求显著增长，电网基础设施与关键电力设备环节可能出现结构性机会。", updatedAt: "2026-09-10 10:20" },
  { id: "topic-ai-asic", name: "AI ASIC / Data Center", thesis: "", updatedAt: "2026-09-10 09:40" },
];

export const primaryResearchTopicId = "topic-ai-power";
export const primaryInvestTopicId = "topic-ai-asic";

export const researchQuestions = [
  { topicId: "topic-ai-power", question: "AI 数据中心会带来多少新增电力需求？", status: "进行中" },
  { topicId: "topic-ai-power", question: "哪些电力环节真正能获得经济收益？", status: "待研究" },
  { topicId: "topic-ai-power", question: "哪些供给约束可能限制需求增长？", status: "已验证" },
] as const;

export const openResearchQuestions = [
  { topicId: "topic-ai-power", question: "美国电网扩容能否跟上需求？", status: "待验证", note: "关注并网周期与输电项目审批进度。" },
  { topicId: "topic-ai-power", question: "中国电力基础设施的瓶颈在哪里？", status: "待验证", note: "区分发电、输电与区域调度约束。" },
  { topicId: "topic-ai-power", question: "电价上涨会不会抑制数据中心扩张？", status: "进行中", note: "验证电力成本在整体 TCO 中的敏感度。" },
] as const;

export const researchSources = [
  { topicId: "topic-ai-power", type: "财报", count: 8, updatedAt: "SEP 08" },
  { topicId: "topic-ai-power", type: "新闻", count: 14, updatedAt: "SEP 07" },
  { topicId: "topic-ai-power", type: "研报", count: 6, updatedAt: "SEP 03" },
  { topicId: "topic-ai-power", type: "公司公告", count: 5, updatedAt: "AUG 27" },
  { topicId: "topic-ai-power", type: "会议纪要", count: 4, updatedAt: "AUG 22" },
] as const;
