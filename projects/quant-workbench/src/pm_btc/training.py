from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from functools import cached_property
import json
from math import log, sqrt
from pathlib import Path
from statistics import mean, pstdev
from typing import Iterable

from .models import clamp_probability, logit, sigmoid


FEATURE_SCHEMA_VERSION = "endpoint-twap-v2-regime-v2"
LEGACY_FEATURE_SCHEMA_VERSIONS = ("endpoint-twap-v2-regime-v1",)
REALTIME_FEATURE_VERSION = "orderflow-ws-v1"
MAX_FIT_POINTS_PER_MARKET = 24

REQUIRED_RESOLUTION_FEATURES = (
    "resolution_pressure", "required_future_twap_gap", "fraction_window_observed",
)

DEFAULT_ALPHA_FEATURES = (
    "resolution_pressure", "gap_bps", "remaining_twap_zscore",
    "chainlink_binance_divergence_bps",
    "fraction_window_observed", "remaining_duration",
    "basis_bps", "spot_imbalance", "futures_imbalance", "funding_rate",
)

MARKET_BASELINE_FEATURES = (
    "remaining_duration", "book_spread_max", "book_depth_top5",
    "liquidity_regime_code", "spread_regime_code", "time_of_day_regime_code",
)

EXTENDED_ALPHA_FEATURES = DEFAULT_ALPHA_FEATURES + (
    "required_future_twap_gap", "distance_to_lock",
    "rolling_volatility", "rolling_trend", "book_depth_top5", "book_spread_max",
    "volatility_regime_code", "trend_regime_code", "liquidity_regime_code",
    "time_of_day_regime_code", "spread_regime_code",
)

REALTIME_ALPHA_FEATURES = EXTENDED_ALPHA_FEATURES + (
    "polymarket_trade_count_60s", "polymarket_trade_volume_60s",
    "polymarket_trade_imbalance_60s",
    "binance_spot_trade_count_60s", "binance_spot_trade_notional_60s",
    "binance_spot_trade_imbalance_60s",
    "binance_futures_trade_count_60s", "binance_futures_trade_notional_60s",
    "binance_futures_trade_imbalance_60s",
    "binance_spot_ws_spread_bps", "binance_spot_ws_top_imbalance",
    "binance_spot_ws_depth_imbalance",
    "binance_futures_ws_spread_bps", "binance_futures_ws_top_imbalance",
    "binance_futures_ws_depth_imbalance", "binance_ws_basis_bps",
)


def _evenly_spaced_indices(length: int, limit: int) -> list[int]:
    if length <= limit:
        return list(range(length))
    if limit <= 1:
        return [length - 1]
    return sorted({round(index * (length - 1) / (limit - 1)) for index in range(limit)})


def balanced_market_sample(
    rows: Iterable[dict], limit: int = MAX_FIT_POINTS_PER_MARKET,
) -> list[dict]:
    """Keep markets equally represented without fitting every correlated second."""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(str(row["market_id"]), []).append(row)
    sampled: list[dict] = []
    for market in sorted(groups):
        market_rows = groups[market]
        ordered = sorted(market_rows, key=lambda row: str(row.get("prediction_timestamp", "")))
        sampled.extend(ordered[index] for index in _evenly_spaced_indices(len(ordered), limit))
    return sampled


