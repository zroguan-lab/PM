export const aiActions = {
  default: ["总结", "找反证", "梳理 Thesis", "生成内容"],
  today: ["总结今日重点", "梳理待处理", "生成今日计划", "解释重要变化"],
  invest: ["最近有什么变化？", "检查风险", "挑战我的判断", "生成投资摘要"],
  research: ["总结 Thesis", "找反证", "梳理证据", "生成研究摘要"],
  create: ["生成短帖", "缩短一半", "改成我的风格", "生成标题"],
} as const;

export const aiActionsByPath = {
  "/today": aiActions.today,
  "/invest": aiActions.invest,
  "/research": aiActions.research,
  "/create": aiActions.create,
} as const;

export const captureTypes = ["Note", "Research", "Content", "Task"] as const;

export const actionRules = [
  { assetId: "asset-mrvl", key: "ADD", label: "加仓条件", tone: "positive", rules: ["ASIC 收入增速连续两个季度高于 30%", "回调后估值进入计划区间", "数据中心 Guidance 再次上调"] },
  { assetId: "asset-mrvl", key: "REDUCE", label: "减仓条件", tone: "warning", rules: ["数据中心增速连续两个季度放缓", "毛利率跌破 60% 且指引未改善", "单一客户收入占比继续上升"] },
  { assetId: "asset-mrvl", key: "EXIT", label: "退出条件", tone: "negative", rules: ["核心 ASIC 项目取消或大幅延期", "基本面判断转为削弱", "现金流与利润趋势同时恶化"] },
] as const;

export const catalysts = [
  { assetId: "asset-mrvl", date: "SEP 26", event: "Earnings", status: "UPCOMING" },
  { assetId: "asset-mrvl", date: "OCT 15", event: "Investor Day", status: "UPCOMING" },
  { assetId: "asset-mrvl", date: "NOV 08", event: "ASIC 项目更新", status: "TRACKING" },
  { assetId: "asset-mrvl", date: "DEC 03", event: "产品发布", status: "UNCONFIRMED" },
] as const;
