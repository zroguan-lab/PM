# PM-BTC 5m Mispricing Detection System

Research-first core for detecting executable mispricing in Polymarket BTC five-minute Up/Down markets.

The implementation treats Chainlink BTC/USD 60-second TWAP as the only label and resolution source. Binance is feature-only. Live trading is disabled by default behind the `PolymarketBroker` adapter and eligibility gate.

Current product goal: build a local research workbench that can maximize Polymarket BTC 5m data coverage, produce its own BTC market judgment, and show the evidence in a dashboard before any live-trading work. See [docs/new-goal-roadmap.md](docs/new-goal-roadmap.md).

## Implemented

- Immutable market-rule versions and Chainlink observation model
- Chainlink resolution-state reconstruction and required remaining TWAP
- Market probability plus residual Alpha ensemble
- Platt calibration and market-cluster uncertainty bounds
- Raw, executable, net, risk-adjusted and conservative edge calculations
- No-trade filter and dynamic maker/taker EV policy
- Purged/embargo walk-forward splits
- Optimistic, estimated and conservative maker fills
- Market-cluster metrics and bootstrap confidence intervals
- Research, realistic paper and capacity ledgers
- Broker abstraction with safe read-only official adapter
- Research/live gates and statistical kill switch
- SQLite rule, observation and audit storage
- Lightweight local status API with no web-framework dependency
- Read-only Polymarket Gamma market discovery and CLOB order-book synchronization
- Binance spot/perpetual quote, depth, basis, open-interest and funding feature snapshots
- Official Binance WebSocket endpoint failover for spot market-data streams
- Binance USDⓈ-M routed WebSocket streams (`/public` books and `/market` trades/mark price)
- Persisted Resolution State snapshots with completeness and gap status
- Bounded current/next-market REST recovery polling alongside exact WebSocket archives

## Run

Use Python 3.11 or newer:

For the Windows local research workbench, use the project-owned runtime and supervisor. The supervisor starts each collector, research/model loop, API, and dashboard in a separate process and restarts a failed component. It never starts paper or live order execution:

```powershell
.\scripts\setup-local.ps1 -WithMl
.\scripts\start-local.ps1
.\scripts\status-local.ps1
# When you intentionally want to stop the whole local stack:
.\scripts\stop-local.ps1
```

The dashboard is then available at `http://localhost:3000/`. Runtime state is written to `run/local-runtime.json`; component output remains under `logs/`. Do not point the launcher at a Codex-bundled Python path because that environment may be replaced independently of this project.

Individual development commands remain available:

```powershell
python -m pip install -e .
pm-btc demo-resolution
pm-btc sync-once --database data/pm_btc.sqlite3
pm-btc sync-features-once --database data/pm_btc.sqlite3
pm-btc sync-chainlink-once --database data/pm_btc.sqlite3 --feed-id 0x...
pm-btc evaluate-once --database data/pm_btc.sqlite3
pm-btc serve-api --database data/pm_btc.sqlite3 --port 8000
pm-btc train-logistic --database data/pm_btc.sqlite3 --minimum-markets 30
pm-btc probability-report --database data/pm_btc.sqlite3 --train-markets 300 --calibration-markets 100 --validation-markets 100
pm-btc publish-model --database data/pm_btc.sqlite3 --minimum-markets 500 --output artifacts/published-model.json
pm-btc status --database data/pm_btc.sqlite3
pm-btc connectivity-check --database data/pm_btc.sqlite3 --timeout 10
pm-btc run-polymarket-books --database data/pm_btc.sqlite3 --interval 2
pm-btc run-polymarket-discovery --database data/pm_btc.sqlite3
pm-btc run-binance-http --database data/pm_btc.sqlite3
pm-btc run-binance-ws --database data/pm_btc.sqlite3
pm-btc run-chainlink-rtds --database data/pm_btc.sqlite3
pm-btc run-polymarket-clob-ws --database data/pm_btc.sqlite3
pm-btc run-research --database data/pm_btc.sqlite3
pm-btc run-sync --database data/pm_btc.sqlite3 --interval 2
pm-btc run-data --database data/pm_btc.sqlite3 --interval 2
python -m unittest discover -s tests -v
```

Optional packages:

```powershell
python -m pip install -e ".[ml,live,dev]"
```

The production Chainlink client must verify reports before creating `ChainlinkObservation` records. The collector interfaces intentionally contain no unauthenticated or scraped substitute, because Binance data must never become a settlement label.

`run-polymarket-books` is the recommended P0 fast path for local validation: it reads already-discovered current/next BTC 5-minute markets from SQLite and snapshots both outcome order books from CLOB every interval. It deliberately does not trigger slow Gamma discovery when the local market cache is empty, so a slow market metadata request cannot block the executable order-book feed.

`run-polymarket-discovery` is the slow path: it discovers nearby BTC 5-minute markets from Gamma, versions market rules, refreshes fee metadata, and records each synchronization run in SQLite. Run it separately from `run-polymarket-books` when validating data coverage.

The remaining `run-*` commands split Binance HTTP, Binance WebSocket, Chainlink RTDS, Polymarket CLOB WebSocket, research, paper, automatic model evaluation, and risk monitoring into independent process boundaries. A slow or disconnected WebSocket therefore cannot stop the REST order-book fast path or hide which feed is actually blocked.

`run-chainlink-rtds` uses the official unified Python SDK as its primary connection. The manual trusted-DNS and direct sockets are failover routes only; this preserves the SDK's working proxy and TLS behavior while keeping a recovery path available.

`run-sync` is the older combined Polymarket collector: it discovers nearby BTC 5-minute markets from Gamma, snapshots both outcome order books from CLOB, versions the market rules, and records each synchronization run in SQLite. It does not sign orders or trade. Automatic prediction remains disabled until verified Chainlink TWAP ingestion and model artifacts are available.

`run-data` runs the Polymarket collector, Binance feature-only collectors, research loop, paper loop, model publisher, and risk monitor together. It is useful as an integration mode, but P0 data-sync debugging should prefer the split Polymarket commands above so REST order-book freshness is not confused with WebSocket, Binance, Chainlink, or research-loop failures. Binance snapshots are stored separately and are structurally prevented from creating Chainlink labels.

The same command also runs the real-time research loop. It records an executable-book-derived market baseline every interval. Until verified Chainlink observations and a published out-of-fold calibrated Alpha model exist, every row is intentionally persisted as `NO_TRADE` with explicit rejection reasons.

`connectivity-check` probes Polymarket Gamma, Polymarket CLOB, Polymarket CLOB WebSocket, Polymarket Chainlink RTDS, and Binance HTTP/WebSocket endpoints. It is read-only and writes no market data; use it when `status` or the dashboard reports stale feeds.

For the local dashboard, start the API on port 8000 and the `web` project with vinext. The dashboard polls `http://127.0.0.1:8000/api/status` every five seconds and is available at `http://localhost:3000/` in the current workspace.

Chainlink Data Streams requires account credentials. Set `CHAINLINK_API_KEY` and `CHAINLINK_API_SECRET` before using `sync-chainlink-once`. The command archives the signed `fullReport` as `UNVERIFIED`; it deliberately does not create a TWAP observation or label until a schema-specific decoder and cryptographic verifier accepts the report.
