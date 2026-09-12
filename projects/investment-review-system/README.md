# 投资决策复盘系统 V1

本机单用户、离线优先的投资判断记录与复盘工具。它不预测市场，也不进行自动交易。

## Windows 启动

双击 `start.bat`。首次启动会安装依赖，然后浏览器自动打开 <http://localhost:3000>。

也可以在 PowerShell 中运行：

```powershell
npm install
npm run dev
```

## 数据位置与备份

所有业务数据存储在 `data/investment-review.db`。关闭应用后，可以直接复制该文件备份；也可以在数据看板下载 JSON 或 CSV。

## V1 功能

- 1–3 分钟创建判断，原始判断与证据保存后不可覆盖。
- 追加备注，保留判断形成后的信息变化。
- 按到期日自动区分验证中、待复盘和已复盘。
- 完成结果、归因和学习复盘，自动计算超额收益。
- 基础数据看板与信心度区间正确率。
- 搜索、状态筛选、JSON/CSV 导出。

## 常用命令

- `npm run dev`：开发模式。
- `npm run build`：生产构建校验。
- `npm test`：运行核心日期与状态规则测试。

需要 Node.js 20.9 或更高版本；当前数据库实现使用 Node.js 22.5+ 内置 SQLite，推荐 Node.js 24。