def upgrade_feature_schema(features: dict) -> dict:
    values = dict(features)
    source_version = values.get("feature_schema_version")
    if source_version == FEATURE_SCHEMA_VERSION:
        return values
    if source_version not in LEGACY_FEATURE_SCHEMA_VERSIONS:
        return values
    start = float(values.get("chainlink_start_price") or 0.0)
    current = float(values.get("current_cumulative_twap") or start)
    proxy = float(values.get("spot_mid") or current)
    gap = float(values.get("required_future_twap_gap") or (proxy - start))
    pressure = float(values.get("resolution_pressure") or 0.0)
    inferred_std = abs(gap / pressure) if abs(pressure) > 1e-9 else 0.0
    if inferred_std <= 0:
        inferred_std = max(abs(proxy) * abs(float(values.get("rolling_volatility") or 0.0)), 1.0)
    values.update({
        "source_feature_schema_version": source_version,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "gap_bps": gap / start * 10_000 if start > 0 else 0.0,
        "expected_remaining_price_std": inferred_std,
        "remaining_twap_zscore": (current - start) / inferred_std,
        "distance_to_lock": abs(current - start) / inferred_std,
        "chainlink_binance_divergence": proxy - current,
        "chainlink_binance_divergence_bps": (proxy - current) / current * 10_000 if current > 0 else 0.0,
    })
    return values


def shrink_alpha_probability(market_probability: float, alpha_probability: float, weight: float) -> float:
    delta = logit(alpha_probability) - logit(market_probability)
    return clamp_probability(sigmoid(logit(market_probability) + max(0.0, min(1.0, weight)) * delta))


def select_alpha_weight(
    rows: Iterable[dict], alpha_probabilities: Iterable[float],
    candidates: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0),
) -> float:
    data, predictions = list(rows), list(alpha_probabilities)
    if len(data) != len(predictions) or not data:
        raise ValueError("aligned alpha-weight calibration samples are required")
    by_market: dict[str, list[tuple[dict, float]]] = {}
    for row, prediction in zip(data, predictions):
        by_market.setdefault(row["market_id"], []).append((row, prediction))

    def score(weight: float) -> float:
        return mean(mean(
            (shrink_alpha_probability(float(row["market_probability_up"]), prediction, weight) - int(row["outcome"])) ** 2
            for row, prediction in group
        ) for group in by_market.values())

    return min(candidates, key=lambda weight: (score(weight), weight))


def select_market_weight(
    rows: Iterable[dict], market_probabilities: Iterable[float],
    candidates: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0),
) -> float:
    """Adopt a trained Market Model only with positive 90% market-cluster LCB."""
    data, predictions = list(rows), list(market_probabilities)
    if len(data) != len(predictions) or not data:
        raise ValueError("aligned market-model calibration samples are required")
    groups: dict[str, list[tuple[dict, float]]] = {}
    for row, prediction in zip(data, predictions):
        groups.setdefault(row["market_id"], []).append((row, prediction))

    def market_scores(weight: float) -> dict[str, float]:
        return {
            market: mean(
                (
                    shrink_alpha_probability(
                        float(row["market_probability_up"]), prediction, weight,
                    ) - int(row["outcome"])
                ) ** 2
                for row, prediction in group
            )
            for market, group in groups.items()
        }

    baseline = market_scores(0.0)
    eligible: list[tuple[float, float]] = []
    for weight in candidates:
        if weight <= 0:
            continue
        candidate = market_scores(weight)
        improvements = [
            baseline[market] - candidate[market] for market in baseline
        ]
        improvement = mean(improvements)
        standard_error = (
            pstdev(improvements) / sqrt(len(improvements))
            if len(improvements) > 1 else float("inf")
        )
        lower_bound = improvement - 1.2815515655446004 * standard_error
        if lower_bound > 0:
            eligible.append((improvement, weight))
    return max(eligible, default=(0.0, 0.0), key=lambda item: (item[0], -item[1]))[1]


@dataclass(frozen=True)
class LogisticAlphaArtifact:
    version: str
    feature_names: tuple[str, ...]
    coefficients: tuple[float, ...]
    intercept: float
    feature_means: tuple[float, ...]
    feature_stds: tuple[float, ...]
    independent_markets: int
    training_points: int
    training_start: str
    training_end: str
    artifact_hash: str = ""

    def __post_init__(self) -> None:
        if not self.artifact_hash:
            payload = {key: value for key, value in asdict(self).items() if key != "artifact_hash"}
            object.__setattr__(self, "artifact_hash", sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest())

    def predict(self, market_probability: float, features: dict[str, float]) -> float:
        values = [
            (float(features.get(name, center)) - center) / scale
            for name, center, scale in zip(self.feature_names, self.feature_means, self.feature_stds)
        ]
        delta = self.intercept + sum(coefficient * value for coefficient, value in zip(self.coefficients, values))
        return clamp_probability(sigmoid(logit(market_probability) + delta))

    def save(self, path: str) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(asdict(self), indent=2, sort_keys=True), encoding="utf-8")


