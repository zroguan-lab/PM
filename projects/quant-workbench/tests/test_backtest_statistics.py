import unittest
from datetime import datetime, timedelta, timezone

from pm_btc.backtest import FillScenario, MakerFillInput, MakerFillSimulator, MarketInterval, PurgedWalkForward
from pm_btc.statistics import PredictionRecord, clustered_metrics


class BacktestStatisticsTests(unittest.TestCase):
    def test_maker_scenarios_are_ordered(self):
        request = MakerFillInput(.5, True, False, 5, 8, 10, .01)
        simulator = MakerFillSimulator()
        optimistic = simulator.simulate(request, FillScenario.OPTIMISTIC)
        estimated = simulator.simulate(request, FillScenario.ESTIMATED)
        conservative = simulator.simulate(request, FillScenario.CONSERVATIVE)
        self.assertGreaterEqual(optimistic.filled_size, estimated.filled_size)
        self.assertGreaterEqual(estimated.filled_size, conservative.filled_size)

    def test_purged_walk_forward_separates_lookback(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        markets = [MarketInterval(str(i), start + timedelta(minutes=5*i), start + timedelta(minutes=5*(i+1))) for i in range(20)]
        folds = PurgedWalkForward(timedelta(minutes=5)).split(markets, 8, 4, 4)
        self.assertTrue(folds)
        self.assertNotIn("7", folds[0].train_market_ids)
        self.assertIn("7", folds[0].purged_market_ids)

    def test_cluster_count_is_market_count_not_prediction_count(self):
        rows = []
        for market, outcome in (("a", 1), ("b", 0)):
            rows.extend(PredictionRecord(market, .8 if outcome else .2, .6 if outcome else .4, outcome) for _ in range(300))
        metrics = clustered_metrics(rows, bootstrap_samples=50)
        self.assertEqual(metrics.independent_markets, 2)
        self.assertEqual(metrics.prediction_points, 600)
        self.assertGreater(metrics.brier_improvement, 0)

    def test_brier_point_estimate_weights_markets_equally(self):
        rows = [PredictionRecord("large", 1.0, .5, 0) for _ in range(100)]
        rows.append(PredictionRecord("small", 1.0, .5, 1))
        metrics = clustered_metrics(rows, bootstrap_samples=50)
        self.assertAlmostEqual(metrics.model_brier, .5)
        self.assertAlmostEqual(metrics.market_brier, .25)


if __name__ == "__main__": unittest.main()
