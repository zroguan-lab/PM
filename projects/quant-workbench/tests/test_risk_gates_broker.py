import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from pm_btc.broker import ReadOnlyOfficialPolymarketBroker
from pm_btc.gates import GateEvidence, live_gate, research_gate
from pm_btc.risk import KillReason, StatisticalKillSwitch, StatisticalSnapshot
from pm_btc.risk_runtime import RiskMonitorRuntime
from pm_btc.config import Settings
from pm_btc.storage import SQLiteStore
from pm_btc.model_runtime import AutoModelRuntime
from pm_btc.domain import ChainlinkObservation, VerificationStatus
from pm_btc.training import REALTIME_ALPHA_FEATURES, REALTIME_FEATURE_VERSION


class RiskGateBrokerTests(unittest.TestCase):
    def test_kill_switch_checks_statistics(self):
        reasons = StatisticalKillSwitch().evaluate(StatisticalSnapshot(rolling_ev_lower_bound=-.01, feature_psi=.3))
        self.assertIn(KillReason.ROLLING_EV, reasons)
        self.assertIn(KillReason.FEATURE_DRIFT, reasons)

    def test_two_level_gates(self):
        evidence = GateEvidence(60, 2000, 2000, .18, .21, .01, .01, .005, 10, False, .5, 7, True, True)
        self.assertTrue(research_gate(evidence).passed)
        self.assertTrue(live_gate(evidence).passed)

    def test_official_broker_is_read_only_without_live_client(self):
        broker = ReadOnlyOfficialPolymarketBroker()
        eligibility = asyncio.run(broker.check_eligibility())
        self.assertTrue(eligibility.read_only)
        with self.assertRaises(PermissionError):
            asyncio.run(broker.place_limit_order("token", None, .5, 1))

    def test_readiness_monitor_fails_closed_and_persists_state(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                database_path=str(Path(directory) / "test.sqlite3"),
                published_model_path=str(Path(directory) / "missing-model.json"),
            )
            store = SQLiteStore(settings.database_path)
            result = RiskMonitorRuntime(settings, store).evaluate_once()
            self.assertEqual(result["mode"], "DISARMED")
            self.assertIn("published_model_missing", result["reasons"])
            self.assertIn("research_gate_labels_incomplete", result["reasons"])
            self.assertIn("binance_ws_spot_unavailable", result["reasons"])
            self.assertEqual(store.get_system_state()["mode"], "DISARMED")
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM statistical_risk_snapshots").fetchone()[0], 1)
            observed = datetime.now(timezone.utc) - timedelta(seconds=20)
            store.save_chainlink(ChainlinkObservation(
                stream_id="test", source_timestamp=observed,
                received_timestamp=observed, twap_60s=100,
                report_id="heartbeat", verification_status=VerificationStatus.VERIFIED,
                raw_payload_hash="heartbeat-hash", market_id="m-heartbeat",
            ))
            result = RiskMonitorRuntime(settings, store).evaluate_once()
            self.assertNotIn("chainlink_feed_stale", result["reasons"])
            store.connection.execute(
                """INSERT INTO resolution_reconciliations VALUES(
                    'mismatch', 'UP', 'DOWN', 0, '2026-01-01T00:00:00+00:00', 'hash'
                )"""
            )
            store.connection.commit()
            result = RiskMonitorRuntime(settings, store).evaluate_once()
            self.assertIn("statistical_kill:INTEGRITY", result["reasons"])
            store.close()

    def test_auto_model_waits_for_independent_markets(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                database_path=str(Path(directory) / "test.sqlite3"),
                published_model_path=str(Path(directory) / "model.json"),
                auto_publish_min_markets=30,
            )
            store = SQLiteStore(settings.database_path)
            result = AutoModelRuntime(settings, store).evaluate_once()
            self.assertEqual(result["status"], "WAITING_FOR_MARKETS")
            self.assertEqual(result["independent_markets"], 0)
            store.set_last_model_attempt(30)
            self.assertEqual(AutoModelRuntime(settings, store)._last_attempted_markets, 30)
            store.close()

    def test_auto_model_can_promote_lightgbm_only_after_logistic_rejections(self):
        class FakeStore:
            def __init__(self):
                self.last_attempt = 0
                self.events = []

            def get_last_model_attempt(self): return self.last_attempt
            def set_last_model_attempt(self, value): self.last_attempt = value
            def audit(self, event_type, payload): self.events.append((event_type, payload))
            def alpha_training_rows(self):
                return [{
                    "market_id": f"m{index}",
                    "prediction_timestamp": "2026-01-01T00:04:50+00:00",
                    "start_time": "2026-01-01T00:00:00+00:00",
                    "end_time": "2026-01-01T00:05:00+00:00",
                    "features": {}, "market_probability_up": .5, "outcome": index % 2,
                } for index in range(40)]

        class FakeArtifact:
            independent_markets = 40
            alpha_kind = "lightgbm"
            time_scope = None
            calibration_method = "identity"
            artifact_hash = "candidate-hash"
            validation = {"selected_probability_edge": .01, "selected_calibration_error": .02}

            def save(self, path): Path(path).write_text("candidate", encoding="utf-8")

        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                database_path=str(Path(directory) / "test.sqlite3"),
                published_model_path=str(Path(directory) / "model.json"),
                auto_publish_min_markets=30,
            )
            store = FakeStore()
            with patch(
                "pm_btc.model_runtime.publish_model",
                side_effect=[
                    ValueError("logistic global"), ValueError("logistic scoped"),
                    FakeArtifact(), ValueError("lightgbm scoped"),
                ],
            ) as mocked_publish:
                result = AutoModelRuntime(settings, store).evaluate_once()
            self.assertEqual(result["status"], "PUBLISHED")
            self.assertEqual(result["alpha_kind"], "lightgbm")
            self.assertEqual(mocked_publish.call_count, 4)
            self.assertEqual(mocked_publish.call_args_list[2].kwargs["alpha_kind"], "lightgbm")
            self.assertTrue(any(event == "auto_lightgbm_model_selected" for event, _ in store.events))

    def test_auto_model_uses_realtime_rows_only_after_independent_market_gate(self):
        class FakeStore:
            def __init__(self, rows):
                self.rows = rows
                self.last_attempt = 0
                self.events = []

            def get_last_model_attempt(self): return self.last_attempt
            def set_last_model_attempt(self, value): self.last_attempt = value
            def audit(self, event_type, payload): self.events.append((event_type, payload))
            def alpha_training_rows(self): return self.rows

        class RealtimeArtifact:
            independent_markets = 40
            alpha_kind = "realtime-logistic"
            time_scope = None
            calibration_method = "platt"
            artifact_hash = "realtime-hash"
            validation = {"selected_probability_edge": .02}

            def save(self, path): Path(path).write_text("realtime", encoding="utf-8")

        feature_values = {name: 0.0 for name in REALTIME_ALPHA_FEATURES}
        feature_values["realtime_feature_version"] = REALTIME_FEATURE_VERSION
        rows = [{
            "market_id": f"m{index}",
            "prediction_timestamp": "2026-01-01T00:04:50+00:00",
            "start_time": "2026-01-01T00:00:00+00:00",
            "end_time": "2026-01-01T00:05:00+00:00",
            "features": dict(feature_values), "market_probability_up": .5,
            "outcome": index % 2,
        } for index in range(40)]
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                published_model_path=str(Path(directory) / "model.json"),
                auto_publish_min_markets=30,
            )
            store = FakeStore(rows)
            with patch(
                "pm_btc.model_runtime.publish_model",
                side_effect=[ValueError("base-1"), ValueError("base-2"),
                             ValueError("base-3"), ValueError("base-4"), RealtimeArtifact()],
            ) as mocked_publish:
                result = AutoModelRuntime(settings, store).evaluate_once()
        self.assertEqual(result["status"], "PUBLISHED")
        self.assertEqual(result["alpha_kind"], "realtime-logistic")
        self.assertEqual(mocked_publish.call_count, 5)
        self.assertEqual(mocked_publish.call_args_list[4].kwargs["rows"], rows)
        self.assertEqual(
            mocked_publish.call_args_list[4].kwargs["feature_names"], REALTIME_ALPHA_FEATURES
        )
        self.assertTrue(any(event == "auto_realtime_model_selected" for event, _ in store.events))

    def test_auto_model_evaluates_non_final_time_buckets(self):
        class FakeStore:
            def __init__(self):
                self.last_attempt = 0
                self.events = []

            def get_last_model_attempt(self): return self.last_attempt
            def set_last_model_attempt(self, value): self.last_attempt = value
            def audit(self, event_type, payload): self.events.append((event_type, payload))
            def alpha_training_rows(self):
                return [{
                    "market_id": f"m{index}",
                    "prediction_timestamp": "2026-01-01T00:04:20+00:00",
                    "start_time": "2026-01-01T00:00:00+00:00",
                    "end_time": "2026-01-01T00:05:00+00:00",
                    "features": {}, "market_probability_up": .5, "outcome": index % 2,
                } for index in range(40)]

        class ScopedArtifact:
            independent_markets = 40
            alpha_kind = "logistic"
            time_scope = "31-60s"
            calibration_method = "identity"
            artifact_hash = "scoped-hash"
            validation = {
                "selected_probability_edge": .01,
                "selected_calibration_error": .02,
            }

            def save(self, path): Path(path).write_text("candidate", encoding="utf-8")

        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                published_model_path=str(Path(directory) / "model.json"),
                auto_publish_min_markets=30,
            )
            store = FakeStore()
            with patch(
                "pm_btc.model_runtime.publish_model",
                side_effect=[ValueError("global rejected"), ScopedArtifact()],
            ) as mocked_publish:
                result = AutoModelRuntime(settings, store).evaluate_once()

        self.assertEqual(result["status"], "PUBLISHED")
        self.assertEqual(mocked_publish.call_count, 2)
        self.assertEqual(mocked_publish.call_args_list[1].kwargs["time_scope"], "31-60s")
        self.assertTrue(any(event == "auto_scoped_model_selected" for event, _ in store.events))


if __name__ == "__main__": unittest.main()