@dataclass(frozen=True)
class LogisticMarketArtifact:
    version: str
    feature_names: tuple[str, ...]
    base_logit_coefficient: float
    coefficients: tuple[float, ...]
    intercept: float
    feature_means: tuple[float, ...]
    feature_stds: tuple[float, ...]
    independent_markets: int
    training_points: int

    def predict(self, market_probability: float, features: dict[str, float]) -> float:
        values = [
            (float(features.get(name, center) or 0.0) - center) / scale
            for name, center, scale in zip(
                self.feature_names, self.feature_means, self.feature_stds,
            )
        ]
        score = (
            self.intercept + self.base_logit_coefficient * logit(market_probability)
            + sum(coefficient * value for coefficient, value in zip(self.coefficients, values))
        )
        return clamp_probability(sigmoid(score))


@dataclass(frozen=True)
class PlattArtifact:
    slope: float
    intercept: float
    independent_markets: int
    regularization: float = 0.001
    intercept_regularization: float = 0.0
    selection_method: str = "fixed"

    def calibrate(self, probability: float) -> float:
        return clamp_probability(sigmoid(self.slope * logit(probability) + self.intercept))


@dataclass(frozen=True)
class LightGBMAlphaArtifact:
    version: str
    feature_names: tuple[str, ...]
    model_text: str
    feature_means: tuple[float, ...]
    feature_stds: tuple[float, ...]
    independent_markets: int
    training_points: int

    @cached_property
    def booster(self):
        import lightgbm as lgb
        return lgb.Booster(model_str=self.model_text)

    def predict(self, market_probability: float, features: dict[str, float]) -> float:
        return self.predict_many([{"market_probability_up": market_probability, "features": features}])[0]

    def predict_many(self, rows: Iterable[dict]) -> list[float]:
        import numpy as np
        data = list(rows)
        matrix = np.asarray([
            [float(row["features"].get(name, 0.0) or 0.0) for name in self.feature_names]
            for row in data
        ], dtype=float)
        deltas = self.booster.predict(matrix, raw_score=True, num_threads=1)
        return [
            clamp_probability(sigmoid(logit(float(row["market_probability_up"])) + float(delta)))
            for row, delta in zip(data, deltas)
        ]


def fit_logistic_market(
    rows: Iterable[dict], feature_names: tuple[str, ...] = MARKET_BASELINE_FEATURES,
    learning_rate: float = 0.03, iterations: int = 800, l2: float = 0.02,
) -> LogisticMarketArtifact:
    """Learn the probability expressed by market structure before external alpha."""
    import numpy as np

    data = balanced_market_sample(rows)
    markets = sorted({row["market_id"] for row in data})
    if len(markets) < 2:
        raise ValueError("at least two independent markets are required for Market Model")
    counts = {market: sum(row["market_id"] == market for row in data) for market in markets}
    columns = [
        [float(row["features"].get(name, 0.0) or 0.0) for row in data]
        for name in feature_names
    ]
    centers = [mean(column) for column in columns]
    scales = [max(pstdev(column), 1e-9) for column in columns]
    matrix = np.asarray([
        [(columns[j][i] - centers[j]) / scales[j] for j in range(len(feature_names))]
        for i in range(len(data))
    ], dtype=float)
    coefficients = np.zeros(len(feature_names), dtype=float)
    weights = np.asarray([1.0 / counts[row["market_id"]] for row in data], dtype=float)
    outcomes = np.asarray([int(row["outcome"]) for row in data], dtype=float)
    market_logits = np.asarray([
        logit(float(row["market_probability_up"])) for row in data
    ], dtype=float)
    base_logit_coefficient, intercept = 1.0, 0.0
    total_weight = float(len(markets))
    for _ in range(iterations):
        scores = intercept + base_logit_coefficient * market_logits + matrix @ coefficients
        probabilities = 1.0 / (1.0 + np.exp(-np.clip(scores, -700.0, 700.0)))
        weighted_errors = weights * (probabilities - outcomes)
        grad_intercept = float(weighted_errors.sum())
        grad_base = float(weighted_errors @ market_logits)
        grad = matrix.T @ weighted_errors
        intercept -= learning_rate * grad_intercept / total_weight
        base_logit_coefficient -= learning_rate * (
            grad_base / total_weight + l2 * (base_logit_coefficient - 1.0)
        )
        coefficients -= learning_rate * (grad / total_weight + l2 * coefficients)
    return LogisticMarketArtifact(
        version="logistic-market-v1", feature_names=feature_names,
        base_logit_coefficient=base_logit_coefficient,
        coefficients=tuple(float(value) for value in coefficients), intercept=intercept,
        feature_means=tuple(centers), feature_stds=tuple(scales),
        independent_markets=len(markets), training_points=len(data),
    )


