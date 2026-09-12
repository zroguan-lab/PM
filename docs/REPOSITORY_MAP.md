# 仓库与开发入口

## 权威来源

| 项目 | 权威开发入口 | 历史处理 | 后续修改 |
|---|---|---|---|
| PM-BTC / 量化工作台 | 本仓库 `projects/quant-workbench/` | Python 核心此前无 Git 仓库；前端已有提交历史已通过子树保留，当前未提交工作态另作快照提交 | 本仓库 |
| W40 / OS | 本仓库 `projects/w40-os/` | 原目录无 Git 仓库，以 2026-09-12 安全快照建立版本边界 | 本仓库 |
| 投资决策复盘系统 | 本仓库 `projects/investment-review-system/` | 原目录无 Git 仓库，以 2026-09-12 安全快照建立版本边界 | 本仓库 |
| Binance Futures Lab | `zroguan-lab/AI-Trading8.22` | 保留原仓库、Issue、PR、CI 和提交历史；本仓库只维护入口说明，不复制代码 | 独立仓库 |

## 克隆

```bash
git clone https://github.com/zroguan-lab/project-collaboration-hub.git
```

Binance Futures Lab 需在接受 `AI-Trading8.22` 的独立协作邀请后另行克隆。

## 版本边界

- 本仓库的首次快照提交是三套本机项目的可恢复边界。
- PM-BTC 前端的更早提交可在本仓库历史中追溯。
- 本仓库不反向覆盖原来的 `D:\\codex项目` 目录；原目录仍可作为本机运行参考，但不再作为顾问协作的共享事实源。
