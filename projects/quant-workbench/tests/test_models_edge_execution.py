import unittest
from datetime import datetime, timezone

from pm_btc.config import Settings
from pm_btc.domain import BookLevel, ExecutionDecision, ExecutionKind, OrderBook, Regime, ResolutionState, Side, VerificationStatus
from pm_btc.edge import EdgeCalculator, polymarket_fee_per_share, quote_taker
from pm_btc.execution import ExecutionPolicy, MakerAssumptions
from pm_btc.models import ClusteredUncertainty, LogisticAlphaModel, MarketModel, MispricingEnsemble, PlattCalibrator
from pm_btc.ledgers import RealisticPaperLedger


def book(token, bid, ask, bid_size=100, ask_size=100):
    return OrderBook(token, (BookLevel(bid, bid_size),), (BookLevel(ask, ask_size),), datetime.now(timezone.utc))


class ModelEdgeExecutionTests(unittest.TestCase):
    def setUp(self):
        self.regime = Regime("normal", "flat", "normal", "us", "tight")
        self.ensemble = MispricingEnsemble(
            MarketModel(), LogisticAlphaModel({"pressure": 0.15}), PlattCalibrator(),
            ClusteredUncertainty(0.01, {self.regime.key: 0.01}),
        )

    def test_market_model_uses_both_books(self):
        probability = MarketModel().probability_up(book("u", .54, .56), book("d", .44, .46))
        self.assertAlmostEqual(probability, .55, places=2)

    def test_ensemble_adds_alpha_on_logit_scale(self):
        result = self.ensemble.predict(book("u", .49, .51), book("d", .49, .51), {"pressure": 2}, .5, self.regime, .01)
        self.assertGreater(result.p_calibrated, result.market_probability)
        self.assertLess(result.p_lower, result.p_calibrated)

    def test_taker_uses_depth_not_midpoint(self):
        depth = OrderBook("u", (BookLevel(.50, 10),), (BookLevel(.55, 1), BookLevel(.60, 2)), datetime.now(timezone.utc))
        quote = quote_taker(depth, 3)
        self.assertAlmostEqual(quote.average_price, (0.55 + 1.2) / 3)

    def test_crypto_fee_uses_probability_curve_not_base_fee_as_flat_percent(self):
        self.assertEqual(polymarket_fee_per_share(.5, .07), .0175)
        self.assertEqual(polymarket_fee_per_share(.1, .07), .0063)

    def test_dynamic_policy_prefers_higher_ev_and_can_no_trade(self):
        probability = self.ensemble.predict(book("u", .49, .51), book("d", .49, .51), {"pressure": 3}, .5, self.regime, 0)
        taker = EdgeCalculator().calculate_taker(Side.UP, probability, book("u", .49, .51), 1, .07, .005, .002)
        resolution = ResolutionState("m", 100, 18000, 100, 120, 100, 1, 1, Side.UP, 1, .6, False)
        decision = ExecutionPolicy(Settings()).choose(
            Side.UP, probability, taker, MakerAssumptions(.50, .9, .001, .001, .001),
            resolution, 1, 0, 1, True, True,
        )
        self.assertIn(decision.kind.value, ("MAKER", "TAKER"))
        blocked = ExecutionPolicy(Settings()).choose(
            Side.UP, probability, taker, MakerAssumptions(.50, .9, .001, .001, .001),
            resolution, 1, 4, 1, True, True,
        )
        self.assertEqual(blocked.kind.value, "NO_TRADE")
        self.assertIn("data_stale", blocked.reasons)

    def test_paper_ledger_charges_share_cost_not_share_count(self):
        ledger = RealisticPaperLedger(10)
        decision = ExecutionDecision(ExecutionKind.TAKER, Side.UP, .50, 4, .05, .05)
        entry = ledger.record_fill("m", datetime.now(timezone.utc), decision, 1.0)
        self.assertEqual(entry.filled, 4)
        self.assertEqual(entry.notional, 2)
        self.assertEqual(ledger.cash, 8)
        pnl = ledger.settle(0, won=True)
        self.assertEqual(pnl, 2)
        self.assertEqual(ledger.cash, 12)


if __name__ == "__main__": unittest.main()
