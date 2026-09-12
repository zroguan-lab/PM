import asyncio
from datetime import datetime, timedelta, timezone
import json
import tempfile
from pathlib import Path
import unittest

from pm_btc.config import Settings
from pm_btc.domain import BookLevel, OrderBook
from pm_btc.polymarket_sync import PolymarketHttpClient, PolymarketSynchronizer
from pm_btc.storage import SQLiteStore


EPOCH = 1_800_000_000
SLUG = f"btc-updown-5m-{EPOCH}"


def market_payload():
    return {
        "id": "market-1",
        "slug": SLUG,
        "conditionId": "condition-1",
        "outcomes": json.dumps(["Up", "Down"]),
        "clobTokenIds": json.dumps(["up-token", "down-token"]),
        "active": True,
        "closed": False,
        "orderPriceMinTickSize": 0.01,
        "orderMinSize": 5,
    }


class FakeGetter:
    def __init__(self):
        self.calls = []

    def __call__(self, url, params=None):
        self.calls.append((url, params))
        if "/markets/slug/" in url:
            return market_payload() if url.endswith(SLUG) else {}
        if "/events/slug/" in url:
            return {}
        if url.endswith("/book"):
            return {
                "timestamp": str(EPOCH * 1000),
                "hash": f"hash-{params['token_id']}",
                "bids": [{"price": "0.48", "size": "20"}],
                "asks": [{"price": "0.52", "size": "10"}],
            }
        if url.endswith("/fee-rate"):
            return {"base_fee": 30}
        if "/clob-markets/" in url:
            return {"fd": {"r": 0.07, "e": 1, "to": True}, "tbf": 1000, "mbf": 1000,
                    "mts": 0.01, "mos": 5, "v": "v1"}
        raise AssertionError(url)


class TimeoutRecordingGetter(FakeGetter):
    def __init__(self):
        super().__init__()
        self.timeouts = []

    def __call__(self, url, params=None, timeout=None):
        self.timeouts.append((url, timeout))
        return super().__call__(url, params)


