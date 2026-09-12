import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

from pm_btc.domain import ChainlinkObservation, MarketRuleVersion, Side, VerificationStatus
from pm_btc.resolution import ResolutionStateEngine
from pm_btc.storage import SQLiteStore


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.rule = MarketRuleVersion(
            market_id="m1", condition_id="c1", resolution_source_url="chainlink",
            chainlink_stream_id="btc-twap", fee_rule_version="fee-v1",
            fee_schedule={"rate": 0.07}, market_schema_version="schema-v1",
            tick_size=0.01, minimum_order_size=1, start_time=self.start,
            end_time=self.start + timedelta(minutes=5), token_ids={"UP": "u", "DOWN": "d"},
        )

    def observation(self, minute, price, verified=True):
        return ChainlinkObservation(
            stream_id="btc-twap", source_timestamp=self.start + timedelta(minutes=minute),
            received_timestamp=self.start + timedelta(minutes=minute, seconds=1), twap_60s=price,
            report_id=str(minute), verification_status=VerificationStatus.VERIFIED if verified else VerificationStatus.INVALID,
            raw_payload_hash=str(minute), market_id="m1",
        )

    def test_required_remaining_twap(self):
        observations = [self.observation(0, 100), self.observation(1, 101), self.observation(2, 102)]
        state = ResolutionStateEngine().calculate(
            self.rule, 100, observations, self.start + timedelta(minutes=3), 103, 2
        )
        self.assertAlmostEqual(state.current_cumulative_twap, 102)
        self.assertAlmostEqual(state.required_remaining_twap, 100)
        self.assertAlmostEqual(state.required_future_twap_gap, 3)
        self.assertAlmostEqual(state.resolution_pressure, 1.5)
        self.assertEqual(state.provisional_resolution, Side.UP)
        self.assertFalse(state.no_trade_reasons)

    def test_unverified_chainlink_blocks_trade(self):
        state = ResolutionStateEngine().calculate(
            self.rule, 100, [self.observation(0, 100, False)], self.start + timedelta(minutes=1), 100, 1
        )
        self.assertIn("chainlink_unverified", state.no_trade_reasons)
        self.assertIn("chainlink_state_incomplete", state.no_trade_reasons)

    def test_missing_minute_bucket_blocks_resolution_even_with_many_events(self):
        observations = [
            ChainlinkObservation(
                stream_id="btc-twap", source_timestamp=self.start + timedelta(seconds=second),
                received_timestamp=self.start + timedelta(seconds=second + 1), twap_60s=100,
                report_id=str(second), verification_status=VerificationStatus.VERIFIED,
                raw_payload_hash=str(second), market_id="m1",
            )
            for second in list(range(0, 60)) + list(range(120, 180))
        ]
        state = ResolutionStateEngine().calculate(
            self.rule, 100, observations, self.start + timedelta(minutes=3), 100, 1
        )
        self.assertIn("chainlink_observation_gap", state.no_trade_reasons)
        self.assertLess(state.resolution_confidence, 1.0)

    def test_rule_hash_changes_with_stream(self):
        other = MarketRuleVersion(**{**self.rule.__dict__, "chainlink_stream_id": "other", "resolution_rule_hash": ""})
        self.assertNotEqual(self.rule.resolution_rule_hash, other.resolution_rule_hash)

    def test_rule_hash_changes_with_fee_schedule(self):
        other = MarketRuleVersion(**{
            **self.rule.__dict__, "fee_rule_version": "fee-v2",
            "fee_schedule": {"UP": {"base_fee": 30}}, "resolution_rule_hash": "",
        })
        self.assertNotEqual(self.rule.resolution_rule_hash, other.resolution_rule_hash)

    def test_internal_label_is_reconciled_with_polymarket_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStore(str(Path(directory) / "test.sqlite3"))
            store.save_polymarket_market({
                "market_id": "m1", "slug": "btc-updown-5m-1", "condition_id": "c1",
                "start_time": self.start.isoformat(), "end_time": self.rule.end_time.isoformat(),
                "active": False, "closed": True, "up_token_id": "u", "down_token_id": "d",
                "rule_hash": "rule", "raw": {"outcomes": ["Up", "Down"], "outcomePrices": ["1", "0"]},
                "synced_at": self.rule.end_time.isoformat(),
            })
            store.save_market_label({
                "market_id": "m1", "rule_hash": "rule", "start_price": 100,
                "final_twap": 101, "outcome": "UP", "observation_count": 300,
                "finalized_at": self.rule.end_time.isoformat(),
            })
            result = store.reconcile_resolved_markets()
            self.assertEqual(result, {"checked": 1, "mismatches": 0})
            self.assertEqual(store.sync_status()["reconciled_market_labels"], 1)
            store.close()


if __name__ == "__main__": unittest.main()
