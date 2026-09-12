# PM-BTC / 量化工作台：项目现状

状态日期：2026-09-12。

## 在做什么

研究 Polymarket BTC 五分钟 Up/Down 市场是否存在可执行的错误定价。Chainlink BTC/USD 60 秒 TWAP 是唯一标签与结算来源；Binance 只提供特征。当前目标是先把数据覆盖、独立判断和可解释界面做成可靠研究闭环，不以自动实盘为优先。

## 已有成果

- Python 研究核心：规则版本、Chainlink resolution 重建、概率/残差模型、Platt 校准、Edge、walk-forward、成交情景、研究/模拟账本、风控门禁和 SQLite 审计。
- 数据链：Polymarket Gamma/CLOB REST/CLOB WS、Binance 现货与永续、Chainlink RTDS；REST 快路径与慢速 discovery 已拆分。
- 只读研究前端：同步覆盖、BTC 判断、概率链、No Trade 原因和数据源健康度。
- Windows Supervisor 脚本：拆分启动、状态检查、失败重启；不会启动 paper 或 live 执行。
- 自动交易默认禁用，未发布模型时保持 `DISARMED / WAITING_FOR_MODEL`。

## 当前做到哪里

- 2026-09-10 路线图记录的运行快照显示当前/下一期 REST 订单簿 2/2，30 分钟窗口覆盖 100%，24 小时约 99.8%，CLOB WS、Chainlink RTDS、Binance WS 当时均为 LIVE。
- 最新候选基于 285 个独立 market 仍未通过全局校准门禁；局部改善没有被包装成可交易模型。
- 本次复验：Python 84 项测试全过；Web 构建与 2 项渲染测试全过。
- 本次运行态检查：历史 Supervisor 清单中的组件均已停止，API 8000 不可用；3000 仍由另一个前端进程响应。该状态只说明当前未运行，不推翻 9 月 10 日的历史运行证据。

## 当前卡点

1. Alpha challenger 尚未在 purged OOF 中同时通过 Brier、ECE 与置信边界门禁；这是主要业务阻塞。
2. 当前本机采集/研究/API 栈未运行，继续实时验证前需恢复 Supervisor，并确认 3000 端口的现存前端来源。
3. 前端原本是单独 Git 工作区且存在一批未提交的架构清理；本仓库已保留原提交并把当前工作态固化为新快照，后续统一从本仓库继续。

## 先看与怎么跑

- 产品与现状：[README.md](README.md)、[docs/new-goal-roadmap.md](docs/new-goal-roadmap.md)
- 核心代码：`src/pm_btc/`
- 数据/模型测试：`tests/`
- 前端：`web/`
- 本机启动：`scripts/setup-local.ps1`，然后 `scripts/start-local.ps1`

验证：

```powershell
python -m unittest discover -s tests -v
cd web
npm install
npm test
```

未知：没有证据证明当前模型已具备正的、可推广的实盘 Alpha；没有执行本次外部连通性复测；不应据此启用交易。