class FlakyBookGetter(FakeGetter):
    def __init__(self, failures: int):
        super().__init__()
        self.failures = failures

    def __call__(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        if url.endswith("/book") and params["token_id"] == "up-token" and self.failures > 0:
            self.failures -= 1
            raise TimeoutError("temporary book timeout")
        if url.endswith("/book"):
            return {
                "timestamp": str(EPOCH * 1000),
                "hash": f"hash-{params['token_id']}",
                "bids": [{"price": "0.48", "size": "20"}],
                "asks": [{"price": "0.52", "size": "10"}],
            }
        return super().__call__(url, params)


class PolymarketSyncTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(discovery_past_markets=0, discovery_future_markets=0)
        self.getter = FakeGetter()
        self.client = PolymarketHttpClient(self.settings, self.getter)

    def test_market_and_book_parsing(self):
        market = self.client.parse_market(market_payload())
        self.assertEqual(market.rule.token_ids, {"UP": "up-token", "DOWN": "down-token"})
        self.assertEqual(self.client.get_fee_rate("up-token"), {"base_fee": 30})
        self.assertEqual(self.client.get_clob_market_info("condition-1")["fd"]["r"], .07)
        book, _ = self.client.get_orderbook("up-token")
        self.assertEqual(book.best_bid, 0.48)
        self.assertEqual(book.best_ask, 0.52)

    def test_orderbook_uses_short_timeout(self):
        settings = Settings(
            discovery_past_markets=0,
            discovery_future_markets=0,
            polymarket_orderbook_timeout_seconds=1.25,
            polymarket_gamma_timeout_seconds=4.5,
            polymarket_clob_timeout_seconds=5.5,
        )
        getter = TimeoutRecordingGetter()
        client = PolymarketHttpClient(settings, getter)

        client.get_market_by_slug(SLUG)
        client.get_orderbook("up-token")
        client.get_clob_market_info("condition-1")

        timeouts = {url.rsplit("/", 1)[-1]: timeout for url, timeout in getter.timeouts}
        self.assertEqual(timeouts[SLUG], 4.5)
        self.assertEqual(timeouts["book"], 1.25)
        self.assertEqual(timeouts["condition-1"], 5.5)

    def test_sync_once_persists_market_and_both_books(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = SQLiteStore(str(Path(temporary) / "sync.sqlite3"))
            sync = PolymarketSynchronizer(self.settings, self.client, store)
            now = datetime.fromtimestamp(EPOCH, tz=timezone.utc)
            result = asyncio.run(sync.sync_once(now))
            status = store.sync_status()
            store.close()
        self.assertEqual(result, {"status": "SUCCEEDED", "markets": 1, "books_saved": 2})
        self.assertEqual(status["markets"], 1)
        self.assertEqual(status["orderbook_snapshots"], 2)
        self.assertEqual(status["latest_run"]["status"], "SUCCEEDED")

    def test_cached_book_poll_does_not_rewrite_market_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = SQLiteStore(str(Path(temporary) / "cached.sqlite3"))
            sync = PolymarketSynchronizer(self.settings, self.client, store)
            now = datetime.fromtimestamp(EPOCH, tz=timezone.utc)
            asyncio.run(sync.sync_once(now))
            first_synced_at = store.connection.execute(
                "SELECT synced_at FROM polymarket_markets WHERE market_id='market-1'"
            ).fetchone()[0]
            result = asyncio.run(sync.sync_once(now, force_discovery=False))
            second_synced_at = store.connection.execute(
                "SELECT synced_at FROM polymarket_markets WHERE market_id='market-1'"
            ).fetchone()[0]
            store.close()
        self.assertEqual(first_synced_at, second_synced_at)
        self.assertEqual(result["markets"], 1)

    def test_cached_book_poll_runs_before_due_discovery_refresh(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = SQLiteStore(str(Path(temporary) / "book-first.sqlite3"))
            settings = Settings(
                discovery_past_markets=0,
                discovery_future_markets=0,
                market_discovery_interval_seconds=0,
            )
            getter = FakeGetter()
            client = PolymarketHttpClient(settings, getter)
            sync = PolymarketSynchronizer(settings, client, store)
            now = datetime.fromtimestamp(EPOCH, tz=timezone.utc)
            asyncio.run(sync.sync_once(now))
            getter.calls.clear()

            asyncio.run(sync.sync_once(now, force_discovery=False))
            store.close()

        urls = [url for url, _params in getter.calls]
        first_book = next(index for index, url in enumerate(urls) if url.endswith("/book"))
        first_discovery = next(index for index, url in enumerate(urls) if "/markets/slug/" in url)
        self.assertLess(first_book, first_discovery)

    def test_book_poll_once_uses_cache_without_market_discovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = SQLiteStore(str(Path(temporary) / "book-only.sqlite3"))
            sync = PolymarketSynchronizer(self.settings, self.client, store)
            now = datetime.fromtimestamp(EPOCH, tz=timezone.utc)
            asyncio.run(sync.refresh_markets_once(now))
            self.getter.calls.clear()

            result = asyncio.run(sync.poll_books_once(now))
            status = store.sync_status()
            store.close()

        urls = [url for url, _params in self.getter.calls]
        self.assertEqual(result["books_saved"], 2)
        self.assertEqual(result["expected_books"], 2)
        self.assertEqual(result["received_books"], 2)
        self.assertEqual(result["complete_markets"], 1)
        self.assertEqual(status["polymarket_book_poll_runs_30m"], 1)
        self.assertEqual(status["polymarket_book_fetch_coverage_30m"], 1.0)
        self.assertEqual(status["polymarket_complete_market_rate_30m"], 1.0)
        self.assertEqual(status["polymarket_book_poll_runs_24h"], 1)
        self.assertEqual(status["polymarket_book_fetch_coverage_24h"], 1.0)
        self.assertEqual(status["polymarket_book_poll_runs_audit"], 1)
        self.assertEqual(status["polymarket_complete_market_rate_audit"], 1.0)
        self.assertIsNotNone(status["polymarket_book_audit_started_at"])
        self.assertTrue(any(url.endswith("/book") for url in urls))
        self.assertFalse(any("/markets/slug/" in url for url in urls))

    def test_book_poll_once_loads_nearby_markets_from_store_after_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = SQLiteStore(str(Path(temporary) / "restart-book.sqlite3"))
            now = datetime.fromtimestamp(EPOCH, tz=timezone.utc)
            asyncio.run(PolymarketSynchronizer(self.settings, self.client, store).refresh_markets_once(now))
            self.getter.calls.clear()

            restarted = PolymarketSynchronizer(self.settings, self.client, store)
            result = asyncio.run(restarted.poll_books_once(now))
            store.close()

        urls = [url for url, _params in self.getter.calls]
        self.assertEqual(result["books_saved"], 2)
        self.assertTrue(any(url.endswith("/book") for url in urls))
        self.assertFalse(any("/markets/slug/" in url for url in urls))

    def test_book_poll_retries_a_transient_token_failure_without_losing_the_round(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = SQLiteStore(str(Path(temporary) / "retry-book.sqlite3"))
            getter = FlakyBookGetter(failures=1)
            sync = PolymarketSynchronizer(self.settings, PolymarketHttpClient(self.settings, getter), store)
            now = datetime.fromtimestamp(EPOCH, tz=timezone.utc)
            asyncio.run(sync.refresh_markets_once(now))
            getter.calls.clear()

            result = asyncio.run(sync.poll_books_once(now))
            status = store.sync_status()
            store.close()

        book_calls = [call for call in getter.calls if call[0].endswith("/book")]
        self.assertEqual(len(book_calls), 3)
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["received_books"], 2)
        self.assertEqual(status["polymarket_book_poll_success_rate_30m"], 1.0)
        self.assertEqual(status["polymarket_open_book_gaps"], 0)

    def test_book_poll_preserves_successful_token_when_another_stays_unavailable(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = SQLiteStore(str(Path(temporary) / "partial-book.sqlite3"))
            getter = FlakyBookGetter(failures=2)
            sync = PolymarketSynchronizer(self.settings, PolymarketHttpClient(self.settings, getter), store)
            now = datetime.fromtimestamp(EPOCH, tz=timezone.utc)
            asyncio.run(sync.refresh_markets_once(now))
            getter.calls.clear()

            result = asyncio.run(sync.poll_books_once(now))
            saved = store.connection.execute("SELECT outcome FROM orderbook_snapshots").fetchall()
            poll = store.connection.execute(
                "SELECT status, expected_books, received_books, error FROM polymarket_book_poll_runs"
            ).fetchone()
            gap_after_failure = store.sync_status()
            recovered = asyncio.run(sync.poll_books_once(now + timedelta(seconds=1)))
            gap_after_recovery = store.sync_status()
            store.close()

        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["received_books"], 1)
        self.assertEqual([row[0] for row in saved], ["DOWN"])
        self.assertEqual(tuple(poll[:3]), ("PARTIAL", 2, 1))
        self.assertIn("temporary book timeout", poll[3])
        self.assertEqual(gap_after_failure["polymarket_book_gap_events"], 1)
        self.assertEqual(gap_after_failure["polymarket_open_book_gaps"], 1)
        self.assertEqual(recovered["status"], "SUCCEEDED")
        self.assertEqual(gap_after_recovery["polymarket_open_book_gaps"], 0)
        self.assertEqual(gap_after_recovery["polymarket_recovered_book_gaps"], 1)

    def test_book_only_poll_does_not_discover_when_cache_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = SQLiteStore(str(Path(temporary) / "empty-book-only.sqlite3"))
            sync = PolymarketSynchronizer(self.settings, self.client, store)
            now = datetime.fromtimestamp(EPOCH, tz=timezone.utc)

            result = asyncio.run(sync.poll_books_once(now, discover_if_empty=False))
            store.close()

        urls = [url for url, _params in self.getter.calls]
        self.assertEqual(result, {"status": "SUCCEEDED", "markets": 0, "books_saved": 0})
        self.assertFalse(any("/markets/slug/" in url for url in urls))
        self.assertFalse(any(url.endswith("/book") for url in urls))

    def test_market_refresh_once_does_not_poll_orderbooks(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = SQLiteStore(str(Path(temporary) / "discovery-only.sqlite3"))
            sync = PolymarketSynchronizer(self.settings, self.client, store)
            now = datetime.fromtimestamp(EPOCH, tz=timezone.utc)

            result = asyncio.run(sync.refresh_markets_once(now))
            store.close()

        urls = [url for url, _params in self.getter.calls]
        self.assertEqual(result["markets"], 1)
        self.assertTrue(any("/markets/slug/" in url for url in urls))
        self.assertFalse(any(url.endswith("/book") for url in urls))

    def test_normalized_orderbook_caps_depth_without_changing_best_prices(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = SQLiteStore(str(Path(temporary) / "depth.sqlite3"))
            now = datetime.fromtimestamp(EPOCH, tz=timezone.utc)
            bids = [{"price": str(.50 - index / 1000), "size": "1"} for index in range(30)]
            asks = [{"price": str(.51 + index / 1000), "size": "1"} for index in range(30)]
            book = OrderBook(
                "up-token",
                tuple(BookLevel(float(level["price"]), 1) for level in bids),
                tuple(BookLevel(float(level["price"]), 1) for level in asks),
                now,
            )
            store.save_orderbook("m1", "UP", book, {"bids": bids, "asks": asks, "hash": "depth"})
            row = store.connection.execute(
                "SELECT best_bid, best_ask, bids_json, asks_json FROM orderbook_snapshots"
            ).fetchone()
            store.close()
        self.assertEqual(row[0], .50)
        self.assertEqual(row[1], .51)
        self.assertEqual(len(json.loads(row[2])), 20)
        self.assertEqual(len(json.loads(row[3])), 20)


if __name__ == "__main__":
    unittest.main()
