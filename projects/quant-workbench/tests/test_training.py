import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

from pm_btc.training import (
    FEATURE_SCHEMA_VERSION, MAX_FIT_POINTS_PER_MARKET, balanced_market_sample,
    fit_lightgbm_alpha, fit_logistic_alpha, fit_logistic_market,
    fit_stable_platt, log_loss, select_market_weight,
    upgrade_feature_schema,
)
from pm_btc.challenger import compare_lightgbm_challenger
from pm_btc.walkforward import walk_forward_probability_report
from pm_btc.publication import PublishedModel, publish_model
from pm_btc.diagnostics import purged_oof_diagnostics


class TrainingTests(unittest.TestCase):
    def test_market_model_weight_requires_positive_cluster_lower_bound(self):
        rows = [{
            "market_id": f"w-{index}", "market_probability_up": 0.5,
            "outcome": index % 2,
        } for index in range(40)]
        self.assertEqual(select_market_weight(rows, [0.9] * len(rows)), 0.0)
        strong = [0.9 if row["outcome"] else 0.1 for row in rows]
        self.assertEqual(select_market_weight(rows, strong), 1.0)

    def test_logistic_market_model_uses_market_probability_before_alpha(self):
        rows = []
        for index in range(40):
            probability = 0.8 if index % 2 else 0.2
            rows.append({
                "market_id": f"market-{index}",
                "prediction_timestamp": f"2026-01-01T00:{index:02d}:00+00:00",
                "market_probability_up": probability,
                "outcome": int(probability > 0.5),
                "features": {},
            })
        artifact = fit_logistic_market(rows)
        self.assertEqual(artifact.version, "logistic-market-v1")
        self.assertGreater(artifact.predict(0.8, {}), artifact.predict(0.2, {}))
        self.assertEqual(artifact.independent_markets, 40)

    def test_stable_platt_uses_only_inner_temporal_selection_and_can_improve_calibration(self):
        probabilities, outcomes, markets = [], [], []
        pattern = [1, 1, 1, 0, 1, 1, 0, 0, 1, 0]
        for index in range(40):
            high = index % 2 == 0
            probabilities.append(0.9 if high else 0.1)
            base = pattern[(index // 2) % len(pattern)]
            outcomes.append(base if high else 1 - base)
            markets.append(f"cal-{index:02d}")
        artifact = fit_stable_platt(probabilities, outcomes, markets)
        self.assertEqual(artifact.selection_method, "inner-temporal")
        self.assertLess(artifact.calibrate(0.9), 0.9)
        self.assertGreater(artifact.calibrate(0.1), 0.1)

    def test_fit_sampling_caps_correlated_seconds_per_market_deterministically(self):
        rows = [
            {
                "market_id": market,
                "prediction_timestamp": f"2026-01-01T00:00:{index:02d}+00:00",
            }
            for market in ("a", "b") for index in range(60)
        ]
        first = balanced_market_sample(rows)
        second = balanced_market_sample(reversed(rows))
        self.assertEqual(len(first), 2 * MAX_FIT_POINTS_PER_MARKET)
        self.assertEqual(
            [(row["market_id"], row["prediction_timestamp"]) for row in first],
            [(row["market_id"], row["prediction_timestamp"]) for row in second],
        )

    def test_legacy_feature_rows_are_deterministically_upgraded(self):
        upgraded = upgrade_feature_schema({
            "feature_schema_version": "endpoint-twap-v2-regime-v1",
            "chainlink_start_price": 100_000.0,
            "current_cumulative_twap": 100_020.0,
            "spot_mid": 100_030.0,
            "required_future_twap_gap": 30.0,
            "resolution_pressure": 1.5,
            "remaining_duration": 30.0,
        })
        self.assertEqual(upgraded["feature_schema_version"], FEATURE_SCHEMA_VERSION)
        self.assertAlmostEqual(upgraded["gap_bps"], 3.0)
        self.assertAlmostEqual(upgraded["remaining_twap_zscore"], 1.0)
        self.assertAlmostEqual(upgraded["chainlink_binance_divergence_bps"], 0.99980004)

    def test_lightgbm_challenger_uses_purged_oof_evaluation(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        rows = []
        for index in range(42):
            outcome = index % 2
            market_start = start + timedelta(minutes=5 * index)
            rows.append({
                "market_id": f"lgb{index}",
                "prediction_timestamp": (market_start + timedelta(minutes=2)).isoformat(),
                "start_time": market_start.isoformat(),
                "end_time": (market_start + timedelta(minutes=5)).isoformat(),
                "market_probability_up": 0.5, "outcome": outcome,
                "features": {"resolution_pressure": 3.0 if outcome else -3.0},
            })
        artifact = fit_lightgbm_alpha(rows, feature_names=("resolution_pressure",))
        self.assertGreater(
            artifact.predict(0.5, {"resolution_pressure": 3.0}),
            artifact.predict(0.5, {"resolution_pressure": -3.0}),
        )
        report = compare_lightgbm_challenger(
            rows, train_count=12, calibration_count=6, validation_count=6,
        )
        self.assertIn("lightgbm", report)
        self.assertIn("logistic", report)
        self.assertIsInstance(report["lightgbm_beats_logistic"], bool)

    def test_logistic_alpha_learns_residual_signal(self):
        rows = []
        for index in range(20):
            outcome = int(index >= 10)
            rows.append({
                "market_id": f"m{index}", "prediction_timestamp": f"2026-01-01T00:{index:02d}:00+00:00",
                "market_probability_up": 0.5, "outcome": outcome,
                "features": {"resolution_pressure": 2.0 if outcome else -2.0},
            })
        artifact = fit_logistic_alpha(rows, feature_names=("resolution_pressure",), iterations=500)
        self.assertEqual(artifact.independent_markets, 20)
        self.assertGreater(artifact.predict(0.5, {"resolution_pressure": 2}), 0.8)
        self.assertLess(artifact.predict(0.5, {"resolution_pressure": -2}), 0.2)
        self.assertLess(log_loss(rows, artifact), 0.3)
        self.assertEqual(len(artifact.artifact_hash), 64)

    def test_purged_walk_forward_reports_probability_edge(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        rows = []
        for index in range(42):
            outcome = index % 2
            market_start = start + timedelta(minutes=5 * index)
            rows.append({
                "market_id": f"m{index}", "prediction_timestamp": (market_start + timedelta(minutes=2)).isoformat(),
                "start_time": market_start.isoformat(), "end_time": (market_start + timedelta(minutes=5)).isoformat(),
                "market_probability_up": 0.5, "outcome": outcome,
                "features": {"resolution_pressure": 2.0 if outcome else -2.0},
            })
        report = walk_forward_probability_report(
            rows, train_count=12, calibration_count=6, validation_count=6,
            feature_names=("resolution_pressure",),
        )
        self.assertGreaterEqual(len(report.folds), 1)
        self.assertGreater(report.mean_probability_edge, 0)
        self.assertLess(report.mean_model_brier, report.mean_market_brier)
        self.assertGreaterEqual(report.mean_market_model_weight, 0.0)
        self.assertLessEqual(report.mean_market_model_weight, 1.0)
        self.assertTrue(all(fold.purged_markets >= 1 for fold in report.folds))
        self.assertIn("121-300s", report.raw_by_time_remaining)

        published = publish_model(
            rows, train_count=12, calibration_count=6, validation_count=6,
            minimum_markets=30, feature_names=("resolution_pressure",),
        )
        high = published.predict(0.5, {"resolution_pressure": 2.0})
        low = published.predict(0.5, {"resolution_pressure": -2.0})
        self.assertGreater(high["p_calibrated"], low["p_calibrated"])
        self.assertLessEqual(high["p_lower"], high["p_calibrated"])
        self.assertGreaterEqual(high["p_upper"], high["p_calibrated"])
        self.assertEqual(len(published.artifact_hash), 64)
        self.assertIsNotNone(published.market)
        self.assertIn("market_model_probability", high)
        with tempfile.TemporaryDirectory() as temporary:
            path = str(Path(temporary) / "published.json")
            published.save(path)
            loaded = PublishedModel.load(path)
        self.assertEqual(loaded.artifact_hash, published.artifact_hash)
        self.assertEqual(loaded.predict(0.5, {"resolution_pressure": 2.0})["p_calibrated"], high["p_calibrated"])
        realtime_named = replace(
            published, alpha_kind="realtime-logistic", artifact_hash="",
        )
        self.assertGreater(
            realtime_named.predict(0.5, {"resolution_pressure": 2.0})["p_calibrated"],
            realtime_named.predict(0.5, {"resolution_pressure": -2.0})["p_calibrated"],
        )

        lightgbm_published = publish_model(
            rows, train_count=12, calibration_count=6, validation_count=6,
            minimum_markets=30, feature_names=("resolution_pressure",),
            alpha_fitter=fit_lightgbm_alpha, alpha_kind="lightgbm",
        )
        self.assertEqual(lightgbm_published.alpha_kind, "lightgbm")
        lightgbm_high = lightgbm_published.predict(0.5, {"resolution_pressure": 2.0})
        lightgbm_low = lightgbm_published.predict(0.5, {"resolution_pressure": -2.0})
        self.assertGreater(lightgbm_high["p_calibrated"], lightgbm_low["p_calibrated"])
        with tempfile.TemporaryDirectory() as temporary:
            path = str(Path(temporary) / "published-lightgbm.json")
            lightgbm_published.save(path)
            loaded_lightgbm = PublishedModel.load(path)
        self.assertEqual(loaded_lightgbm.alpha_kind, "lightgbm")
        self.assertAlmostEqual(
            loaded_lightgbm.predict(0.5, {"resolution_pressure": 2.0})["p_calibrated"],
            lightgbm_high["p_calibrated"],
        )
        self.assertIn("selected_probability_edge", loaded_lightgbm.validation)

        diagnostics = purged_oof_diagnostics(
            rows, train_count=12, calibration_count=6, validation_count=6,
            feature_names=("resolution_pressure",),
        )
        self.assertGreater(diagnostics["overall"]["brier_improvement"], 0)
        self.assertIn("121-300s", diagnostics["by_time_remaining"])

        scoped_rows = [{
            **row,
            "prediction_timestamp": (datetime.fromisoformat(row["end_time"]) - timedelta(seconds=10)).isoformat(),
        } for row in rows]
        scoped = publish_model(
            scoped_rows, train_count=12, calibration_count=6, validation_count=6,
            minimum_markets=30, minimum_validation_markets=6,
            time_scope="0-30s", feature_names=("resolution_pressure",),
        )
        self.assertEqual(scoped.time_scope, "0-30s")


if __name__ == "__main__":
    unittest.main()
