# W40 / OS — Product Spec V1

## 1. 产品定位

W40 / OS 是一个个人投资研究工作台。

它不是交易终端，也不是资讯门户。V1 只解决四个核心问题：

1. **今日**：今天有什么值得我处理？
2. **投资**：我关注的资产现在是什么状态，我要做什么？
3. **研究**：我的判断依据是什么？
4. **内容**：哪些认知值得输出？

V1 不追求全自动，不追求覆盖所有市场，不追求复杂量化能力。

核心原则：

> 先做一个每天愿意打开的个人投资 OS，再逐步自动化。

---

## 2. 一级导航

只保留 4 个一级模块：

- TODAY / 今日
- INVEST / 投资
- RESEARCH / 研究
- CREATE / 内容

不设置独立：
- 跟踪
- 决策
- Evidence
- Thesis
- Watch Center
- 复盘
- AI Assistant

这些都作为数据对象或页面组件存在。

---

## 3. 全局壳层

### 3.1 左侧导航

固定左侧栏：

- W40 / OS
- PERSONAL INVESTMENT SYSTEM
- TODAY
- INVEST
- RESEARCH
- CREATE

底部可放：
- 系统状态
- 本地时间

不要放励志语、品牌口号、装饰性文字。

### 3.2 顶部 Command Bar

顶部横条固定：

- 全局搜索
- BTC
- NDX
- SOX
- MU
- MRVL
- 通知入口
- 用户入口

行情条为紧凑 ticker，不做成大卡片。

### 3.3 AI

AI 不是一级页面。

右侧保留一个统一的 `W40 AI` 面板：

- 默认常驻或可折叠
- 根据当前页面自动带入上下文
- 不做 5 套不同 AI 助手

V1 只支持：

- 总结
- 找反证
- 梳理 Thesis
- 生成内容

---

# 4. TODAY / 今日

## 目标

回答：

> 今天有什么值得我处理？

## 页面只保留 3 个核心区块

### 4.1 重要变化

显示真正影响判断的变化，而不是普通行情：

示例：

- MRVL：FY26 Guidance 上调
- AI × 电力：微软提高数据中心 CapEx
- BTC：30 日波动率明显上升

字段：

- 标题
- 关联对象
- 时间
- 方向：正面 / 负面 / 中性
- 一句话说明

### 4.2 今日任务

示例：

- 更新 MRVL 基本面笔记
- 验证 AI × 电力 Thesis
- 写一条 X 内容

字段：

- 任务名称
- 状态
- 关联对象
- 优先级

### 4.3 快速记录

一个大输入框：

可输入：
- 想法
- 问题
- 链接
- 研究线索
- 内容灵感

V1 手动选择保存类型：

- Note
- Research
- Content
- Task

不要做复杂自动分类。

## 可选辅助区块

仅当页面仍保持简洁时加入：

- Watchlist
- Upcoming Events
- Ideas

---

# 5. INVEST / 投资

## 目标

回答：

> 我关注的资产现在是什么状态，我要做什么？

V1 先以 MRVL 为 Demo。

## 5.1 股票列表

左侧或上方展示：

- MRVL
- MU
- NVDA
- TSLA
- BTC

字段：

- Ticker
- 名称
- 当前价格
- 当日涨跌
- 当前状态

## 5.2 MRVL 详情页

顶部信息：

- MRVL / Marvell Technology
- 当前价格
- 当日涨跌

核心状态：

- 基本面：增强 / 不变 / 削弱
- 当前观点：看多 / 中性 / 看空
- 当前动作：持有 / 观察 / 加仓 / 减仓 / 退出
- 当前仓位
- 最后更新时间

不要自动计算“置信度 82%”。

## 5.3 最近变化

时间线形式：

- 日期
- 变化
- 类型
- 影响

示例：

- FY26 Guidance 上调
- 新增 ASIC 项目
- 毛利率目标维持
- 客户集中风险上升

## 5.4 核心 KPI

V1 表格即可，不做复杂小图：

MRVL 示例：

- Data Center Revenue
- ASIC Revenue
- Gross Margin
- FCF
- Guidance

字段：

- KPI
- 最新值
- 同比 / 环比
- 备注

## 5.5 操作条件

合并跟踪和决策。

只保留：

### 加仓条件
- 条件文本

