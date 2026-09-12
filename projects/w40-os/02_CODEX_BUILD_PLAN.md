# W40 / OS — Codex Build Plan

## 使用方式

Codex 每次只执行一个阶段。

不要一次性完成整个项目。

每个阶段完成后：

1. 启动项目
2. 浏览器检查
3. 汇报修改文件
4. 等待确认
5. 再进入下一阶段

---

# Phase 0 — 项目审计

如果已有项目，先执行：

```text
请先审计当前项目，不要修改任何文件。

输出：
1. 技术栈
2. 启动命令
3. 当前路由
4. 当前组件结构
5. 当前样式方案
6. 当前依赖
7. 是否可正常运行
8. 需要注意的风险

不要开始重构。
```

---

# Phase 1 — 建立项目骨架

## Prompt

```text
我要构建 W40 / OS，一个个人投资研究工作台 V1。

先阅读：
- 00_PRODUCT_SPEC.md
- 01_DESIGN_SYSTEM.md

本阶段只搭建全局骨架，不完成具体页面功能。

技术要求：
- Next.js
- TypeScript
- Tailwind CSS
- shadcn/ui
- Lucide icons
- mock data
- 不接数据库
- 不接真实金融 API
- 不接真实 AI API

创建一级路由：
- /today
- /invest
- /research
- /create

创建全局布局：
1. LeftNav
2. CommandBar
3. MainWorkspace
4. W40AIPanel

创建统一 Design Tokens。

左侧导航：
TODAY / 今日
INVEST / 投资
RESEARCH / 研究
CREATE / 内容

顶部：
搜索框
BTC / NDX / SOX / MU / MRVL ticker
通知
用户入口

右侧：
W40 AI 面板
只做 UI 与占位交互。

所有页面先用 placeholder。

不要实现业务细节。
不要增加不必要依赖。

完成后：
- 启动项目
- 告诉我访问地址
- 列出修改文件
- 停止继续开发
```

---

# Phase 2 — TODAY

```text
现在只实现 /today。

严格按照 00_PRODUCT_SPEC.md 和 01_DESIGN_SYSTEM.md。

页面核心：

1. 重要变化
2. 今日任务
3. 快速记录

可选：
- Watchlist
- Upcoming Events
- Ideas

但只有在页面仍然简洁时才加入。

重要变化使用 mock data：
- MRVL Guidance 上调
- AI × 电力研究更新
- BTC 波动率上升

今日任务：
- 更新 MRVL 基本面笔记
- 验证 AI × 电力 Thesis
- 写一条 X 内容

快速记录：
- 大输入框
- Note / Research / Content / Task 四种类型
- 本地保存即可

不要做：
- 自动分类
- 自动行情抓取
- 新闻流
- 日历系统
- 复杂任务管理

完成后启动项目并停止。
```

---

# Phase 3 — INVEST

```text
现在只实现 /invest。

V1 先做 MRVL Demo。

页面包含：

1. 股票列表
2. MRVL 基本信息
3. 基本面状态
4. 当前观点
5. 当前动作
6. 当前仓位
7. 最近变化
8. 核心 KPI
9. 加仓条件
10. 减仓条件
11. 退出条件
12. 催化事件
13. 历史决策

MRVL KPI：
- Data Center Revenue
- ASIC Revenue
- Gross Margin
- FCF
- Guidance

不要做：
- 自动置信度
- 自动仓位建议
- 自动估值模型
- 自动风险评分
- 自动止损
- 自动交易

所有数据使用 mock data。

右侧 W40 AI 根据页面上下文显示：
- 最近有什么变化
- 检查风险
- 挑战我的判断
- 生成投资摘要

不要修改其他页面。
完成后启动项目并停止。
```

---

# Phase 4 — RESEARCH

