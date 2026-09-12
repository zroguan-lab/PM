# PM-BTC 新目标路线图

## 2026-09-10 已验证运行快照

- 项目独立 `.venv` 和 `scripts/start-local.ps1` 已可由 Supervisor 启动并自动恢复只读研究组件。
- Polymarket 当前/下一期 REST 订单簿已观测到 2/2（100%）；过去30分钟的轮询成功率、预期书获取率和完整market率均已持久化并在 UI 展示。CLOB WS、Chainlink RTDS 和 Binance WS 已同时验证为 LIVE。
- 页面已将 Chainlink Resolution State 生成的 BTC 方向倾向与交易授权分离：方向可为 READY，交易仍可为 `NO_TRADE`。
- Alpha challenger 尚未通过发布门禁，因此系统保持 `DISARMED / WAITING_FOR_MODEL`；这是真实研究状态，不是 UI 或启动故障。
- 实时特征 schema 已超过 30 个独立已结算 market；最新 challenger 虽出现微弱正 Probability Edge，但未通过 calibration 门禁。自动评估现已覆盖全局和四个剩余时间桶，并对每个 market 的拟合点数进行确定性上限控制。

当前目标不再优先追求自动实盘交易，而是先完成一个可验证的 BTC 5 分钟研究工作台：

1. 数据能尽可能完整同步 Polymarket。
2. 系统能输出自己的 BTC 走势/错误定价判断。
3. 前端能清楚展示数据、判断、阻塞原因和进度。

## 目标 1：Polymarket 数据同步

### 真实含义

“100% 同步”不能定义成公网永远不断线。更可执行的定义是：

- 所有可发现的 BTC 5m Polymarket market 都能落库。
- 每个 market 保存规则版本、token ids、start/end time、tick size、minimum order size、fee schedule。
- 活跃 market 的 UP/DOWN REST orderbook 持续刷新。
- CLOB WebSocket 可用时归档 tick/orderflow；不可用时系统明确标红，但不阻塞 REST 盘口继续采集。
- 同步缺口、延迟、失败原因都必须落库和出现在 API/UI。

### 当前状态

- Gamma market discovery 可用。
- CLOB REST orderbook 可用；已新增独立 `run-polymarket-books` 快路径，避免被慢 discovery、WS 或研究循环拖住。
- CLOB WebSocket 已通过 ambient proxy / trusted DNS / direct 路由状态机恢复，实时事件持续归档。
- REST book 已实现每个 token 独立重试和 `PARTIAL` 落库，不再因一个请求超时丢掉整轮成功结果。
- 同步审计已拆成最近30分钟、最近24小时和审计表启用以来三层口径；历史失败不会被短窗口覆盖。
- 新增token级盘口缺口账本：连续重试仍失败时创建未恢复缺口，后续同token成功快照自动标记恢复；“原始轮询获取率”和“当前是否已追平”不再共用一个指标。
- 已拆分 REST orderbook 与 CLOB WS 健康度。
- `run-data` 仍可作为集成模式，但当前调试和 P0 验收优先使用独立进程边界：
  - `run-polymarket-books`：只同步当前/下一期 BTC 5m REST orderbook。
  - `run-polymarket-discovery`：慢速刷新 Gamma market 和规则版本。

### 当前验收

- 上述项已通过运行时 API 和前端数据质量页验证。
- 2026-09-10 运行快照：最近30分钟盘口获取率和完整market率均为100%；最近24小时/审计期盘口获取率为99.83%，完整market率为99.82%。差额来自审计启用早期的瞬时漏取，已保留而不是隐藏。
- token级缺口账本上线后的运行验证：当前/下一期未恢复缺口为0，当前状态已追平；账本上线前的25个历史瞬时快照仍计入原始获取率，不能事后伪造恢复。
- “100%”仅表示选定窗口内所有预期 UP/DOWN book 都有可审计结果，不表示公网永不中断。最终目标是实时采集加缺口补采后达到100%可解释覆盖；在补采闭环完成前不得宣称累计100%。

## 目标 2：自己的 BTC 判断

### 真实含义

系统不应该只输出“涨/跌”，而要输出：

- Polymarket 当前盘口概率 `Pm`。
- 系统自己的概率判断 `P_model`。
- 二者差异 `edge`。
- 当前 No Trade / Trade 判断原因。
- Chainlink 结算状态不足时，判断必须降级为研究观察，不能变成交易信号。

### 当前状态