### 减仓条件
- 条件文本

### 退出条件
- 条件文本

不做自动仓位建议。
不做自动估值模型。
不做自动止损建议。

## 5.6 催化事件

字段：

- 日期
- 事件
- 类型
- 是否已发生

示例：

- Earnings
- Investor Day
- 新产品发布
- 大客户项目更新

## 5.7 历史决策

字段：

- 日期
- 动作
- 仓位
- 原因
- 结果：正确 / 错误 / 未验证
- 备注

这也是未来复盘的数据基础。

---

# 6. RESEARCH / 研究

## 目标

回答：

> 我的判断依据是什么？

研究按主题，而不是按股票组织。

Demo 主题：

- AI × 电力

## 6.1 当前主题

展示：

- 主题名称
- 当前 Thesis
- 最后更新时间

## 6.2 核心问题

例如：

1. AI 数据中心到底带来多少新增电力需求？
2. 哪些环节能真正获得经济收益？
3. 供给约束在哪里？

## 6.3 Thesis

只保留一段清晰陈述：

示例：

> AI 算力扩张将推动未来 3–5 年全球电力需求显著增长，电网基础设施和关键电力设备环节更可能出现结构性机会。

不要放自动评分。

## 6.4 支持证据

字段：

- 标题
- 日期
- 来源
- 简短说明

## 6.5 反对证据

同上。

必须单独存在，防止研究只寻找支持观点的材料。

## 6.6 待验证问题

字段：

- 问题
- 状态
- 备注

## 6.7 资料来源

分类展示即可：

- 财报
- 新闻
- 研报
- 公司公告
- 会议纪要

V1 不做知识图谱。
V1 不做研究地图。
V1 不做复杂主题自动关联。

---

# 7. CREATE / 内容

## 目标

回答：

> 哪些认知值得输出？

## 7.1 内容状态

只保留：

- 草稿
- 已发布

V1 暂时不要“待发布”。

## 7.2 选题池

字段：

- 选题
- 来源：Invest / Research / Manual
- 标签
- 创建时间

## 7.3 编辑器

主要区域就是文章编辑器。

支持：

- 标题
- 正文
- Markdown
- 自动保存
- 保存草稿
- 标记已发布

## 7.4 AI 写作

右侧 W40 AI 提供：

- 生成短帖
- 改成我的风格
- 缩短一半
- 生成标题

V1 不做：

- 自动发布 X
- 多平台分发
- 阅读量抓取
- 粉丝增长分析
- 内容收益归因

---

# 8. V1 数据对象

底层优先保持简单。

## Asset

字段：

- id
- ticker
- name
- type
- price
- day_change
- status
- viewpoint
- action
- position
- updated_at

## Metric

字段：

- id
- asset_id
- name
- value
- change
- note
- updated_at

## Change

字段：

- id
- asset_id / topic_id
- title
- description
- direction
- type
- happened_at

## Topic

字段：

- id
- name
- thesis
- updated_at

## Evidence

字段：

- id
- topic_id
- side: support / counter
- title
- source
- date
- note

## Decision

字段：

- id
- asset_id
- action
- position
- reason
- result
- note
- created_at

## Content

字段：

- id
- title
- body
- status: draft / published
- source_type
- source_id
- created_at
- updated_at

## Task

字段：

- id
- title
- status
- priority
- related_type
- related_id
- created_at

---

# 9. V1 明确不做

以下全部不在第一版：

- 自动置信度评分
- 自动风险评分
- 自动仓位建议
- 自动估值模型
- 自动止损模型
- 知识图谱
- 研究地图
- 自动证据权重
- 自动多股票关联
- 自动新闻抓取
- 自动财报解析
- 自动修改 Thesis
- 自动交易
- 自动发布 X
- 内容数据分析
- 独立复盘页面
- 多 Agent 系统

---

# 10. 验收标准

V1 成功标准不是“功能多”。

而是能完成这一条链：

1. 在 TODAY 看到一个重要变化
2. 打开 MRVL 投资页
3. 更新基本面状态 / KPI / 操作条件
4. 进入 AI × 电力研究页更新 Thesis 或证据
5. 把研究结果转成一条内容草稿
6. 保存草稿
7. 在浏览器正常使用

如果这条链顺畅，V1 就成功。