def fit_lightgbm_alpha(
    rows: Iterable[dict], feature_names: tuple[str, ...] = DEFAULT_ALPHA_FEATURES,
) -> LightGBMAlphaArtifact:
    import lightgbm as lgb
    import numpy as np

    data = balanced_market_sample(rows)
    markets = sorted({row["market_id"] for row in data})
    if len(markets) < 10:
        raise ValueError("at least ten independent markets are required for LightGBM")
    counts = {market: sum(row["market_id"] == market for row in data) for market in markets}
    matrix = np.asarray([
        [float(row["features"].get(name, 0.0) or 0.0) for name in feature_names]
        for row in data
    ], dtype=float)
    feature_means = tuple(float(value) for value in np.mean(matrix, axis=0))
    feature_stds = tuple(max(float(value), 1e-9) for value in np.std(matrix, axis=0))
    labels = []
    initial_scores = []
    weights = []
    for row in data:
        pm = clamp_probability(float(row["market_probability_up"]))
        labels.append(int(row["outcome"]))
        initial_scores.append(logit(pm))
        weights.append(1.0 / counts[row["market_id"]])
    dataset = lgb.Dataset(
        matrix, label=np.asarray(labels), weight=np.asarray(weights),
        init_score=np.asarray(initial_scores),
        feature_name=list(feature_names), free_raw_data=False,
    )
    model = lgb.train({
        "objective": "binary", "metric": "binary_logloss", "learning_rate": 0.03,
        "num_leaves": 7, "max_depth": 3, "min_data_in_leaf": 5,
        "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1,
        "lambda_l2": 2.0, "seed": 7, "deterministic": True,
        "force_col_wise": True, "verbosity": -1, "num_threads": 1,
        "boost_from_average": False,
    }, dataset, num_boost_round=120)
    return LightGBMAlphaArtifact(
        version="lightgbm-alpha-v1", feature_names=feature_names,
        model_text=model.model_to_string(), feature_means=feature_means,
        feature_stds=feature_stds, independent_markets=len(markets),
        training_points=len(data),
    )


