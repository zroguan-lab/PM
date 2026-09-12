import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: handler } = await import(workerUrl.href);

  return handler(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
  );
}

test("server-renders the PM-BTC research dashboard shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<html lang="zh-CN">/i);
  assert.match(html, /<title>PM·BTC Mispricing Lab<\/title>/i);
  assert.match(html, /BTC 5M MISPRICING DETECTION/);
  assert.match(html, /CURRENT POLYMARKET/);
  assert.match(html, /UP 可成交价格/);
  assert.match(html, /BTC INDEPENDENT VIEW/);
  assert.match(html, /Probability Edge/);
  assert.match(html, /Chainlink 60s TWAP/);
  assert.match(html, /Binance WS/);
  assert.match(html, /CLOB WS/);
  assert.match(html, /同步就绪链/);
  assert.match(html, /DISARMED/);
  assert.doesNotMatch(html, /胜率/);
});

test("dashboard source keeps live health and conservative-decision evidence", async () => {
  const [page, layout, css] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
  ]);

  assert.match(page, /^"use client";/);
  assert.match(page, /http:\/\/127\.0\.0\.1:8000\/api\/status/);
  assert.match(page, /setTimeout\(refresh,5000\)/);
  assert.match(page, /data_readiness/);
  assert.match(page, /current_prediction/);
  assert.match(page, /prediction_health/);
  assert.match(page, /btc_judgment/);
  assert.match(page, /btc_trend_judgment/);
  assert.match(page, /BTC INDEPENDENT VIEW/);
  assert.match(page, /未校准研究信号/);
  assert.match(page, /Chainlink 结算状态/);
  assert.match(page, /live_markets/);
  assert.match(page, /polymarket_book_fetch_coverage_30m/);
  assert.match(page, /24h盘口获取率/);
  assert.match(page, /审计期盘口获取率/);
  assert.match(page, /当前未恢复盘口缺口/);
  assert.match(page, /已自动恢复缺口/);
  assert.match(page, /候选已有正Brier改善/);
  assert.match(page, /Market Model Pm/);
  assert.match(page, /Market Model Brier/);
  assert.match(page, /ReadinessChain/);
  assert.match(page, /binance_ws_events/);
  assert.match(page, /binance_ws_trades/);
  assert.match(page, /binance_ws_book_snapshots/);
  assert.match(page, /Conservative Edge/);
  assert.match(page, /No-Trade|NO TRADE|NO_TRADE/);
  assert.doesNotMatch(page, /胜率/);
  assert.match(layout, /title:\s*"PM·BTC Mispricing Lab"/);
  assert.match(layout, /Polymarket BTC 5m mispricing research and execution dashboard/);
  assert.match(css, /\.app-shell\s*\{/);
  assert.match(css, /@media\s*\(max-width:/);
});
