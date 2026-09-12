# Project Collaboration Hub

顾问协作的统一入口。内容按 2026-09-12 可核验的本地材料、代码、测试结果和 GitHub 状态整理；未知项明确保留为未知，不把计划当成已完成功能。

## 从这里开始

1. 先读 [仓库与开发入口](docs/REPOSITORY_MAP.md)，确认每个项目应在哪里修改。
2. 按优先级阅读各项目的 `PROJECT_STATUS.md`。
3. 需要参与开发时，遵循 [CONTRIBUTING.md](CONTRIBUTING.md)；不要提交凭证、个人数据库或运行数据。

## 项目总览

| 项目 | 当前定位与阶段 | 代码入口 | 建议先看 |
|---|---|---|---|
| PM-BTC / 量化工作台 | Polymarket BTC 5 分钟错误定价研究工作台；数据链、研究核心、门禁和只读前端已实现，保持 `RESEARCH_ONLY / NO_TRADE`；当前业务阻塞是 Alpha 校准与发布门禁未通过 | 本仓库 `projects/quant-workbench/` | [项目现状](projects/quant-workbench/PROJECT_STATUS.md) · [路线图](projects/quant-workbench/docs/new-goal-roadmap.md) |
| W40 / OS | 个人投资研究工作台；TODAY / INVEST / RESEARCH / CREATE 四个页面和统一 UI 已落地，目前仍是集中 mock data 的前端原型 | 本仓库 `projects/w40-os/` | [项目现状](projects/w40-os/PROJECT_STATUS.md) · [产品规格](projects/w40-os/00_PRODUCT_SPEC.md) |
| 投资决策复盘系统 | 本机单用户、离线优先的投资判断记录与复盘 V1；表单、复盘、状态规则、SQLite 和导出路径已实现 | 本仓库 `projects/investment-review-system/` | [项目现状](projects/investment-review-system/PROJECT_STATUS.md) · [产品规格](projects/investment-review-system/docs/v1-product-spec.md) |
| Binance Futures Lab | Binance 期货 paper/testnet 研究实验室；继续使用既有独立私有仓库和完整历史；主网下单仍故意禁用 | 独立仓库 [zroguan-lab/AI-Trading8.22](https://github.com/zroguan-lab/AI-Trading8.22) | [项目现状](projects/binance-futures-lab/PROJECT_STATUS.md) · [代码入口](projects/binance-futures-lab/source/README.md) |

## 已核验的关键结论

- PM-BTC Python 核心：84 项测试通过；前端生产构建与 2 项渲染测试通过。
- W40 / OS：ESLint 通过；在本仓库干净副本中的构建结果见 [验证记录](docs/VALIDATION.md)。
- 投资决策复盘系统：3 项核心规则测试通过；干净副本构建结果见 [验证记录](docs/VALIDATION.md)。
- Binance Futures Lab：`main` 最近一次合并为 PR #15；PR #16、#17、#19 截至整理时仍为 open。
- 原项目目录未移动、未删除；本仓库是可协作的安全快照与统一入口。

## 不在本次协作包内

`封面`、`SKILL` 是内容/视觉资产集合，`粒子` 为空目录，`mirofish` 是较早的第三方实验副本且带本地配置。这些不具备与四个当前产品同等的独立项目证据，因此没有混入代码协作入口。取舍与排除项见 [共享边界](docs/SHARING_BOUNDARY.md)。
