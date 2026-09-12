from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from .domain import ChainlinkObservation, MarketRuleVersion, VerificationStatus
from .resolution import ResolutionStateEngine
from .config import Settings
from .polymarket_sync import create_synchronizer
from .polymarket_ws import PolymarketClobWebSocketRuntime
from .binance_sync import BinanceHttpClient, BinanceSynchronizer
from .binance_ws import BinanceWebSocketRuntime
from .chainlink_sync import ChainlinkDataStreamsClient, ChainlinkRawSynchronizer
from .chainlink_rtds import PolymarketChainlinkRtdsRuntime
from .trusted_dns import TrustedDnsResolver
from .research_runtime import RealtimeResearchRuntime
from .server import serve
from .training import fit_logistic_alpha
from .walkforward import walk_forward_probability_report
from .publication import publish_model
from .paper_runtime import PaperTradingRuntime
from .risk_runtime import RiskMonitorRuntime
from .model_runtime import AutoModelRuntime
from .storage import SQLiteStore
from .diagnostics import purged_oof_diagnostics
from .connectivity import connectivity_report
from .local_runtime import LocalSupervisor, local_status


def demo_resolution() -> dict:
    start = datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc)
    rule = MarketRuleVersion(
        market_id="demo",
        condition_id="demo-condition",
        resolution_source_url="https://data.chain.link/streams/btc-usd-twap-60s-streams",
        chainlink_stream_id="btc-usd-twap-60s",
        fee_rule_version="v1",
        fee_schedule={"rate": 0.07},
        market_schema_version="v1",
        tick_size=0.01,
        minimum_order_size=1.0,
        start_time=start,
        end_time=start + timedelta(minutes=5),
        token_ids={"UP": "up", "DOWN": "down"},
    )
    observations = [
        ChainlinkObservation(
            stream_id=rule.chainlink_stream_id,
            source_timestamp=start + timedelta(minutes=i),
            received_timestamp=start + timedelta(minutes=i, seconds=1),
            twap_60s=100_000 + 20 * i,
            report_id=str(i),
            verification_status=VerificationStatus.VERIFIED,
            raw_payload_hash=f"hash-{i}",
            market_id=rule.market_id,
        )
        for i in range(3)
    ]
    state = ResolutionStateEngine().calculate(
        rule,
        start_price=100_000,
        observations=observations,
        now=start + timedelta(minutes=3),
        proxy_price=100_080,
        expected_remaining_price_std=50,
    )
    return state.__dict__


