from hashlib import sha256
import asyncio
import hmac
import json
from datetime import datetime, timedelta, timezone
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from pm_btc.chainlink_sync import authentication_headers
from pm_btc.chainlink_rtds import PolymarketChainlinkRtdsRuntime
from pm_btc.trusted_dns import ResolvedWebSocketTarget
from pm_btc.storage import SQLiteStore


class ChainlinkSyncTests(unittest.TestCase):
    def test_trusted_dns_stream_keeps_original_tls_identity_and_parses_official_event(self):
        class AuditStore:
            def __init__(self): self.events = []
            def audit(self, event_type, payload): self.events.append((event_type, payload))

        class Resolver:
            async def resolve_websocket(self, uri):
                return ResolvedWebSocketTarget(
                    uri=uri, hostname="ws-live-data.polymarket.com",
                    address="104.18.34.205", port=443,
                )

        class WebSocket:
            def __init__(self): self.sent = []
            async def send(self, message): self.sent.append(message)
            async def recv(self):
                return '{"topic":"crypto_prices_twap_sixty","type":"update",' \
                    '"timestamp":1788163260000,"payload":{"symbol":"btc/usd",' \
                    '"timestamp":1788163260000,"value":"65000.5",' \
                    '"full_accuracy_value":"65000500000000000000000","window_s":60}}'

        captured = {}
        websocket = WebSocket()

        class Connection:
            async def __aenter__(self): return websocket
            async def __aexit__(self, *_): return None

        def connector(uri, **kwargs):
            captured.update({"uri": uri, **kwargs})
            return Connection()

        async def exercise():
            runtime = PolymarketChainlinkRtdsRuntime(
                AuditStore(), resolver=Resolver(), connector=connector,
            )
            stream = runtime._trusted_resolved_stream()
            event = await stream.__anext__()
            await stream.aclose()
            return runtime, event

        runtime, event = asyncio.run(exercise())
        self.assertEqual(event.payload.symbol, "btc/usd")
        self.assertEqual(event.payload.window_seconds, 60)
        self.assertEqual(captured["host"], "104.18.34.205")
        self.assertEqual(captured["server_hostname"], "ws-live-data.polymarket.com")
        self.assertIsNone(captured["proxy"])
        subscription = json.loads(websocket.sent[0])
        self.assertEqual(
            subscription["subscriptions"][0]["topic"],
            "crypto_prices_twap_sixty",
        )
        self.assertTrue(any(name == "chainlink_rtds_connected" for name, _ in runtime.store.events))

    def test_rtds_heartbeat_timeout_audits_and_reconnects(self):
        class AuditStore:
            def __init__(self): self.events = []
            def audit(self, event_type, payload): self.events.append((event_type, payload))

        async def stalled_stream():
            await asyncio.Event().wait()
            yield None

        async def exercise():
            store = AuditStore()
            runtime = PolymarketChainlinkRtdsRuntime(
                store, stream_factory=stalled_stream, heartbeat_timeout_seconds=.01,
            )
            task = asyncio.create_task(runtime.run_forever())
            await asyncio.sleep(.03)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            return store.events

        events = asyncio.run(exercise())
        self.assertTrue(any(event == "chainlink_rtds_error" for event, _ in events))

    def test_rtds_official_sdk_is_primary_then_falls_back_to_trusted_dns(self):
        class AuditStore:
            def __init__(self): self.events = []
            def audit(self, event_type, payload): self.events.append((event_type, payload))

        class Resolver:
            async def resolve_websocket(self, _uri):
                raise OSError("dns route failed")

        async def exercise():
            delays = []
            runtime = PolymarketChainlinkRtdsRuntime(
                AuditStore(), resolver=Resolver(),
                heartbeat_timeout_seconds=.01,
            )

            async def failed_official_stream():
                raise ConnectionError("official route failed")
                yield None

            runtime._official_stream = failed_official_stream

            async def capture_then_cancel(delay):
                delays.append(delay)
                raise asyncio.CancelledError

            with patch("pm_btc.chainlink_rtds.asyncio.sleep", capture_then_cancel):
                try:
                    await runtime.run_forever()
                except asyncio.CancelledError:
                    pass
            return runtime, delays

        runtime, delays = asyncio.run(exercise())
        self.assertEqual(runtime._route, "trusted_dns")
        self.assertEqual(delays, [1.0])
        errors = [payload for event, payload in runtime.store.events if event == "chainlink_rtds_error"]
        self.assertEqual(errors[-1]["route"], "official_sdk")
        fallback = [payload for event, payload in runtime.store.events if event == "chainlink_rtds_route_fallback"]
        self.assertEqual(fallback[-1]["next_route"], "trusted_dns")

    def test_hmac_authentication_matches_documented_string(self):
        path = "/api/v1/reports/latest?feedID=0xabc"
        headers = authentication_headers("key", "secret", path, 1234)
        body_hash = sha256(b"").hexdigest()
        expected = hmac.new(
            b"secret", f"GET {path} {body_hash} key 1234".encode(), sha256
        ).hexdigest()
        self.assertEqual(headers["Authorization"], "key")
        self.assertEqual(headers["X-Authorization-Timestamp"], "1234")
        self.assertEqual(headers["X-Authorization-Signature-SHA256"], expected)

    def test_official_rtds_twap_is_mapped_to_containing_market(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStore(str(Path(directory) / "test.sqlite3"))
            start = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
            store.save_polymarket_market({
                "market_id": "m1", "slug": "btc-updown-5m-1", "condition_id": "c1",
                "start_time": start.isoformat(), "end_time": (start + timedelta(minutes=5)).isoformat(),
                "active": True, "closed": False, "up_token_id": "up", "down_token_id": "down",
                "rule_hash": "rule", "raw": {}, "synced_at": start.isoformat(),
            })
            event = {"topic": "crypto_prices_twap_sixty", "payload": {
                "symbol": "btc/usd", "timestamp": int((start + timedelta(minutes=1)).timestamp() * 1000),
                "value": "65000.500000000000000000", "window_s": 60,
            }}
            result = PolymarketChainlinkRtdsRuntime(store).ingest_event(event)
            self.assertEqual(result, {"matched_markets": 1, "saved": 1})
            row = store.connection.execute(
                "SELECT twap_60s, verification_status, stream_id FROM chainlink_observations"
            ).fetchone()
            self.assertEqual(row[0], 65000.5)
            self.assertEqual(row[1], "VERIFIED")
            self.assertIn("polymarket-rtds", row[2])
            raw = store.connection.execute(
                "SELECT exact_value, raw_json FROM chainlink_rtds_events"
            ).fetchone()
            self.assertEqual(raw[0], "65000.500000000000000000")
            self.assertIn("65000.500000000000000000", raw[1])
            store.close()


if __name__ == "__main__":
    unittest.main()
