# 协作约定

## 修改位置

- PM-BTC、W40 / OS、投资决策复盘系统：直接在本仓库对应 `projects/` 文件夹修改。
- Binance Futures Lab：在独立仓库 `zroguan-lab/AI-Trading8.22` 修改；本仓库只更新子模块指针和项目索引。
- PM-BTC 前端原有本地 Git 历史已作为 `projects/quant-workbench/web` 子树保留；后续统一从本仓库继续。

## 建议流程

1. 从 `main` 创建 `feature/<topic>` 或 `consulting/<topic>` 分支。
2. 一个 PR 只解决一个清晰问题，说明事实依据、影响范围和验证结果。
3. 涉及交易、权限、外部 API 或真实资金时，默认失败关闭；不得用 UI 状态代替后端门禁。
4. PR 合并前运行对应项目 `PROJECT_STATUS.md` 中的验证命令。

## 禁止提交

- `.env`、API key、token、钱包、私钥、账户标识或浏览器会话。
- SQLite 数据库、个人投资记录、交易/行情原始数据、日志、运行态和模型产物。
- `node_modules`、`.venv`、`.next`、`dist` 等可重建目录。

若新增样例配置，只提交 `.env.example`，并使用明显的占位值。

