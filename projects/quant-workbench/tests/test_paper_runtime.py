from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from pm_btc.config import Settings
from pm_btc.domain import BookLevel, OrderBook
from pm_btc.paper_runtime import PaperTradingRuntime
from pm_btc.storage import SQLiteStore


class PaperRuntimeTests(unittest.TestCase):
    def test_taker_signal_fills_and_settles_all_counterfactual_books(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            store = SQLiteStore(str(Path(temporary) / "paper.sqlite3"))
            store.save_polymarket_market({
                "market_id": "m", "slug": "btc-test", "condition_id": "c",
                "start_time": (now - timedelta(minutes=1)).isoformat(),
                "end_time": (now + timedelta(minutes=4)).isoformat(),
                "active": True, "closed": False, "up_token_id": "u", "down_token_id": "d",
                "rule_hash": "rule", "raw": {}, "synced_at": now.isoformat(),
            })
            book = OrderBook("u", (BookLevel(.49, 10),), (BookLevel(.50, 10),), now)
            store.save_orderbook("m", "UP", book, {
                "bids": [{"price": .49, "size": 10}], "asks": [{"price": .50, "size": 10}], "hash": "book",
            })
            store.save_research_prediction({
                "market_id": "m", "prediction_timestamp": now.isoformat(),
                "market_probability_up": .6, "p_raw": .7, "p_calibrated": .7,
                "p_lower": .65, "p_upper": .75, "conservative_edge": .14,
                "decision": "TAKER", "no_trade_reasons": [], "model_version": "test",
                "features": {"execution_side": "UP", "execution_price": .50, "execution_size": 1},
            })
            runtime = PaperTradingRuntime(Settings(paper_starting_cash=10), store)
            self.assertEqual(runtime.create_from_next_signal(), 3)
            self.assertEqual(runtime.update_orders(now)["filled"], 3)
            store.save_market_label({
                "market_id": "m", "rule_hash": "rule", "start_price": 100,
                "final_twap": 101, "outcome": "UP", "observation_count": 5,
                "finalized_at": now.isoformat(),
            })
            self.assertEqual(runtime.update_orders(now)["settled"], 3)
            status = store.sync_status()
            store.close()
        self.assertEqual(status["paper_orders"], 3)
        self.assertAlmostEqual(status["paper_realized_pnl"], 1.5)
        self.assertEqual(status["capacity_points"], 5)


if __name__ == "__main__":
    unittest.main()
