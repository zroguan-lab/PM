from datetime import datetime, timedelta, timezone
import asyncio
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
import zlib

from pm_btc.config import Settings
from pm_btc.polymarket_ws import PolymarketClobWebSocketRuntime
from pm_btc.storage import SQLiteStore


class PolymarketWebSocketTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = SQLiteStore(str(Path(self.temporary.name) / "clob.sqlite3"))
        self.now = datetime(2026, 9, 1, 7, 0, tzinfo=timezone.utc)
        self.store.save_polymarket_market({
            "market_id": "m1", "slug": "btc-updown-5m-test", "condition_id": "condition-1",
            "start_time": (self.now - timedelta(minutes=1)).isoformat(),
            "end_time": (self.now + timedelta(minutes=4)).isoformat(),
            "active": True, "closed": False, "up_token_id": "up-token",
            "down_token_id": "down-token", "rule_hash": "rule-1", "raw": {},
            "synced_at": self.now.isoformat(),
        })
        self.runtime = PolymarketClobWebSocketRuntime(
            Settings(polymarket_ws_book_snapshot_interval_seconds=0), self.store
        )
        self.assertEqual(self.runtime._refresh_token_metadata(self.now), {"up-token", "down-token"})

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def test_book_delta_and_trade_are_archived_and_reconstructed(self):
        timestamp_ms = int(self.now.timestamp() * 1000)
        book = {
            "event_type": "book", "asset_id": "up-token", "market": "condition-1",
            "bids": [{"price": "0.49", "size": "10"}, {"price": "0.48", "size": "5"}],
            "asks": [{"price": "0.51", "size": "8"}],
            "timestamp": str(timestamp_ms), "hash": "book-hash",
        }
        result = self.runtime.ingest_message(json.dumps([book]))
        self.assertEqual(result, {"events_saved": 1, "books_saved": 1, "trades_saved": 0})

        change = {
            "event_type": "price_change", "market": "condition-1", "timestamp": str(timestamp_ms + 1),
            "price_changes": [
                {"asset_id": "up-token", "price": "0.49", "size": "0", "side": "BUY", "hash": "c1"},
                {"asset_id": "up-token", "price": "0.50", "size": "3", "side": "BUY", "hash": "c2"},
            ],
        }
        changed = self.runtime.ingest_event(change)
        self.assertEqual(changed["books_saved"], 1)
        latest = self.store.latest_book_for_outcome("m1", "UP")
        self.assertEqual([item["price"] for item in latest["bids"]], ["0.50", "0.48"])

        trade = {
            "event_type": "last_trade_price", "asset_id": "up-token", "market": "condition-1",
            "price": "0.50", "size": "4", "fee_rate_bps": "7", "side": "BUY",
            "timestamp": str(timestamp_ms + 2), "transaction_hash": "0xtrade",
        }
        traded = self.runtime.ingest_event(trade)
        self.assertEqual(traded["trades_saved"], 1)
        trades = self.store.recent_polymarket_trades(
            "m1", (self.now - timedelta(seconds=1)).isoformat(), (self.now + timedelta(seconds=1)).isoformat()
        )
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["outcome"], "UP")
        self.assertEqual(trades[0]["side"], "BUY")
        status = self.store.sync_status()
        self.assertEqual(status["polymarket_clob_events"], 3)
        self.assertEqual(status["polymarket_clob_trades"], 1)

    def test_connection_preserves_ambient_proxy(self):
        captured = {}

        class WebSocket:
            async def __aenter__(self): return self
            async def __aexit__(self, *_): return None
            async def send(self, _message): return None
            async def recv(self): raise ConnectionError("closed")

        def connector(uri, **kwargs):
            captured.update({"uri": uri, **kwargs})
            return WebSocket()

        runtime = PolymarketClobWebSocketRuntime(
            Settings(polymarket_ws_book_snapshot_interval_seconds=0), self.store, connector=connector,
        )
        runtime._refresh_token_metadata = lambda _now=None: {"up-token"}
        with self.assertRaises(ConnectionError):
            asyncio.run(runtime._run_connection())

        self.assertTrue(captured["proxy"])

    def test_duplicate_event_is_idempotent(self):
        event = {
            "event_type": "book", "asset_id": "down-token", "market": "condition-1",
            "bids": [{"price": "0.40", "size": "2"}],
            "asks": [{"price": "0.60", "size": "2"}],
            "timestamp": str(int(self.now.timestamp() * 1000)), "hash": "same",
        }
        first = self.runtime.ingest_event(event)
        second = self.runtime.ingest_event(event)
        self.assertEqual(first["events_saved"], 1)
        self.assertEqual(second["events_saved"], 0)
        self.assertEqual(second["books_saved"], 0)

    def test_live_events_are_batched_compressed_and_replayable(self):
        event = {
            "event_type": "best_bid_ask", "asset_id": "up-token", "market": "condition-1",
            "best_bid": "0.49", "best_ask": "0.51", "spread": "0.02",
            "timestamp": str(int(self.now.timestamp() * 1000)),
        }
        queued = self.runtime.ingest_event(event, archive_immediately=False)
        self.assertEqual(queued["events_saved"], 1)
        self.assertEqual(self.runtime.flush_raw_events(), 1)
        row = self.store.connection.execute(
            """SELECT batch_hash, event_count, archive_path FROM raw_event_batch_catalog
            WHERE source='POLYMARKET_CLOB'"""
        ).fetchone()
        self.assertEqual(row[1], 1)
        replayed = self.store.load_polymarket_clob_event_batch(row[0])
        self.assertEqual(replayed[0]["raw"], event)
        status = self.store.sync_status()
        self.assertEqual(status["polymarket_clob_events"], 1)
        self.assertEqual(status["polymarket_clob_event_batches"], 1)
        self.assertEqual(status["raw_archive_partitions"], 1)
        self.assertTrue((Path(self.temporary.name) / row[2]).exists())

    def test_legacy_main_database_batch_remains_replayable(self):
        events = [{"event_hash": "legacy", "raw": {"event_type": "book"}}]
        encoded = json.dumps(events, sort_keys=True, separators=(",", ":")).encode()
        self.store.connection.execute(
            """INSERT INTO polymarket_clob_event_batches VALUES(
                'legacy-batch', ?, ?, ?, ?, 1, ?
            )""",
            (
                self.now.isoformat(), self.now.isoformat(), self.now.isoformat(),
                self.now.isoformat(), zlib.compress(encoded),
            ),
        )
        self.store.connection.commit()
        self.assertEqual(
            self.store.load_polymarket_clob_event_batch("legacy-batch"), events
        )

    def test_established_connection_retries_in_one_second(self):
        delays = []

        async def fail_after_connect():
            self.runtime._connection_established = True
            raise ConnectionError("remote closed without frame")

        async def capture_then_cancel(delay):
            delays.append(delay)
            raise asyncio.CancelledError

        self.runtime._run_connection = fail_after_connect
        with patch("pm_btc.polymarket_ws.asyncio.sleep", capture_then_cancel):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(self.runtime.run_forever())
        self.assertEqual(delays, [1.0])
        audit = self.store.connection.execute(
            "SELECT payload_json FROM audit_events WHERE event_type='polymarket_clob_ws_error'"
        ).fetchone()[0]
        self.assertIn('"retry_seconds": 1.0', audit)

    def test_preconnect_failure_falls_back_from_ambient_proxy(self):
        delays = []

        class Resolver:
            async def resolve_websocket(self, _uri):
                raise OSError("dns route failed")

        async def capture_then_cancel(delay):
            delays.append(delay)
            raise asyncio.CancelledError

        def connector(*_args, **_kwargs):
            raise ConnectionError("direct route failed")

        runtime = PolymarketClobWebSocketRuntime(
            Settings(polymarket_ws_book_snapshot_interval_seconds=0), self.store,
            connector=connector, resolver=Resolver(),
        )
        runtime._refresh_token_metadata = lambda _now=None: {"up-token"}
        with patch("pm_btc.polymarket_ws.asyncio.sleep", capture_then_cancel):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(runtime.run_forever())

        self.assertEqual(runtime._route, "trusted_dns")
        self.assertEqual(delays, [1.0])
        audit = self.store.connection.execute(
            "SELECT payload_json FROM audit_events WHERE event_type='polymarket_clob_ws_route_fallback'"
        ).fetchone()[0]
        self.assertIn('"next_route": "trusted_dns"', audit)


if __name__ == "__main__":
    unittest.main()
