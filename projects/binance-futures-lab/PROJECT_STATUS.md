# Binance Futures Lab：项目现状

状态日期：2026-09-12。权威代码库：[zroguan-lab/AI-Trading8.22](https://github.com/zroguan-lab/AI-Trading8.22)。本目录只保存顾问入口说明，代码不在总览仓库重复维护。

## 在做什么

TypeScript 全栈的 Binance 期货研究实验室。支持本地 paper 撮合与 Binance 官方 USDⓈ-M Futures Testnet 执行；主网真实下单仍故意禁用。V4–V6 研究策略稳健性，另有只读六 Agent 影子协作链，用于衡量 AI 建议相对确定性系统是否增加 Alpha。

## 已有成果

- paper_local 与 binance_testnet 两种执行后端，数据采集、持仓恢复、保护单、诊断和仪表盘路径。
- 版本化策略、Shadow Ledger、Coordinator 结果归因、确定性 Promotion Gate。
- Agent 层不拥有 Broker/Risk/Order 权限，不能绕过确定性风控或开启主网。
- `main` 最近一次提交为 2026-08-23 合并的 PR #15：Trade Reviewer 只使用入场前的版本化 Agent 上下文，避免事后信息泄漏。

## 当前做到哪里与卡点

截至整理时：

- PR [#16](https://github.com/zroguan-lab/AI-Trading8.22/pull/16) open：在 API/仪表盘展示真实 Promotion Gate 指标。
- PR [#17](https://github.com/zroguan-lab/AI-Trading8.22/pull/17) open：强化 Alpha 数据完整性、去重、时间与 regime 归因。
- PR [#19](https://github.com/zroguan-lab/AI-Trading8.22/pull/19) open：只读的实时开发协作监控；其说明要求在数据语义 PR 后再合并或 rebase。

主要业务卡点不是缺交易入口，而是 AI 辅助资格仍需足够的干净已复盘样本、正期望、PF、滚动窗口与跨品种稳健性证据。Mainnet adapter 仍有意未实现。

## 建议开始位置

1. 读独立仓库 `README.md` 的 Safety、V6、Shadow multi-agent collaboration。
2. 依次审阅 #17、#16，再处理 #19 的 rebase/合并顺序。
3. 查看 Issue #1 的 AI quant roadmap，并用真实诊断输出判断是否达到 Promotion Gate。

未知：本次没有访问该项目的私有运行数据库或 `.env`，因此不声称当前样本数、收益、账户连接或 testnet 在线状态。
