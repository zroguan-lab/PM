import asyncio
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError, URLError

from pm_btc.binance_sync import BinanceHttpClient, BinanceSynchronizer
from pm_btc.config import Settings
from pm_btc.storage import SQLiteStore


class FakeGetter:
    def __call__(self, url, params=None):
        if url.endswith("/api/v3/ticker/bookTicker"):
            return {"bidPrice": "100", "askPrice": "102"}
        if url.endswith("/api/v3/depth"):
            return {"lastUpdateId": 1, "bids": [["100", "3"]], "asks": [["102", "1"]]}
        if url.endswith("/fapi/v1/ticker/bookTicker"):
            return {"bidPrice": "101", "askPrice": "103", "time": 1_800_000_000_000}
        if url.endswith("/fapi/v1/depth"):
            return {"E": 1_800_000_000_000, "bids": [["101", "2"]], "asks": [["103", "2"]]}
        if url.endswith("/fapi/v1/premiumIndex"):
            return {"time": 1_800_000_000_000, "markPrice": "102", "indexPrice": "101", "lastFundingRate": "0.0001"}
        if url.endswith("/fapi/v1/openInterest"):
            return {"time": 1_800_000_000_000, "openInterest": "12345"}
        raise AssertionError(url)


class BinanceSyncTests(unittest.TestCase):
    def test_feature_snapshot_and_persistence(self):
        settings = Settings()
        client = BinanceHttpClient(settings, FakeGetter())
        snapshot = client.snapshot().values
        self.assertEqual(snapshot["spot_mid"], 101)
        self.assertEqual(snapshot["futures_mid"], 102)
        self.assertAlmostEqual(snapshot["spot_imbalance"], 0.5)
        self.assertAlmostEqual(snapshot["basis_bps"], 10000 / 101)
        with tempfile.TemporaryDirectory() as temporary:
            store = SQLiteStore(str(Path(temporary) / "features.sqlite3"))
            result = asyncio.run(BinanceSynchronizer(settings, client, store).sync_once())
            status = store.sync_status()
            store.close()
        self.assertTrue(result["saved"])
        self.assertEqual(status["binance_feature_snapshots"], 1)

    def test_spot_failover_is_sticky_and_archives_selected_endpoint(self):
        calls = []

        class FailoverGetter(FakeGetter):
            def __call__(self, url, params=None):
                calls.append(url)
                if url.startswith("https://primary.example"):
                    raise URLError("primary unavailable")
                return super().__call__(url, params)

        settings = Settings(
            binance_spot_base_url="https://primary.example",
            binance_spot_fallback_urls=("https://fallback.example",),
        )
        client = BinanceHttpClient(settings, FailoverGetter())
        snapshot = client.snapshot().values
        endpoints = snapshot["raw"]["source_endpoints"]
        self.assertEqual(endpoints["spot_quote"], "https://fallback.example")
        self.assertEqual(endpoints["spot_depth"], "https://fallback.example")
        primary_attempts = sum(url.startswith("https://primary.example") for url in calls)
        self.assertIn(primary_attempts, (1, 2))
        client.snapshot()
        self.assertEqual(sum(url.startswith("https://primary.example") for url in calls), primary_attempts)

    def test_rate_limit_does_not_rotate_hosts(self):
        calls = []

        def rate_limited(url, params=None):
            calls.append(url)
            raise HTTPError(url, 429, "rate limited", {}, None)

        settings = Settings(
            binance_spot_base_url="https://primary.example",
            binance_spot_fallback_urls=("https://fallback.example",),
        )
        with self.assertRaises(HTTPError):
            BinanceHttpClient(settings, rate_limited).snapshot()
        self.assertGreaterEqual(sum(url.startswith("https://primary.example") for url in calls), 1)
        self.assertFalse(any(url.startswith("https://fallback.example") for url in calls))


if __name__ == "__main__":
    unittest.main()
