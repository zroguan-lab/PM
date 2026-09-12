import type { Evidence } from "@/lib/types";

export const evidence: ReadonlyArray<Evidence> = [
  { id: "evidence-capex", topicId: "topic-ai-power", side: "support", title: "云厂商继续提高数据中心 CapEx", date: "2026-09-08", source: "公司财报", note: "主要云厂商资本开支指引继续上调，AI 基础设施仍是优先方向。" },
  { id: "evidence-power-demand", topicId: "topic-ai-power", side: "support", title: "数据中心用电需求持续上升", date: "2026-09-03", source: "行业研报", note: "新增机架功率密度提升，区域电网负荷压力正在扩大。" },
  { id: "evidence-transformers", topicId: "topic-ai-power", side: "support", title: "变压器交付周期延长", date: "2026-08-27", source: "会议纪要", note: "大型电力变压器供应紧张，交付周期仍显著高于历史均值。" },
  { id: "evidence-grid-orders", topicId: "topic-ai-power", side: "support", title: "电网设备订单保持增长", date: "2026-08-19", source: "公司公告", note: "输配电设备企业在手订单增长，需求能见度进一步提高。" },
  { id: "evidence-chip-efficiency", topicId: "topic-ai-power", side: "counter", title: "AI 芯片能效持续提升", date: "2026-09-05", source: "技术报告", note: "单位算力耗电下降，可能部分抵消总算力规模扩张带来的需求。" },
  { id: "evidence-renewables", topicId: "topic-ai-power", side: "counter", title: "可再生能源供给快速扩张", date: "2026-08-31", source: "行业新闻", note: "新增清洁能源装机可能缓解部分区域的电力供给压力。" },
  { id: "evidence-policy", topicId: "topic-ai-power", side: "counter", title: "部分地区限制数据中心建设", date: "2026-08-16", source: "政策公告", note: "电网容量和用水约束令部分项目审批周期延长。" },
];
