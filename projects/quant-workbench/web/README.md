# PM-BTC Research Dashboard

本机只读研究界面，用于查看 PM-BTC 5m Mispricing Detection System 的实时状态、概率链、Edge、数据质量与上线门禁。

## 本地运行

要求 Node.js `>=22.13.0`，并先在项目根目录启动状态 API：

```powershell
pm-btc serve-api --database data/pm_btc.sqlite3 --port 8000
```

再启动前端：

```powershell
npm install
npm run dev
```

页面位于 `http://localhost:3000/`，默认每五秒读取 `http://127.0.0.1:8000/api/status`。

## 验证命令

```powershell
npm run build
npm test
npm run lint
```

当前前端只负责展示研究状态，不包含钱包、下单、身份认证、云数据库或云端部署逻辑。交易与风控的事实来源仍在 Python 核心和 SQLite 中，前端不得自行推导交易状态。
