from __future__ import annotations

from dataclasses import dataclass
from random import Random
from statistics import mean
from typing import Iterable


@dataclass(frozen=True)
class PredictionRecord:
    market_id: str
    model_probability: float
    market_probability: float
    outcome: int
    net_edge: float = 0.0
    realized_pnl: float = 0.0
    regime: str = "unknown"


@dataclass(frozen=True)
class ClusteredMetrics:
    independent_markets: int
    prediction_points: int
    model_brier: float
    market_brier: float
    brier_improvement: float
    calibration_error: float
    mean_net_edge: float
    mean_realized_pnl: float
    brier_improvement_ci: tuple[float, float]


def _market_aggregate(records: Iterable[PredictionRecord]) -> dict[str, list[PredictionRecord]]:
    clusters: dict[str, list[PredictionRecord]] = {}
    for record in records:
        clusters.setdefault(record.market_id, []).append(record)
    return clusters


def expected_calibration_error(records: list[PredictionRecord], bins: int = 10) -> float:
    total = len(records)
    if total == 0:
        return 0.0
    error = 0.0
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        bucket = [r for r in records if low <= r.model_probability < high or (index == bins - 1 and r.model_probability == 1)]
        if bucket:
            error += len(bucket) / total * abs(mean(r.model_probability for r in bucket) - mean(r.outcome for r in bucket))
    return error


def clustered_metrics(
    records: Iterable[PredictionRecord],
    bootstrap_samples: int = 500,
    seed: int = 7,
) -> ClusteredMetrics:
    rows = list(records)
    clusters = _market_aggregate(rows)
    if not rows or not clusters:
        raise ValueError("records are required")

    def cluster_scores(group: list[PredictionRecord]) -> tuple[float, float, float, float]:
        return (
            mean((r.model_probability - r.outcome) ** 2 for r in group),
            mean((r.market_probability - r.outcome) ** 2 for r in group),
            mean(r.net_edge for r in group),
            sum(r.realized_pnl for r in group),
        )

    scores = {market: cluster_scores(group) for market, group in clusters.items()}

    weighted_rows = [
        (record, 1.0 / len(group))
        for group in clusters.values() for record in group
    ]
    cluster_ece = 0.0
    total_weight = float(len(clusters))
    for index in range(10):
        low, high = index / 10, (index + 1) / 10
        bucket = [
            (record, weight) for record, weight in weighted_rows
            if low <= record.model_probability < high or (index == 9 and record.model_probability == 1)
        ]
        if bucket:
            weight_sum = sum(weight for _, weight in bucket)
            probability = sum(record.model_probability * weight for record, weight in bucket) / weight_sum
            outcome = sum(record.outcome * weight for record, weight in bucket) / weight_sum
            cluster_ece += weight_sum / total_weight * abs(probability - outcome)

    def brier_delta(sample_markets: list[str]) -> float:
        return mean(scores[market][1] - scores[market][0] for market in sample_markets)

    rng = Random(seed)
    market_ids = list(clusters)
    deltas: list[float] = []
    for _ in range(bootstrap_samples):
        sampled = [rng.choice(market_ids) for _ in market_ids]
        deltas.append(brier_delta(sampled))
    deltas.sort()
    lo = deltas[int(0.05 * (len(deltas) - 1))]
    hi = deltas[int(0.95 * (len(deltas) - 1))]
    model_brier = mean(value[0] for value in scores.values())
    market_brier = mean(value[1] for value in scores.values())
    market_pnls = [value[3] for value in scores.values()]
    return ClusteredMetrics(
        independent_markets=len(clusters),
        prediction_points=len(rows),
        model_brier=model_brier,
        market_brier=market_brier,
        brier_improvement=market_brier - model_brier,
        calibration_error=cluster_ece,
        mean_net_edge=mean(value[2] for value in scores.values()),
        mean_realized_pnl=mean(market_pnls),
        brier_improvement_ci=(lo, hi),
    )