def fit_platt(
    probabilities: Iterable[float], outcomes: Iterable[int], market_ids: Iterable[str],
    learning_rate: float = 0.05, iterations: int = 1000, l2: float = 0.001,
    intercept_l2: float = 0.0, selection_method: str = "fixed",
) -> PlattArtifact:
    import numpy as np

    values, labels, markets = list(probabilities), list(outcomes), list(market_ids)
    if not (len(values) == len(labels) == len(markets)) or not values:
        raise ValueError("aligned calibration samples are required")
    grouped_indices: dict[str, list[int]] = {}
    for index, market in enumerate(markets):
        grouped_indices.setdefault(market, []).append(index)
    selected_indices = [
        index
        for market_indices in grouped_indices.values()
        for position in _evenly_spaced_indices(len(market_indices), MAX_FIT_POINTS_PER_MARKET)
        for index in (market_indices[position],)
    ]
    values = [values[index] for index in selected_indices]
    labels = [labels[index] for index in selected_indices]
    markets = [markets[index] for index in selected_indices]
    unique = sorted(set(markets))
    if len(unique) < 2:
        raise ValueError("at least two independent calibration markets are required")
    counts = {market: markets.count(market) for market in unique}
    slope, intercept = 1.0, 0.0
    total_weight = float(len(unique))
    logits = np.asarray([logit(value) for value in values], dtype=float)
    labels_array = np.asarray(labels, dtype=float)
    weights = np.asarray([1.0 / counts[market] for market in markets], dtype=float)
    for _ in range(iterations):
        scores = slope * logits + intercept
        probabilities = 1.0 / (1.0 + np.exp(-np.clip(scores, -700.0, 700.0)))
        weighted_errors = weights * (probabilities - labels_array)
        grad_slope = float(weighted_errors @ logits)
        grad_intercept = float(weighted_errors.sum())
        slope -= learning_rate * (grad_slope / total_weight + l2 * (slope - 1.0))
        intercept -= learning_rate * (
            grad_intercept / total_weight + intercept_l2 * intercept
        )
    return PlattArtifact(
        slope=slope, intercept=intercept, independent_markets=len(unique),
        regularization=l2, intercept_regularization=intercept_l2,
        selection_method=selection_method,
    )


def _market_balanced_calibration_metrics(
    probabilities: list[float], outcomes: list[int], market_ids: list[str],
) -> tuple[float, float]:
    groups: dict[str, list[int]] = {}
    for index, market in enumerate(market_ids):
        groups.setdefault(market, []).append(index)
    brier = mean(mean(
        (probabilities[index] - int(outcomes[index])) ** 2 for index in indices
    ) for indices in groups.values())
    weighted = [
        (probabilities[index], int(outcomes[index]), 1.0 / len(indices))
        for indices in groups.values() for index in indices
    ]
    total_weight = float(len(groups))
    ece = 0.0
    for bin_index in range(10):
        low, high = bin_index / 10, (bin_index + 1) / 10
        bucket = [
            item for item in weighted
            if low <= item[0] < high or (bin_index == 9 and item[0] == 1)
        ]
        if bucket:
            weight_sum = sum(item[2] for item in bucket)
            predicted = sum(item[0] * item[2] for item in bucket) / weight_sum
            observed = sum(item[1] * item[2] for item in bucket) / weight_sum
            ece += weight_sum / total_weight * abs(predicted - observed)
    return brier, ece


