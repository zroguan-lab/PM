# 验证记录

记录日期：2026-09-12（Asia/Shanghai）。这里只记录本次实际执行结果。

| 项目 | 命令/检查 | 结果 |
|---|---|---|
| PM-BTC Python | `.venv\\Scripts\\python.exe -m unittest discover -s tests -v` | 84/84 通过，10.351s |
| PM-BTC Web | `npm test`（包含 vinext build） | 构建通过，2/2 渲染测试通过 |
| W40 / OS | `npm run lint` | 通过 |
| W40 / OS | `npm run build` | 干净隔离副本构建通过；`/`、`/today`、`/invest`、`/research`、`/create` 均成功静态生成。原目录先前失败来自运行中 `.next/trace-build` 文件锁 |
| 投资决策复盘系统 | `npm test` | 3/3 通过 |
| 投资决策复盘系统 | `npm run build` | 在隔离副本中限定 `outputFileTracingRoot` 后构建通过；5 个页面路由和导出 API 完成编译。该限定仅用于验证，没有写入项目源码 |
| PM-BTC 运行态 | `scripts/status-local.ps1` | Supervisor 清单中的采集、研究、API、Web 组件均未运行，状态 `DEGRADED`；API 8000 不可用；另有前端进程使 3000 返回 HTTP 200 |
| GitHub / Binance Futures Lab | 仓库提交、Issue、PR 查询 | `main` 最新为已合并 PR #15；PR #16、#17、#19 为 open |

说明：本次没有为了“变绿”而启动数据采集、交易或真实外部 API，也没有停止原项目进程。

补充风险：投资复盘安装时 npm 明确警告 `next@15.5.2` 存在已知安全漏洞；应在任何联网或多人部署前升级到已修复版本并重新回归。其默认 Next 配置在机器上存在上级 lockfile 时也可能误判 tracing root，本次通过验证副本中的显式 root 证明源码可构建。
