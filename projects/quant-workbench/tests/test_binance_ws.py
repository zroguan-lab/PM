import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pm_btc.binance_ws import BinanceWebSocketRuntime
from pm_btc.config import Settings
from pm_btc.research_runtime import RealtimeResearchRuntime
from pm_btc.storage import SQLiteStore


class BinanceWebSocketTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = SQLiteStore(str(Path(self.temporary.name) / "binance-ws.sqlite3"))
        self.runtime = BinanceWebSocketRuntime(
            Settings(binance_ws_book_snapshot_interval_seconds=0), self.store
        )
        self.timestamp_ms = int(datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc).timestamp() * 1000)

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def test_uses_official_routed_combined_streams(self):
        urls = self.runtime.stream_urls()
        candidates = self.runtime.stream_url_candidates()
        self.assertIn("stream.binance.com:9443/stream?streams=", urls["spot"])
        self.assertTrue(any("stream.binance.com:443/stream?streams=" in url for url in candidates["spot"]))
        self.assertTrue(any("data-stream.binance.vision/stream?streams=" in url for url in candidates["spot"]))
        self.assertIn("btcusdt@aggTrade", urls["spot"])
        self.assertIn("fstream.binance.com/public/stream?streams=", urls["futures_public"])
        self.assertIn("btcusdt@bookTicker", urls["futures_public"])
        self.assertIn("fstream.binance.com/market/stream?streams=", urls["futures_market"])
        self.assertIn("btcusdt@markPrice@1s", urls["futures_market"])

    def test_connection_preserves_ambient_proxy(self):
        captured = {}

        class EmptyWebSocket:
            async def __aenter__(self): return self
            async def __aexit__(self, *_): return None
            def __aiter__(self): return self
            async def __anext__(self): raise StopAsyncIteration

        def connector(url, **kwargs):
            captured.update({"url": url, **kwargs})
            return EmptyWebSocket()

        runtime = BinanceWebSocketRuntime(self.runtime.settings, self.store, connector=connector)
        with self.assertRaises(ConnectionError):
            asyncio.run(runtime._run_connection("spot", "wss://example.test/stream"))

        self.assertTrue(captured["proxy"])

    def test_trades_are_deduplicated_aggregated_and_raw_batch_is_replayable(self):
        buy = {"stream": "btcusdt@aggTrade", "data": {
            "e": "aggTrade", "E": self.timestamp_ms, "p": "100", "q": "2", "m": False,
        }}
        sell = {"stream": "btcusdt@aggTrade", "data": {
            "e": "aggTrade", "E": self.timestamp_ms + 100, "p": "101", "q": "3", "m": True,
        }}
        self.assertEqual(self.runtime.ingest_message("spot", json.dumps(buy))["trades_aggregated"], 1)
        self.assertEqual(self.runtime.ingest_message("spot", json.dumps(buy))["trades_aggregated"], 0)
        self.runtime.ingest_message("spot", json.dumps(sell))
        flushed = self.runtime.flush()
        self.assertEqual(flushed["events_saved"], 2)
        flow = self.store.recent_binance_orderflow(
            "2026-09-01T07:59:59+00:00", "2026-09-01T08:00:01+00:00"
        )["SPOT"]
        self.assertEqual(flow["trade_count"], 2)
        self.assertEqual(flow["buy_quantity"], 2)
        self.assertEqual(flow["sell_quantity"], 3)
        row = self.store.connection.execute(
            """SELECT batch_hash, archive_path FROM raw_event_batch_catalog
            WHERE source='BINANCE_WS'"""
        ).fetchone()
        replayed = self.store.load_binance_ws_event_batch(row[0])
        self.assertEqual(len(replayed), 2)
        self.assertEqual(replayed[0]["raw"]["data"]["p"], "100")
        self.assertTrue((Path(self.temporary.name) / row[1]).exists())

    def test_book_ticker_and_depth_create_structured_snapshots(self):
        ticker = {"stream": "btcusdt@bookTicker", "data": {
            "E": self.timestamp_ms, "u": 10,
            "b": "100", "B": "4", "a": "101", "A": "5",
        }}
        depth = {"stream": "btcusdt@depth5@100ms", "data": {
            "E": self.timestamp_ms + 1, "lastUpdateId": 11,
            "bids": [["100", "4"], ["99", "6"]],
            "asks": [["101", "5"], ["102", "7"]],
        }}
        self.assertEqual(self.runtime.ingest_message("spot", json.dumps(ticker))["books_saved"], 1)
        self.assertEqual(self.runtime.ingest_message("spot", json.dumps(depth))["books_saved"], 1)
        self.runtime.flush()
        book = self.store.latest_binance_ws_books()["SPOT"]
        self.assertEqual(book["best_bid"], 100)
        self.assertEqual(book["best_ask"], 101)
        self.assertEqual(book["depth_bid_size"], 10)
        self.assertEqual(book["depth_ask_size"], 12)
        health = self.store.binance_ws_stream_health()["spot"]
        self.assertEqual(health["last_stream"], "btcusdt@depth5@100ms")

    def test_latest_book_lookup_has_source_id_index(self):
        indexes = {
            row[1] for row in self.store.connection.execute(
                "PRAGMA index_list('binance_ws_book_snapshots')"
            ).fetchall()
        }
        self.assertIn("idx_binance_ws_books_source_id", indexes)

    def test_established_connection_retries_in_one_second(self):
        delays = []

        async def fail_after_connect(name, _url):
            self.runtime._connection_established[name] = True
            raise ConnectionError("remote closed")

        async def capture_then_cancel(delay):
            delays.append(delay)
            raise asyncio.CancelledError

        self.runtime._run_connection = fail_after_connect
        with patch("pm_btc.binance_ws.asyncio.sleep", capture_then_cancel):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(self.runtime._connection_forever("spot", "wss://example"))
        self.assertEqual(delays, [1.0])
        payload = self.store.connection.execute(
            "SELECT payload_json FROM audit_events WHERE event_type='binance_ws_error'"
        ).fetchone()[0]
        self.assertIn('"retry_seconds": 1.0', payload)

    def test_unestablished_spot_connection_rotates_to_official_fallback(self):
        attempted = []
        delays = []

        async def fail_before_connect(_name, url):
            attempted.append(url)
            raise TimeoutError("handshake")

        async def capture_then_cancel(delay):
            delays.append(delay)
            if len(delays) == 2:
                raise asyncio.CancelledError

        self.runtime._run_connection = fail_before_connect
        with patch("pm_btc.binance_ws.asyncio.sleep", capture_then_cancel):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(self.runtime._connection_forever(
                    "spot", ("wss://primary", "wss://fallback")
                ))
        self.assertEqual(attempted, ["wss://primary", "wss://fallback"])
        self.assertEqual(delays, [1.0, 1.0])

    def test_research_features_use_spot_and_futures_orderflow(self):
        now = datetime(2026, 9, 1, 8, 0, 30, tzinfo=timezone.utc)
        for source, buy, sell, price in (("SPOT", 600, 400, 100), ("FUTURES", 300, 700, 101)):
            self.store.upsert_binance_orderflow_second({
                "source": source, "bucket_timestamp": now.replace(second=20).isoformat(),
                "received_timestamp": now.isoformat(), "buy_quantity": buy / price,
                "sell_quantity": sell / price, "buy_notional": buy, "sell_notional": sell,
                "trade_count": 10, "last_price": price,
            })
            snapshot = {
                "source": source, "source_timestamp": now.isoformat(),
                "received_timestamp": now.isoformat(), "best_bid": price - .5,
                "best_ask": price + .5, "best_bid_size": 6, "best_ask_size": 4,
                "depth_bid_size": 12, "depth_ask_size": 8,
                "update_id": "1", "snapshot_hash": f"{source}-book",
            }
            self.store.save_binance_ws_book_snapshot(snapshot)
        for name in ("spot", "futures_public", "futures_market"):
            self.store.update_binance_ws_stream_health({
                "connection_name": name, "last_stream": "test",
                "last_source_timestamp": now.isoformat(), "last_received_timestamp": now.isoformat(),
            })
        features, reasons = RealtimeResearchRuntime(Settings(), self.store)._binance_ws_features(now)
        self.assertEqual(reasons, [])
        self.assertAlmostEqual(features["binance_spot_trade_imbalance_60s"], .2)
        self.assertAlmostEqual(features["binance_futures_trade_imbalance_60s"], -.4)
        self.assertAlmostEqual(features["binance_ws_basis_bps"], 100)
        self.assertEqual(features["binance_spot_trade_count_60s"], 10)


if __name__ == "__main__":
    unittest.main()