- Market baseline 已经能从 UP/DOWN orderbook 推导市场概率。
- Research prediction loop 已经在写 `research_predictions`。
- 当前模型未发布，因为历史样本的 Brier/Calibration 门禁没有通过。
- Chainlink 实时源已恢复，标签与 resolution reconciliation 持续生成，当前不一致数为0。
- “BTC短线走势”和“Polymarket结算倾向”已拆成两条独立研究输出：前者由Binance现货/永续60秒成交不平衡与盘口压力组成透明的未校准趋势分数，后者继续由Chainlink Resolution State决定。两者均不能单独授权交易。
- 当前真正阻塞是模型校准：Probability Edge 候选尚未在 purged OOF 中同时通过 ECE 和置信边界。
- Platt 正则强度现只在 calibration 内部的时间后段选择；若不能同时改善 Brier 和 ECE 则回退 identity，外层 purged validation 不参与调参。
- Market Model 已从原始 microprice 中独立：Logistic 基线只使用盘口、剩余时间和流动性特征，`market_weight` 只在独立 market 的单侧90% Brier 改善下界大于0时才允许偏离原始盘口；Alpha 再学习该基线之外的残差。
- Resolution Pressure 的独立概率映射已实证弱于 Polymarket，因此仅保留为方向/结算状态特征，不冒充最终交易概率。
- 自动模型门禁已去除拒绝后重复执行的 Logistic/LightGBM OOF 比较；Market Logistic、Alpha Logistic 与 Platt 梯度计算已改为等价 NumPy 向量运算。实际全量样本单次 Logistic fit 从逐行长循环降至约1.5–1.9秒，后续重训仍保留相同 market-balanced 权重和发布门禁。
- 285个独立market的最新候选仍被拒绝：全局 Logistic raw edge 为负，LightGBM 的局部正改善未同时通过校准门禁；系统继续 `DISARMED`，不把局部结果包装成可交易模型。

### 下一步验收

- 即使没有已发布 Alpha 模型，也能在前端展示 market baseline 判断。
- 输出BTC短线趋势、Chainlink结算倾向、盘口概率、深度、spread、时间窗口。
- 明确标识：这是研究判断，不是交易信号。
- Chainlink 标签补齐后，再训练 Alpha 模型并比较 `Brier(Model) < Brier(Polymarket)`。

## 目标 3：可视化界面

### 真实含义

前端首页先服务研究，不服务营销：

- 第一屏看到系统是否能用。
- 看到当前 BTC 5m market。
- 看到 Polymarket 数据同步情况。
- 看到系统自己的判断和为什么不交易。
- 看到 Chainlink / Polymarket / Binance 哪条链路卡住。

### 当前状态

- 本地前端已可访问 `http://localhost:3000/`。
- API 已可访问 `http://127.0.0.1:8000/api/status`。
- 页面已有同步链、概率链、No Trade 原因和研究进度。
- 需要进一步降低“实盘交易系统”的视觉比重，提高“数据同步与研究判断”的比重。

### 下一步验收

- 首页三块核心卡片：
  - 数据同步覆盖率。
  - 当前 BTC 判断。
  - 阻塞原因。
- 数据源拆分显示：
  - Polymarket Market Discovery
  - Polymarket REST Book
  - Polymarket CLOB WS
  - Chainlink TWAP
  - Binance Features
- 不把 CLOB WS 失败误报成 REST 盘口失败。

## 当前优先级

P0：数据同步稳定化

- 不再把 monolithic `run-data` 作为 P0 唯一运行方式。
- REST orderbook 快路径、market discovery 慢路径、WS 归档路径分离运行。
- `/api/status` 增加同步覆盖率与延迟统计。
- 增加同步缺口报告。

P1：BTC 判断最小闭环

- 将 market baseline 判断提升为一等输出。
- 明确 research-only 状态。
- 在 Chainlink 缺失时只输出观察，不输出交易信号。

P2：前端研究界面

- 首页重排为数据、判断、阻塞三栏。
- 首页已展示当前 market、盘口新鲜度、BTC Directional View 和 No Trade 原因。
- 数据质量页已展示当前未恢复缺口、已自动恢复缺口，以及30分钟、24小时和审计期的轮询成功率/盘口获取率、完整market率与归档证据。

P3：模型与回测

- Chainlink 标签补齐。
- 训练 Logistic / LightGBM alpha。
- Walk-forward、calibration、Brier 对比。

P4：模拟盘与实盘

- 只有数据、模型、模拟盘全部通过后才考虑。
- 默认继续 `DISARMED`。

## 不做的事

- 不用 Binance 替代 Chainlink 标签。
- 不在 Chainlink 缺失时假装模型有效。
- 不为了 UI 好看隐藏同步阻塞。
- 不在未通过 eligibility 和模型门禁前接入实盘。
