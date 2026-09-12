from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from pm_btc.config import Settings
from pm_btc.domain import BookLevel, ChainlinkObservation, MarketRuleVersion, OrderBook, VerificationStatus
from pm_btc.server import build_data_readiness, status_payload
from pm_btc.storage import SQLiteStore


class ServerStatusTests(unittest.TestCase):
    def test_empty_database_reports_data_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings = Settings(database_path=str(Path(temporary) / "empty.sqlite3"))
            store = SQLiteStore(settings.database_path)
            store.close()

            payload = status_payload(settings)

        self.assertEqual(payload["data_readiness"]["status"], "DATA_BLOCKED")
        self.assertFalse(payload["data_readiness"]["data_ready"])
        self.assertIn("polymarket_market_missing", payload["data_readiness"]["blocking_reasons"])
        self.assertIn("polymarket_rest_orderbook_not_fresh", payload["data_readiness"]["blocking_reasons"])
        self.assertIn("chainlink_verified_twap_not_fresh", payload["data_readiness"]["blocking_reasons"])

    def test_complete_data_without_model_waits_for_model(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        with tempfile.TemporaryDirectory() as temporary:
            settings = Settings(database_path=str(Path(temporary) / "ready.sqlite3"))
            store = SQLiteStore(settings.database_path)
            rule = MarketRuleVersion(
                market_id="m1",
                condition_id="c1",
                resolution_source_url="chainlink",
                chainlink_stream_id="btc-twap",
                fee_rule_version="fee",
                fee_schedule={},
                market_schema_version="v1",
                tick_size=.01,
                minimum_order_size=1,
                start_time=now,
                end_time=now + timedelta(minutes=5),
                token_ids={"UP": "up", "DOWN": "down"},
            )
            store.save_rule(rule)
            store.save_polymarket_market({
                "market_id": "m1",
                "slug": "btc-updown-5m-ready",
                "condition_id": "c1",
                "start_time": rule.start_time.isoformat(),
                "end_time": rule.end_time.isoformat(),
                "active": True,
                "closed": False,
                "up_token_id": "up",
                "down_token_id": "down",
                "rule_hash": rule.resolution_rule_hash,
                "raw": {},
                "synced_at": now.isoformat(),
            })
            for outcome, token in (("UP", "up"), ("DOWN", "down")):
                store.save_orderbook(
                    "m1",
                    outcome,
                    OrderBook(token, (BookLevel(.49, 10),), (BookLevel(.51, 10),), now),
                    {"bids": [{"price": .49, "size": 10}], "asks": [{"price": .51, "size": 10}], "hash": token},
                )
            store.save_polymarket_clob_event({
                "event_hash": "clob-1",
                "event_type": "book",
                "market_id": "m1",
                "condition_id": "c1",
                "asset_id": "up",
                "source_timestamp": now.isoformat(),
                "received_timestamp": now.isoformat(),
                "raw": {},
            })
            store.save_binance_features({
                "symbol": "BTCUSDT",
                "source_timestamp": now.isoformat(),
                "received_timestamp": now.isoformat(),
                "spot_bid": 100,
                "spot_ask": 101,
                "spot_mid": 100.5,
                "spot_imbalance": 0,
                "futures_bid": 100,
                "futures_ask": 101,
                "futures_mid": 100.5,
                "futures_imbalance": 0,
                "basis_bps": 0,
                "open_interest": 1,
                "funding_rate": 0,
                "mark_price": 100.5,
                "index_price": 100.5,
                "raw": {},
                "snapshot_hash": "feature-1",
            })
            for connection in ("spot", "futures_public", "futures_market"):
                store.update_binance_ws_stream_health({
                    "connection_name": connection,
                    "last_stream": "btcusdt@bookTicker",
                    "last_source_timestamp": now.isoformat(),
                    "last_received_timestamp": now.isoformat(),
                })
            store.save_chainlink(ChainlinkObservation(
                stream_id="btc-twap",
                source_timestamp=now,
                received_timestamp=now,
                twap_60s=100,
                report_id="r1",
                verification_status=VerificationStatus.VERIFIED,
                raw_payload_hash="chainlink-1",
                market_id="m1",
            ))
            store.save_research_prediction({
                "market_id": "m1",
                "prediction_timestamp": now.isoformat(),
                "market_probability_up": .50,
                "p_raw": None,
                "p_calibrated": None,
                "p_lower": None,
                "p_upper": None,
                "conservative_edge": None,
                "decision": "NO_TRADE",
                "no_trade_reasons": ["trained_calibrated_alpha_model_unavailable"],
                "features": {
                    "resolution_pressure": 1.25,
                    "required_remaining_twap": 99.5,
                    "current_cumulative_twap": 100.25,
                    "provisional_resolution": "UP",
                    "binance_spot_trade_imbalance_60s": .6,
                    "binance_futures_trade_imbalance_60s": .4,
                    "binance_spot_ws_top_imbalance": .2,
                    "binance_futures_ws_top_imbalance": -.1,
                },
                "model_version": "market-baseline-only-v1",
            })
            sync = store.sync_status()
            prediction = store.latest_research_prediction()
            store.close()
            payload = status_payload(settings)

        health = {
            "binance_fresh": True,
            "binance_ws_fresh": True,
            "binance_ws_stream_ages": {"spot": 0, "futures_public": 0, "futures_market": 0},
            "polymarket_orderbook_fresh": True,
            "polymarket_orderbook_age_seconds": 0,
            "polymarket_clob_fresh": True,
            "polymarket_clob_age_seconds": 0,
            "chainlink_configured": True,
            "chainlink_fresh": True,
            "chainlink_age_seconds": 0,
        }
        readiness = build_data_readiness(settings, sync, health, prediction, None)

        self.assertEqual(readiness["status"], "WAITING_FOR_MODEL")
        self.assertTrue(readiness["data_ready"])
        self.assertFalse(readiness["research_ready"])
        self.assertEqual(readiness["blocking_reasons"], ["published_model_missing_or_invalid"])
        self.assertEqual(payload["live_markets"][0]["market_id"], "m1")
        self.assertEqual(payload["live_markets"][0]["phase"], "CURRENT")
        self.assertEqual(payload["live_markets"][0]["books"]["UP"]["best_ask"], .51)
        self.assertTrue(payload["prediction_health"]["fresh"])
        self.assertEqual(payload["current_prediction"]["market_id"], "m1")
        self.assertEqual(payload["btc_judgment"]["direction"], "UP")
        self.assertEqual(payload["btc_judgment"]["strength"], "MODERATE")
        self.assertFalse(payload["btc_judgment"]["tradable"])
        self.assertEqual(payload["btc_trend_judgment"]["direction"], "UP")
        self.assertEqual(payload["btc_trend_judgment"]["strength"], "MODERATE")
        self.assertFalse(payload["btc_trend_judgment"]["calibrated"])
        self.assertFalse(payload["btc_trend_judgment"]["tradable"])


if __name__ == "__main__":
    unittest.main()