```text
现在只实现 /research。

Demo 主题：
AI × 电力

页面只保留：

1. 当前主题
2. 当前 Thesis
3. 核心问题
4. 支持证据
5. 反对证据
6. 待验证问题
7. 资料来源

不要做：
- 研究地图
- 知识图谱
- 自动证据评分
- 自动主题关系图
- 自动多股票关联
- 复杂图表

右侧 W40 AI：
- 总结 Thesis
- 找反证
- 梳理证据
- 生成研究摘要

所有数据用 mock data。

完成后启动项目并停止。
```

---

# Phase 5 — CREATE

```text
现在只实现 /create。

页面目标：
把研究和投资观点转成内容。

页面只保留：

1. 草稿
2. 已发布
3. 选题池
4. 当前编辑器

编辑器支持：
- 标题
- 正文
- Markdown
- 自动保存
- 保存草稿
- 标记已发布

右侧 W40 AI：
- 生成短帖
- 缩短一半
- 改成我的风格
- 生成标题

不要做：
- 自动发布 X
- X API
- 多平台分发
- 阅读量统计
- 粉丝增长
- 收益归因

完成后启动项目并停止。
```

---

# Phase 6 — 数据结构

```text
现在不要新增页面。

把现有 mock data 统一整理成数据模型：

Asset
Metric
Change
Topic
Evidence
Decision
Content
Task

要求：
- 类型定义集中
- mock data 集中
- 页面不要重复维护同一份数据
- 组件只通过 props 接收数据
- 避免硬编码散落在页面里

不要接数据库。
不要引入 ORM。

完成后列出：
- 数据结构
- 文件路径
- 页面引用关系
```

---

# Phase 7 — 组件抽取

```text
现在只做组件整理，不增加新功能。

检查以下是否可以抽成公共组件：

- PageHeader
- StatusBadge
- DataTable
- Timeline
- TickerBar
- EmptyState
- SectionCard
- W40AIPanel
- QuickCapture

目标：
减少重复代码。

不要为了抽象而抽象。
只有两个以上页面重复使用时再抽公共组件。
```

---

# Phase 8 — UI Review

建议开启新的 Codex 会话。

```text
你现在是 UI Reviewer，不是开发者。

不要直接修改代码。

请检查：

1. TODAY / INVEST / RESEARCH / CREATE 是否视觉统一
2. 是否存在重复信息
3. 是否存在无用途装饰
4. 是否科技感过强影响阅读
5. 是否符合“80%专业金融 + 20%未来科技”
6. 左侧导航是否统一
7. 顶部 Command Bar 是否统一
8. W40 AI 是否复用同一组件
9. 卡片是否过多
10. 字体与数字对齐是否专业
11. 1440px 是否协调
12. 1024px 是否溢出
13. 是否存在重复组件
14. 是否存在不必要依赖

输出：
P0 必须修复
P1 建议修复
P2 可选优化

先输出问题清单，不要修改。
```

---

# Phase 9 — Browser Acceptance

```text
按照验收清单逐页检查。

页面：
/today
/invest
/research
/create

检查：
- 页面能正常打开
- 导航可用
- ticker 不溢出
- AI panel 可折叠
- 所有按钮 hover 正常
- 所有表格对齐
- 中文没有截断
- 1024 / 1440 宽度正常
- 没有 console error
- npm run lint 通过
- npm run build 通过

最后输出：
1. 发现的问题
2. 已修问题
3. 未修问题
4. 下一阶段建议

不要新增功能。
```

---

# Codex 全局规则

每次任务都遵守：

1. 先读 Product Spec 和 Design System
2. 一次只做一个页面或一个范围
3. 不擅自加功能
4. 不擅自换技术栈
5. 不擅自增加依赖
6. 不擅自接 API
7. 不修改未授权页面
8. 改完必须启动并检查
9. 必须说明修改文件
10. 不把 mock data 写死到多个组件
11. UI 以信息为主，装饰不超过 20%
12. 不加入励志文案、空洞口号、装饰性状态块
