# 投资决策复盘系统：项目现状

状态日期：2026-09-12。

## 在做什么

本机单用户、离线优先的投资判断记录与复盘工具。目标是在 1–3 分钟内记录判断，保留当时的原始判断和证据，在到期后做结果、归因和学习复盘；不预测市场，不自动交易。

## 已有成果

- Next.js 15.5.2、React 19、TypeScript、Node 内置 SQLite。
- 新建判断、判断详情、待复盘列表、完成复盘等页面与 Server Actions。
- 原始判断/证据不可覆盖，后续变化以追加信息表达。
- 到期日与状态规则、超额收益计算、基础统计和 JSON/CSV 导出。
- SQLite V1 schema、产品规格和 Windows 一键启动脚本。

## 当前做到哪里

V1 的核心本地路径已经形成，3 项日期/状态规则测试本次全部通过。业务数据原本位于 `data/investment-review.db`；为保护个人记录，本仓库只共享代码和 schema，不共享数据库及 WAL/SHM 文件。

## 当前卡点

1. 自动化测试目前只覆盖日期/状态核心规则，数据库迁移、不可变约束、导出和完整页面路径仍缺回归证据。
2. 当前依赖 `next@15.5.2` 在安装时被 npm 明确标记为存在已知安全漏洞；任何联网或多人部署前应先升级并回归。
3. 默认 Next 配置在存在上级 lockfile 的机器上可能误判 tracing root。本次在隔离验证副本中显式限定 root 后生产构建通过；项目源码尚未固化该配置。
4. 目前是单机 V1，没有多用户、权限、云同步、备份恢复演练或生产部署证据。

## 先看与怎么跑

- [README.md](README.md)
- [docs/v1-product-spec.md](docs/v1-product-spec.md)
- [docs/v1-schema.sql](docs/v1-schema.sql)
- 核心数据路径：`lib/db.ts`、`lib/actions.ts`
- 页面：`app/`

```powershell
npm install
npm test
npm run build
npm run dev
```

未知：没有证据表明该工具已经完成真实长期使用验证；个人数据库中的实际记录没有被读取或共享。