def main() -> None:
    parser = argparse.ArgumentParser(description="PM-BTC mispricing detection core")
    parser.add_argument("command", choices=(
        "demo-resolution", "sync-once", "run-sync", "sync-features-once", "sync-chainlink-once",
        "sync-clob-ws-once", "sync-binance-ws-once",
        "run-polymarket-books", "run-polymarket-discovery",
        "run-binance-http", "run-binance-ws", "run-chainlink-rtds",
        "run-polymarket-clob-ws", "run-research", "run-paper",
        "run-auto-model", "run-risk-monitor",
        "evaluate-once", "train-logistic", "probability-report", "publish-model",
        "diagnostic-report", "connectivity-check", "auto-model-once", "run-data", "serve-api", "status",
        "run-local", "local-status"
    ))
    parser.add_argument("--database", default=Settings().database_path)
    parser.add_argument("--interval", type=float, default=Settings().sync_interval_seconds)
    parser.add_argument("--feed-id")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--output", default="artifacts/logistic-alpha-v1.json")
    parser.add_argument("--minimum-markets", type=int, default=30)
    parser.add_argument("--train-markets", type=int, default=300)
    parser.add_argument("--calibration-markets", type=int, default=100)
    parser.add_argument("--validation-markets", type=int, default=100)
    args = parser.parse_args()
    if args.command == "demo-resolution":
        print(json.dumps(demo_resolution(), default=str, indent=2))
    elif args.command == "run-local":
        try:
            LocalSupervisor(Path.cwd(), args.database).run_forever()
        except KeyboardInterrupt:
            pass
        except RuntimeError as error:
            raise SystemExit(f"local runtime unavailable: {error}") from error
    elif args.command == "local-status":
        print(json.dumps(local_status(Path.cwd()), default=str, indent=2))
    elif args.command == "status":
        store = SQLiteStore(args.database)
        try:
            print(json.dumps(store.sync_status(), default=str, indent=2))
        finally:
            store.close()
    elif args.command in ("sync-once", "run-sync", "run-polymarket-books", "run-polymarket-discovery"):
        settings = replace(Settings(), database_path=args.database, sync_interval_seconds=args.interval)
        synchronizer, store = create_synchronizer(settings)
        try:
            if args.command == "sync-once":
                print(json.dumps(asyncio.run(synchronizer.sync_once()), indent=2))
            elif args.command == "run-sync":
                asyncio.run(synchronizer.run_forever())
            elif args.command == "run-polymarket-books":
                asyncio.run(synchronizer.run_books_forever())
            else:
                asyncio.run(synchronizer.run_discovery_forever())
        except KeyboardInterrupt:
            pass
        finally:
            store.close()
    elif args.command == "sync-chainlink-once":
        if not args.feed_id:
            parser.error("sync-chainlink-once requires --feed-id")
        settings = replace(Settings.from_env(), database_path=args.database)
        store = SQLiteStore(args.database)
        try:
            result = ChainlinkRawSynchronizer(ChainlinkDataStreamsClient(settings), store).sync_once(args.feed_id)
            print(json.dumps(result, indent=2))
        finally:
            store.close()
    elif args.command == "sync-clob-ws-once":
        settings = replace(Settings.from_env(), database_path=args.database)
        store = SQLiteStore(args.database)
        try:
            result = asyncio.run(PolymarketClobWebSocketRuntime(settings, store).collect_for(args.duration))
            print(json.dumps(result, indent=2))
        finally:
            store.close()
    elif args.command == "sync-binance-ws-once":
        settings = replace(Settings.from_env(), database_path=args.database)
        store = SQLiteStore(args.database)
        try:
            result = asyncio.run(BinanceWebSocketRuntime(settings, store).collect_for(args.duration))
            print(json.dumps(result, indent=2))
        finally:
            store.close()
    elif args.command in (
        "run-binance-http", "run-binance-ws", "run-chainlink-rtds",
        "run-polymarket-clob-ws", "run-research", "run-paper",
        "run-auto-model", "run-risk-monitor",
    ):
        settings = replace(
            Settings.from_env(), database_path=args.database,
            sync_interval_seconds=args.interval,
        )
        store = SQLiteStore(args.database)
        trusted_dns = (
            TrustedDnsResolver(settings.trusted_dns_over_https_url)
            if settings.websocket_trusted_dns_enabled else None
        )
        runtime_factories = {
            "run-binance-http": lambda: BinanceSynchronizer(
                settings, BinanceHttpClient(settings), store,
            ),
            "run-binance-ws": lambda: BinanceWebSocketRuntime(settings, store),
            "run-chainlink-rtds": lambda: PolymarketChainlinkRtdsRuntime(
                store, resolver=trusted_dns, websocket_url=settings.polymarket_rtds_ws_url,
            ),
            "run-polymarket-clob-ws": lambda: PolymarketClobWebSocketRuntime(
                settings, store, resolver=trusted_dns,
            ),
            "run-research": lambda: RealtimeResearchRuntime(settings, store),
            "run-paper": lambda: PaperTradingRuntime(settings, store),
            "run-auto-model": lambda: AutoModelRuntime(settings, store),
            "run-risk-monitor": lambda: RiskMonitorRuntime(settings, store),
        }
        try:
            asyncio.run(runtime_factories[args.command]().run_forever())
        except KeyboardInterrupt:
            pass
        finally:
            store.close()
    elif args.command == "evaluate-once":
        store = SQLiteStore(args.database)
        try:
            print(json.dumps(RealtimeResearchRuntime(Settings.from_env(), store).evaluate_once(), indent=2))
        finally:
            store.close()
    elif args.command == "serve-api":
        serve(replace(Settings.from_env(), database_path=args.database), args.host, args.port)
    elif args.command == "train-logistic":
        store = SQLiteStore(args.database)
        try:
            rows = store.alpha_training_rows()
        finally:
            store.close()
        independent = len({row["market_id"] for row in rows})
        if independent < args.minimum_markets:
            raise SystemExit(
                f"refusing to publish: {independent} independent Chainlink-labeled markets; "
                f"minimum is {args.minimum_markets}"
            )
        artifact = fit_logistic_alpha(rows)
        artifact.save(args.output)
        print(json.dumps({
            "status": "TRAINED", "output": args.output,
            "independent_markets": artifact.independent_markets,
            "training_points": artifact.training_points,
            "artifact_hash": artifact.artifact_hash,
        }, indent=2))
    elif args.command == "probability-report":
        store = SQLiteStore(args.database)
        try:
            rows = store.alpha_training_rows()
        finally:
            store.close()
        try:
            report = walk_forward_probability_report(
                rows, train_count=args.train_markets,
                calibration_count=args.calibration_markets,
                validation_count=args.validation_markets,
            )
        except ValueError as error:
            raise SystemExit(f"report unavailable: {error}") from error
        print(json.dumps(report.to_dict(), indent=2))
    elif args.command == "diagnostic-report":
        store = SQLiteStore(args.database)
        try:
            rows = store.alpha_training_rows()
        finally:
            store.close()
        try:
            report = purged_oof_diagnostics(
                rows, train_count=args.train_markets,
                calibration_count=args.calibration_markets,
                validation_count=args.validation_markets,
            )
        except ValueError as error:
            raise SystemExit(f"diagnostic unavailable: {error}") from error
        print(json.dumps(report, indent=2))
    elif args.command == "connectivity-check":
        settings = replace(Settings.from_env(), database_path=args.database)
        print(json.dumps(asyncio.run(connectivity_report(settings, args.timeout)), indent=2))
    elif args.command == "publish-model":
        store = SQLiteStore(args.database)
        try:
            rows = store.alpha_training_rows()
        finally:
            store.close()
        try:
            artifact = publish_model(
                rows, train_count=args.train_markets,
                calibration_count=args.calibration_markets,
                validation_count=args.validation_markets,
                minimum_markets=args.minimum_markets,
            )
        except ValueError as error:
            raise SystemExit(f"refusing to publish: {error}") from error
        artifact.save(args.output)
        print(json.dumps({
            "status": "PUBLISHED", "output": args.output,
            "artifact_hash": artifact.artifact_hash,
            "independent_markets": artifact.independent_markets,
            "probability_edge": artifact.validation["selected_probability_edge"],
            "alpha_kind": artifact.alpha_kind,
            "calibration_method": artifact.calibration_method,
        }, indent=2))
    elif args.command == "auto-model-once":
        settings = replace(Settings.from_env(), database_path=args.database)
        store = SQLiteStore(args.database)
        try:
            print(json.dumps(AutoModelRuntime(settings, store).evaluate_once(), indent=2))
        finally:
            store.close()
    else:
        settings = replace(Settings.from_env(), database_path=args.database, sync_interval_seconds=args.interval)
        synchronizer, store = create_synchronizer(settings)
        binance = BinanceSynchronizer(settings, BinanceHttpClient(settings), store)
        research = RealtimeResearchRuntime(settings, store)
        paper = PaperTradingRuntime(settings, store)
        risk_monitor = RiskMonitorRuntime(settings, store)
        trusted_dns = (
            TrustedDnsResolver(settings.trusted_dns_over_https_url)
            if settings.websocket_trusted_dns_enabled else None
        )
        chainlink_rtds = PolymarketChainlinkRtdsRuntime(
            store, resolver=trusted_dns, websocket_url=settings.polymarket_rtds_ws_url
        )
        polymarket_clob_ws = PolymarketClobWebSocketRuntime(settings, store, resolver=trusted_dns)
        binance_ws = BinanceWebSocketRuntime(settings, store)
        auto_model = AutoModelRuntime(settings, store)
        try:
            if args.command == "sync-features-once":
                print(json.dumps(asyncio.run(binance.sync_once()), indent=2))
            else:
                async def run_all() -> None:
                    await asyncio.gather(
                        synchronizer.run_forever(), binance.run_forever(),
                        binance_ws.run_forever(), chainlink_rtds.run_forever(),
                        polymarket_clob_ws.run_forever(), research.run_forever(),
                        paper.run_forever(), auto_model.run_forever(), risk_monitor.run_forever(),
                    )
                asyncio.run(run_all())
        except KeyboardInterrupt:
            pass
        finally:
            store.close()


if __name__ == "__main__":
    main()
