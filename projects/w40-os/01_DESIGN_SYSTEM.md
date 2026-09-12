# W40 / OS — Design System V1

## 1. 设计目标

整体风格：

> 80% 专业金融工作台 + 20% 未来科技系统感

参考气质：

- Bloomberg：金融专业性
- Linear：克制与秩序
- Palantir：情报系统感
- JARVIS：智能系统存在感

避免：

- 满屏发光
- 过多 HUD 圆环
- 六边形装饰
- 机械切角
- 大面积动态背景
- 无意义状态文字
- 励志语
- 纯装饰性模块

所有视觉元素都必须服务于信息和操作。

---

# 2. 页面骨架

桌面端优先。

推荐宽度：

- 1440px 以上最佳
- 1024px 可用
- 移动端 V1 仅保证基本可访问，不做重点优化

布局：

```text
┌─────────────────────────────────────────────────────┐
│ Global Command Bar                                  │
├──────────┬───────────────────────────────┬──────────┤
│ Left Nav │ Main Workspace                │ W40 AI   │
│          │                               │          │
└──────────┴───────────────────────────────┴──────────┘
```

推荐：

- 左侧导航：200–220px
- AI 面板：300–340px
- 中间主区：自适应

AI 面板允许折叠。

---

# 3. 颜色

## 背景

```css
--bg: #070B10;
--surface: #0D131B;
--surface-2: #111923;
--surface-hover: #151F2C;
--border: #1B2838;
--border-subtle: #13202D;
```

## 文本

```css
--text-primary: #F4F7FA;
--text-secondary: #9AA8B7;
--text-muted: #657586;
```

## 系统色

```css
--blue: #3B82F6;
--blue-bright: #60A5FA;
--positive: #22C55E;
--negative: #EF4444;
--warning: #F59E0B;
```

规则：

- 蓝色：系统、交互、选中状态
- 绿色：正向基本面 / 正收益 / 正变化
- 红色：风险 / 负变化
- 黄色：提醒 / 未确认
- 不要用颜色做无意义装饰

---

# 4. 字体

## 英文与数字

优先：

- Space Grotesk
- IBM Plex Mono
- Geist Mono
- DIN 风格替代字体

推荐：

- 页面标题：Space Grotesk / 600
- ticker / 数字 / KPI：IBM Plex Mono / 500

## 中文

优先：

- 思源黑体
- Noto Sans SC
- HarmonyOS Sans SC

规则：

- 中文标题不使用过圆字体
- 正文 14–15px
- 卡片标题 14–16px
- 页面标题 28–34px
- KPI 数字 24–36px
- ticker 12–13px

科技感主要依赖排版与数字字体，不依赖夸张“科幻字体”。

---

# 5. 字距与层级

标签可使用 uppercase：

- SIGNALS
- FOCUS
- THESIS
- EVIDENCE
- KPI
- EVENTS

中文作为次级说明。

示例：

```text
SIGNALS
重要变化
```

不要中英文都很大。

---

# 6. 卡片

卡片原则：

- 少
- 大
- 信息集中
- 不做卡片套卡片

推荐：

```css
border: 1px solid var(--border);
border-radius: 10px;
background: var(--surface);
```

阴影极轻或无。

只允许在：

- 当前选中
- AI 正在分析
- 重大变化

出现极轻微 glow。

---

# 7. 科幻装饰比例

最多 20%。

允许：

- 极轻微网格背景
- AI 状态轻 pulse
- 数据更新轻微闪烁
- 边角细线
- 极少量扫描线 / 微动画

不允许：

- 大圆环长期占据空间
- 无信息价值的 3D 地球
- 纯装饰型波纹
- 高频动画
- 发光边框包围所有卡片

---

# 8. 顶部行情条

ticker 形式，不使用卡片堆叠。

示例：

```text
BTC  63,248  +1.8%
NDX  17,084  +0.7%
SOX   4,982  +1.4%
MU      125  +2.1%
MRVL   74.6  +2.4%
```

数字使用等宽字体。

---

# 9. 左侧导航

一级导航：

- TODAY
- INVEST
- RESEARCH
- CREATE

英文主标签 + 中文小字。

选中状态：

- 左侧细蓝线
- 背景轻微提亮
- 不使用大面积 neon glow

---

# 10. W40 AI

标题：

`W40 AI`

状态：

- READY
- ANALYZING
- OFFLINE

默认控件：

- 输入框
- 4 个上下文动作
- 最近对话

不同页面自动切换动作。

TODAY：

- 总结今日重点
- 梳理待处理
- 生成今日计划
- 解释重要变化

INVEST：

- 最近有什么变化
- 检查风险
- 挑战我的判断
- 生成投资摘要

RESEARCH：

- 总结 Thesis
- 找反证
- 梳理证据
- 生成研究摘要

CREATE：

- 生成短帖
- 缩短一半
- 改成我的风格
- 生成标题

---

# 11. 图标

使用简单线性图标。

推荐：

- Lucide Icons

不要混用多个图标库。

---

# 12. 动效

V1 只保留：

- hover
- panel open / close
- route transition
- status pulse
- loading

时长：

- 120–220ms

不要粒子动画。
不要持续旋转装饰。
不要背景视频。

---

# 13. Design Tokens

建议写入全局 CSS：

```css
:root {
  --bg: #070B10;
  --surface: #0D131B;
  --surface-2: #111923;
  --surface-hover: #151F2C;

  --border: #1B2838;
  --border-subtle: #13202D;

  --text-primary: #F4F7FA;
  --text-secondary: #9AA8B7;
  --text-muted: #657586;

  --blue: #3B82F6;
  --blue-bright: #60A5FA;
  --positive: #22C55E;
  --negative: #EF4444;
  --warning: #F59E0B;

  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;

  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-8: 32px;
}
```

---

# 14. 设计验收

每个页面完成后检查：

- 是否存在无用途装饰
- 是否重复展示同一信息
- 颜色是否只表达状态或交互
- 是否有卡片过多问题
- 视觉重点是否清楚
- 1024px 是否溢出
- 1440px 是否有良好信息密度
- AI 区是否影响主内容阅读
- 数字是否对齐
- 字体是否统一
