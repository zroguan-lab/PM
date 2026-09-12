# W40 / OS：项目现状

状态日期：2026-09-12。

## 在做什么

个人投资研究工作台，围绕“今天处理什么、资产现在是什么状态、判断依据是什么、哪些认知值得输出”组织日常工作。V1 明确不是交易终端，也不追求复杂量化或多 Agent。

## 已有成果

- Next.js 16.3.4、React 19、TypeScript、Tailwind CSS 4。
- 完成统一壳层：左侧导航、Command Bar、主工作区、可折叠 W40 AI 面板。
- `/today`、`/invest`、`/research`、`/create` 四个页面均已有实现。
- 资产、指标、变化、主题、证据、决策、内容、任务类型和 mock 数据已集中管理；共享组件已抽取。
- 四张阶段截图可直接查看已有 UI。

## 当前做到哪里

构建计划的 Phase 1–7 在源码中已有明显落地证据：页面不再只是 placeholder，数据模型与公共组件已经集中。当前仍是前端原型：快速记录、编辑器和 AI 面板没有真实持久化/API/模型执行路径，行情也不是实时数据。

本次验证中 `npm run lint` 通过。原目录因正在运行的 Next 构建目录被锁，首次 `npm run build` 在写 `.next/trace-build` 时出现 Windows `EPERM`；在不复用该构建目录的干净隔离副本中，生产构建通过，五个页面路由均成功静态生成。

## 当前卡点

1. 需要先完成 Phase 8/9 的 UI 与浏览器验收，明确 1024/1440 布局、交互和控制台状态。
2. V1 仍缺持久化与真实数据接入的产品决定；规格当前明确“不接数据库/真实金融 API/真实 AI API”，不能把 mock 行为描述成完成闭环。
3. W40 AI 目前是禁用输入和动作占位，不具备执行能力。

## 先看与怎么跑

- [00_PRODUCT_SPEC.md](00_PRODUCT_SPEC.md)
- [01_DESIGN_SYSTEM.md](01_DESIGN_SYSTEM.md)
- [02_CODEX_BUILD_PLAN.md](02_CODEX_BUILD_PLAN.md)
- 页面实现：`app/`、`components/`
- 类型与数据：`lib/types.ts`、`lib/mock/`

```powershell
npm install
npm run lint
npm run build
npm run dev
```

未知：没有生产部署、真实用户使用或业务数据闭环的证据。
