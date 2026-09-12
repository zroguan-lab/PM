from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from pm_btc.config import Settings
from pm_btc.domain import (
    BookLevel, ChainlinkObservation, MarketRuleVersion, OrderBook, VerificationStatus,
)
from pm_btc.research_runtime import RealtimeResearchRuntime
from pm_btc.storage import SQLiteStore


class ResearchRuntimeTests(unittest.TestCase):
    def test_incomplete_final_state_is_idempotent_until_new_chainlink_data_arrives(self):
        end = datetime(2026, 8, 30, 12, 5, tzinfo=timezone.utc)
        start = end - timedelta(minutes=5)
        with tempfile.TemporaryDirectory() as temporary:
            store = SQLiteStore(str(Path(temporary) / "incomplete-state.sqlite3"))
            rule = MarketRuleVersion(
                market_id="m-gap", condition_id="c-gap", resolution_source_url="chainlink",
                chainlink_stream_id="btc-twap", fee_rule_version="fee", fee_schedule={},
                market_schema_version="v1", tick_size=.01, minimum_order_size=1,
                start_time=start, end_time=end, token_ids={"UP": "up-gap", "DOWN": "down-gap"},
            )
            store.save_rule(rule)
            store.save_polymarket_market({
                "market_id": "m-gap", "slug": "btc-updown-5m-gap", "condition_id": "c-gap",
                "start_time": start.isoformat(), "end_time": end.isoformat(),
                "active": False, "closed": True, "up_token_id": "up-gap", "down_token_id": "down-gap",
                "rule_hash": rule.resolution_rule_hash, "raw": {}, "synced_at": end.isoformat(),
            })
            store.save_chainlink(ChainlinkObservation(
                stream_id="btc-twap", source_timestamp=start, received_timestamp=start,
                twap_60s=100, report_id="start", verification_status=VerificationStatus.VERIFIED,
                raw_payload_hash="start-hash", market_id="m-gap",
            ))
            runtime = RealtimeResearchRuntime(Settings(), store)
            first = runtime.finalize_chainlink_labels(end + timedelta(seconds=1))
            second = runtime.finalize_chainlink_labels(end + timedelta(seconds=2))
            store.save_chainlink(ChainlinkObservation(
                stream_id="btc-twap", source_timestamp=end, received_timestamp=end,
                twap_60s=101, report_id="end", verification_status=VerificationStatus.VERIFIED,
                raw_payload_hash="end-hash", market_id="m-gap",
            ))
            third = runtime.finalize_chainlink_labels(end + timedelta(seconds=3))
            snapshot_count = store.connection.execute(
                "SELECT COUNT(*) FROM resolution_state_snapshots WHERE market_id='m-gap'"
            ).fetchone()[0]
            store.close()
        self.assertEqual(first, {"finalized": 0, "rejected": 1})
        self.assertEqual(second, {"finalized": 0, "rejected": 0})
        self.assertEqual(third, {"finalized": 0, "rejected": 1})
        self.assertEqual(snapshot_count, 1)

    def test_research_ledger_normalizes_one_usdc_and_settles(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = SQLiteStore(str(Path(temporary) / "research-ledger.sqlite3"))
            saved = store.save_research_prediction({
                "market_id": "m-ledger", "prediction_timestamp": "2026-01-01T00:00:01+00:00",
                "market_probability_up": .38, "p_raw": .62, "p_calibrated": .60,
                "p_lower": .55, "p_upper": .65, "conservative_edge": .10,
                "decision": "NO_TRADE", "no_trade_reasons": ["conservative_edge_below_buffer"],
                "features": {
                    "research_side": "UP", "research_executable_price": .40,
                    "research_fees_per_share": .01, "research_net_edge": .19,
                    "research_conservative_net_edge": .14,
                },
                "model_version": "test-model",
            })
            self.assertTrue(saved)
            row = store.connection.execute(
                "SELECT normalized_stake, normalized_shares, decision FROM research_ledger"
            ).fetchone()
            self.assertEqual(row[0], 1.0)
            self.assertAlmostEqual(row[1], 1.0 / .41)
            self.assertEqual(row[2], "NO_TRADE")
            store.save_market_label({
                "market_id": "m-ledger", "rule_hash": "rule", "start_price": 100,
                "final_twap": 101, "outcome": "UP", "observation_count": 6,
                "finalized_at": "2026-01-01T00:05:01+00:00",
            })
            self.assertEqual(store.settle_research_ledger(), 1)
            pnl = store.connection.execute("SELECT realized_pnl FROM research_ledger").fetchone()[0]
            self.assertAlmostEqual(pnl, 1.0 / .41 - 1.0)
            store.close()

    def test_market_baseline_is_recorded_but_chainlink_blocks_trade(self):
        now = datetime(2026, 8, 30, 12, 2, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            store = SQLiteStore(str(Path(temporary) / "research.sqlite3"))
            rule = MarketRuleVersion(
                market_id="m1", condition_id="c1", resolution_source_url="chainlink",
                chainlink_stream_id="btc-twap", fee_rule_version="fee", fee_schedule={},
                market_schema_version="v1", tick_size=0.01, minimum_order_size=1,
                start_time=now - timedelta(minutes=2), end_time=now + timedelta(minutes=3),
                token_ids={"UP": "up", "DOWN": "down"},
            )
            store.save_rule(rule)
            store.save_polymarket_market({
                "market_id": "m1", "slug": "btc-updown-5m-test", "condition_id": "c1",
                "start_time": (now - timedelta(minutes=2)).isoformat(),
                "end_time": (now + timedelta(minutes=3)).isoformat(),
                "active": True, "closed": False, "up_token_id": "up", "down_token_id": "down",
                "rule_hash": rule.resolution_rule_hash, "raw": {}, "synced_at": now.isoformat(),
            })
            for outcome, token, bid, ask in (
                ("UP", "up", 0.54, 0.56), ("DOWN", "down", 0.44, 0.46)
            ):
                book = OrderBook(token, (BookLevel(bid, 10),), (BookLevel(ask, 10),), now)
                store.save_orderbook("m1", outcome, book, {"bids": [{"price": bid, "size": 10}], "asks": [{"price": ask, "size": 10}], "hash": token})
            store.save_binance_features({
                "symbol": "BTCUSDT", "source_timestamp": now.isoformat(), "received_timestamp": now.isoformat(),
                "spot_bid": 100, "spot_ask": 101, "spot_mid": 100.5, "spot_imbalance": 0,
                "futures_bid": 100, "futures_ask": 101, "futures_mid": 100.5,
                "futures_imbalance": 0, "basis_bps": 0, "open_interest": 1,
                "funding_rate": 0, "mark_price": 100.5, "index_price": 100.5,
                "raw": {}, "snapshot_hash": "features-1",
            })
            for event_hash, asset_id, outcome, side, size in (
                ("trade-up", "up", "UP", "BUY", 4),
                ("trade-down", "down", "DOWN", "BUY", 1),
            ):
                store.save_polymarket_clob_trade({
                    "event_hash": event_hash, "market_id": "m1", "condition_id": "c1",
                    "asset_id": asset_id, "outcome": outcome, "price": .5,
                    "size": size, "side": side, "fee_rate_bps": 0,
                    "source_timestamp": (now - timedelta(seconds=10)).isoformat(),
                    "received_timestamp": now.isoformat(),
                })
            result = RealtimeResearchRuntime(Settings(), store).evaluate_once(now)
            latest = store.latest_research_prediction()
            for minute, price in enumerate((100, 101, 102, 103, 104, 105)):
                observed = rule.start_time + timedelta(minutes=minute)
                store.save_chainlink(ChainlinkObservation(
                    stream_id="btc-twap", source_timestamp=observed,
                    received_timestamp=observed + timedelta(seconds=1), twap_60s=price,
                    report_id=str(minute), verification_status=VerificationStatus.VERIFIED,
                    raw_payload_hash=f"hash-{minute}", market_id="m1",
                ))
            labels = RealtimeResearchRuntime(Settings(), store).finalize_chainlink_labels(
                rule.end_time + timedelta(seconds=1)
            )
            final_state = store.connection.execute(
                """SELECT settlement_complete, data_complete, observation_count,
                provisional_resolution FROM resolution_state_snapshots
                WHERE market_id='m1' ORDER BY id DESC LIMIT 1"""
            ).fetchone()
            stale = RealtimeResearchRuntime(Settings(), store).evaluate_once(now + timedelta(seconds=10))
            label_count = store.sync_status()["chainlink_market_labels"]
            store.close()
        self.assertEqual(result["decision"], "NO_TRADE")
        self.assertAlmostEqual(result["market_probability_up"], 0.55)
        self.assertEqual(result["features"]["polymarket_trade_count_60s"], 2)
        self.assertAlmostEqual(result["features"]["polymarket_trade_imbalance_60s"], .6)
        self.assertIn("chainlink_missing_or_unverified", result["no_trade_reasons"])
        self.assertEqual(latest["market_id"], "m1")
        self.assertEqual(labels["finalized"], 1)
        self.assertEqual(label_count, 1)
        self.assertEqual(final_state, (1, 1, 6, "UP"))
        self.assertIn("binance_features_stale", stale["no_trade_reasons"])


if __name__ == "__main__":
    unittest.main()