def fit_stable_platt(
    probabilities: Iterable[float], outcomes: Iterable[int], market_ids: Iterable[str],
    regularizations: tuple[float, ...] = (0.001, 0.01, 0.1, 1.0, 10.0),
) -> PlattArtifact:
    """Select Platt regularization inside calibration data, never on outer validation."""
    values, labels, markets = list(probabilities), list(outcomes), list(market_ids)
    if not (len(values) == len(labels) == len(markets)) or not values:
        raise ValueError("aligned calibration samples are required")
    market_order: list[str] = []
    for market in markets:
        if market not in market_order:
            market_order.append(market)
    if len(market_order) < 12:
        return fit_platt(values, labels, markets)
    split = max(2, min(len(market_order) - 5, int(len(market_order) * 0.7)))
    fit_markets, selection_markets = set(market_order[:split]), set(market_order[split:])
    fit_indices = [index for index, market in enumerate(markets) if market in fit_markets]
    selection_indices = [index for index, market in enumerate(markets) if market in selection_markets]
    fit_values = [values[index] for index in fit_indices]
    fit_labels = [labels[index] for index in fit_indices]
    fit_ids = [markets[index] for index in fit_indices]
    selection_values = [values[index] for index in selection_indices]
    selection_labels = [labels[index] for index in selection_indices]
    selection_ids = [markets[index] for index in selection_indices]
    baseline = _market_balanced_calibration_metrics(
        selection_values, selection_labels, selection_ids,
    )
    eligible: list[tuple[float, float, float]] = []
    for regularization in regularizations:
        candidate = fit_platt(
            fit_values, fit_labels, fit_ids, iterations=500,
            l2=regularization, intercept_l2=regularization,
            selection_method="inner-temporal",
        )
        predictions = [candidate.calibrate(value) for value in selection_values]
        brier, ece = _market_balanced_calibration_metrics(
            predictions, selection_labels, selection_ids,
        )
        if brier < baseline[0] and ece < baseline[1]:
            eligible.append((brier, ece, regularization))
    if not eligible:
        return PlattArtifact(
            slope=1.0, intercept=0.0, independent_markets=len(market_order),
            regularization=0.0, intercept_regularization=0.0,
            selection_method="inner-temporal-identity",
        )
    selected_regularization = min(eligible)[2]
    return fit_platt(
        values, labels, markets, l2=selected_regularization,
        intercept_l2=selected_regularization,
        selection_method="inner-temporal",
    )


def fit_logistic_alpha(
    rows: Iterable[dict], feature_names: tuple[str, ...] = DEFAULT_ALPHA_FEATURES,
    learning_rate: float = 0.05, iterations: int = 1000, l2: float = 0.01,
) -> LogisticAlphaArtifact:
    import numpy as np

    data = balanced_market_sample(rows)
    markets = sorted({row["market_id"] for row in data})
    if len(markets) < 2:
        raise ValueError("at least two independent Chainlink-labeled markets are required")
    counts = {market: sum(row["market_id"] == market for row in data) for market in markets}
    columns = [[float(row["features"].get(name, 0.0) or 0.0) for row in data] for name in feature_names]
    centers = [mean(column) for column in columns]
    scales = [max(pstdev(column), 1e-9) for column in columns]
    matrix = np.asarray([
        [(columns[j][i] - centers[j]) / scales[j] for j in range(len(feature_names))]
        for i in range(len(data))
    ], dtype=float)
    coefficients = np.zeros(len(feature_names), dtype=float)
    weights = np.asarray([1.0 / counts[row["market_id"]] for row in data], dtype=float)
    outcomes = np.asarray([int(row["outcome"]) for row in data], dtype=float)
    market_logits = np.asarray([
        logit(float(row["market_probability_up"])) for row in data
    ], dtype=float)
    intercept = 0.0
    total_weight = float(len(markets))
    for _ in range(iterations):
        scores = market_logits + intercept + matrix @ coefficients
        probabilities = 1.0 / (1.0 + np.exp(-np.clip(scores, -700.0, 700.0)))
        weighted_errors = weights * (probabilities - outcomes)
        grad_b = float(weighted_errors.sum())
        grad = matrix.T @ weighted_errors
        intercept -= learning_rate * grad_b / total_weight
        coefficients -= learning_rate * (grad / total_weight + l2 * coefficients)
    return LogisticAlphaArtifact(
        version="logistic-alpha-v1", feature_names=feature_names,
        coefficients=tuple(float(value) for value in coefficients), intercept=intercept,
        feature_means=tuple(centers), feature_stds=tuple(scales),
        independent_markets=len(markets), training_points=len(data),
        training_start=min(row["prediction_timestamp"] for row in data),
        training_end=max(row["prediction_timestamp"] for row in data),
    )


def log_loss(rows: Iterable[dict], artifact: LogisticAlphaArtifact) -> float:
    losses = []
    for row in rows:
        probability = artifact.predict(row["market_probability_up"], row["features"])
        outcome = int(row["outcome"])
        losses.append(-(outcome * log(probability) + (1 - outcome) * log(1 - probability)))
    return mean(losses)
