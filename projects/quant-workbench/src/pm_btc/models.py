from __future__ import annotations

from dataclasses import dataclass
from math import exp, log, sqrt
from statistics import NormalDist
from typing import Iterable, Mapping, Protocol

from .domain import OrderBook, ProbabilityEstimate, Regime


def clamp_probability(value: float, epsilon: float = 1e-6) -> float:
    return min(1.0 - epsilon, max(epsilon, value))


def logit(value: float) -> float:
    p = clamp_probability(value)
    return log(p / (1.0 - p))


def sigmoid(value: float) -> float:
    if value >= 0:
        z = exp(-value)
        return 1.0 / (1.0 + z)
    z = exp(value)
    return z / (1.0 + z)


class AlphaModel(Protocol):
    version: str

    def predict_logit_delta(self, features: Mapping[str, float]) -> float: ...


@dataclass
class LogisticAlphaModel:
    coefficients: Mapping[str, float]
    intercept: float = 0.0
    version: str = "logistic-alpha-v1"

    def predict_logit_delta(self, features: Mapping[str, float]) -> float:
        return self.intercept + sum(self.coefficients.get(name, 0.0) * value for name, value in features.items())


@dataclass
class PlattCalibrator:
    slope: float = 1.0
    intercept: float = 0.0

    def calibrate(self, probability: float) -> float:
        return clamp_probability(sigmoid(self.slope * logit(probability) + self.intercept))


class MarketModel:
    """Computes an executable-price-aware market baseline from both outcome books."""

    def probability_up(self, up_book: OrderBook, down_book: OrderBook) -> float:
        up = up_book.microprice
        down = down_book.microprice
        if up is None or down is None:
            raise ValueError("both outcome books require two-sided liquidity")
        total = up + down
        if total <= 0:
            raise ValueError("invalid outcome prices")
        return clamp_probability(up / total)


@dataclass
class ClusteredUncertainty:
    """Regime-aware normal approximation fitted from market-level residuals."""

    global_standard_error: float
    regime_standard_errors: Mapping[str, float]
    confidence: float = 0.90

    @classmethod
    def fit(
        cls,
        residuals_by_market: Mapping[str, Iterable[float]],
        regime_by_market: Mapping[str, str] | None = None,
        confidence: float = 0.90,
    ) -> "ClusteredUncertainty":
        market_means = {
            market: sum(values_list) / len(values_list)
            for market, values in residuals_by_market.items()
            if (values_list := list(values))
        }
        if len(market_means) < 2:
            return cls(global_standard_error=0.15, regime_standard_errors={}, confidence=confidence)
        values = list(market_means.values())
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
        global_se = max(sqrt(variance), 0.01)
        regime_errors: dict[str, float] = {}
        if regime_by_market:
            groups: dict[str, list[float]] = {}
            for market, value in market_means.items():
                groups.setdefault(regime_by_market.get(market, "unknown"), []).append(value)
            for key, group in groups.items():
                if len(group) >= 20:
                    group_mean = sum(group) / len(group)
                    group_var = sum((value - group_mean) ** 2 for value in group) / (len(group) - 1)
                    regime_errors[key] = max(sqrt(group_var), 0.01)
        return cls(global_standard_error=global_se, regime_standard_errors=regime_errors, confidence=confidence)

    def bounds(self, probability: float, regime: Regime) -> tuple[float, float]:
        standard_error = self.regime_standard_errors.get(regime.key, self.global_standard_error * 1.25)
        z = NormalDist().inv_cdf(self.confidence)
        return (
            clamp_probability(probability - z * standard_error),
            clamp_probability(probability + z * standard_error),
        )


@dataclass
class MispricingEnsemble:
    market_model: MarketModel
    alpha_model: AlphaModel
    calibrator: PlattCalibrator
    uncertainty: ClusteredUncertainty
    meta_time_coefficient: float = 0.0
    regime_adjustments: Mapping[str, float] | None = None

    def predict(
        self,
        up_book: OrderBook,
        down_book: OrderBook,
        features: Mapping[str, float],
        time_remaining_fraction: float,
        regime: Regime,
        ood_risk: float,
    ) -> ProbabilityEstimate:
        pm = self.market_model.probability_up(up_book, down_book)
        delta = self.alpha_model.predict_logit_delta(features)
        regime_delta = (self.regime_adjustments or {}).get(regime.key, 0.0)
        raw = sigmoid(logit(pm) + delta + self.meta_time_coefficient * time_remaining_fraction + regime_delta)
        calibrated = self.calibrator.calibrate(raw)
        lower, upper = self.uncertainty.bounds(calibrated, regime)
        confidence = max(0.0, min(1.0, 1.0 - (upper - lower) - ood_risk))
        return ProbabilityEstimate(
            market_probability=pm,
            alpha_delta=calibrated - pm,
            p_raw=raw,
            p_calibrated=calibrated,
            p_lower=lower,
            p_upper=upper,
            confidence=confidence,
            ood_risk=ood_risk,
            model_version=self.alpha_model.version,
        )

