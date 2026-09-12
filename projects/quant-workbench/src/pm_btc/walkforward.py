from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from statistics import mean
from typing import Callable, Iterable

from .backtest import MarketInterval, PurgedWalkForward
from .training import (
    DEFAULT_ALPHA_FEATURES, fit_logistic_alpha, fit_logistic_market,
    fit_stable_platt, select_alpha_weight, select_market_weight,
    shrink_alpha_probability,
)
from .statistics import PredictionRecord, clustered_metrics


def row_time_bucket(row: dict) -> str:
    remaining = max(0.0, (
        datetime.fromisoformat(row["end_time"]) - datetime.fromisoformat(row["prediction_timestamp"])
    ).total_seconds())
    return "0-30s" if remaining <= 30 else "31-60s" if remaining <= 60 else "61-120s" if remaining <= 120 else "121-300s"


@dataclass(frozen=True)
class FoldProbabilityReport:
    fold: int
    train_markets: int
    calibration_markets: int
    validation_markets: int
    purged_markets: int
    embargoed_markets: int
    model_brier: float
    market_brier: float
    raw_alpha_brier: float
    raw_alpha_probability_edge: float
    raw_alpha_calibration_error: float
    market_model_weight: float
    alpha_weight: float
    market_model_brier: float
    calibrated_market_brier: float
    probability_edge: float
    calibration_error: float


@dataclass(frozen=True)
class WalkForwardProbabilityReport:
    folds: tuple[FoldProbabilityReport, ...]
    validation_markets: int
    mean_model_brier: float
    mean_market_brier: float
    mean_raw_alpha_brier: float
    mean_raw_alpha_probability_edge: float
    mean_raw_alpha_calibration_error: float
    mean_market_model_weight: float
    mean_alpha_weight: float
    mean_market_model_brier: float
    mean_calibrated_market_brier: float
    mean_probability_edge: float
    mean_calibration_error: float
    by_time_remaining: dict
    by_regime: dict
    raw_by_time_remaining: dict
    raw_by_regime: dict

    def to_dict(self) -> dict:
        return asdict(self)


def _market_rows(rows: list[dict], market_ids: set[str]) -> list[dict]:
    return [row for row in rows if row["market_id"] in market_ids]


def _predict_rows(alpha, rows: list[dict]) -> list[float]:
    if hasattr(alpha, "predict_many"):
        return alpha.predict_many(rows)
    return [alpha.predict(row["market_probability_up"], row["features"]) for row in rows]


def _market_adjusted_rows(market_model, rows: list[dict], weight: float) -> list[dict]:
    return [{
        **row,
        "raw_market_probability_up": float(row["market_probability_up"]),
        "market_probability_up": shrink_alpha_probability(
            float(row["market_probability_up"]),
            market_model.predict(float(row["market_probability_up"]), row["features"]),
            weight,
        ),
    } for row in rows]


def _ece(probabilities: list[float], outcomes: list[int], bins: int = 10) -> float:
    error = 0.0
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        selected = [i for i, probability in enumerate(probabilities) if low <= probability < high or (index == bins - 1 and probability == 1)]
        if selected:
            error += len(selected) / len(probabilities) * abs(
                mean(probabilities[i] for i in selected) - mean(outcomes[i] for i in selected)
            )
    return error


def walk_forward_probability_report(
    rows: Iterable[dict], train_count: int, calibration_count: int,
    validation_count: int, max_lookback: timedelta = timedelta(minutes=5),
    embargo: timedelta = timedelta(minutes=5),
    feature_names: tuple[str, ...] = DEFAULT_ALPHA_FEATURES,
    time_scope: str | None = None,
    alpha_fitter: Callable = fit_logistic_alpha,
) -> WalkForwardProbabilityReport:
    data = list(rows)
    by_market: dict[str, dict] = {}
    for row in data:
        by_market.setdefault(row["market_id"], row)
    intervals = [MarketInterval(
        market_id=market, start=datetime.fromisoformat(row["start_time"]),
        end=datetime.fromisoformat(row["end_time"]),
    ) for market, row in by_market.items()]
    folds = PurgedWalkForward(max_lookback, embargo).split(
        intervals, train_count, calibration_count, validation_count
    )
    reports: list[FoldProbabilityReport] = []
    calibrated_oof: list[tuple[PredictionRecord, str, str]] = []
    raw_oof: list[tuple[PredictionRecord, str, str]] = []
    for index, fold in enumerate(folds):
        train = _market_rows(data, set(fold.train_market_ids))
        calibration = _market_rows(data, set(fold.calibration_market_ids))
        validation = _market_rows(data, set(fold.validation_market_ids))
        if time_scope is not None:
            train = [row for row in train if row_time_bucket(row) == time_scope]
            calibration = [row for row in calibration if row_time_bucket(row) == time_scope]
            validation = [row for row in validation if row_time_bucket(row) == time_scope]
        if len(set(row["market_id"] for row in train)) < 2 or len(set(row["market_id"] for row in calibration)) < 2:
            continue
        market_model = fit_logistic_market(train)
        calibration_market_predictions = [
            market_model.predict(float(row["market_probability_up"]), row["features"])
            for row in calibration
        ]
        market_model_weight = select_market_weight(
            calibration, calibration_market_predictions,
        )
        market_train = _market_adjusted_rows(market_model, train, market_model_weight)
        market_calibration = _market_adjusted_rows(
            market_model, calibration, market_model_weight,
        )
        market_validation = _market_adjusted_rows(
            market_model, validation, market_model_weight,
        )
        alpha = alpha_fitter(market_train, feature_names=feature_names)
        calibration_unshrunk = _predict_rows(alpha, market_calibration)
        alpha_weight = select_alpha_weight(market_calibration, calibration_unshrunk)
        calibration_raw = [
            shrink_alpha_probability(row["market_probability_up"], probability, alpha_weight)
            for row, probability in zip(market_calibration, calibration_unshrunk)
        ]
        platt = fit_stable_platt(
            calibration_raw, [row["outcome"] for row in market_calibration],
            [row["market_id"] for row in market_calibration],
        )
        market_platt = fit_stable_platt(
            [row["market_probability_up"] for row in market_calibration],
            [row["outcome"] for row in market_calibration],
            [row["market_id"] for row in market_calibration],
        )
        validation_unshrunk = _predict_rows(alpha, market_validation)
        validation_raw = [
            shrink_alpha_probability(row["market_probability_up"], probability, alpha_weight)
            for row, probability in zip(market_validation, validation_unshrunk)
        ]
        probabilities = [platt.calibrate(value) for value in validation_raw]
        market_model_probabilities = [
            float(row["market_probability_up"]) for row in market_validation
        ]
        calibrated_market_probabilities = [
            market_platt.calibrate(value) for value in market_model_probabilities
        ]
        outcomes = [row["outcome"] for row in validation]
        market_probabilities = [row["market_probability_up"] for row in validation]
        fold_records = [PredictionRecord(
            market_id=row["market_id"], model_probability=probability,
            market_probability=float(row["market_probability_up"]),
            outcome=int(row["outcome"]),
        ) for row, probability in zip(validation, probabilities)]
        fold_metrics = clustered_metrics(fold_records, bootstrap_samples=100)
        raw_metrics = clustered_metrics([
            PredictionRecord(
                market_id=row["market_id"], model_probability=probability,
                market_probability=float(row["market_probability_up"]), outcome=int(row["outcome"]),
            ) for row, probability in zip(validation, validation_raw)
        ], bootstrap_samples=100)
        market_model_metrics = clustered_metrics([
            PredictionRecord(
                market_id=row["market_id"], model_probability=probability,
                market_probability=float(row["market_probability_up"]), outcome=int(row["outcome"]),
            ) for row, probability in zip(validation, market_model_probabilities)
        ], bootstrap_samples=100)
        calibrated_market_metrics = clustered_metrics([
            PredictionRecord(
                market_id=row["market_id"], model_probability=probability,
                market_probability=float(row["market_probability_up"]), outcome=int(row["outcome"]),
            ) for row, probability in zip(validation, calibrated_market_probabilities)
        ], bootstrap_samples=100)
        model_brier = fold_metrics.model_brier
        market_brier = fold_metrics.market_brier
        reports.append(FoldProbabilityReport(
            fold=index, train_markets=len({row["market_id"] for row in train}),
            calibration_markets=len({row["market_id"] for row in calibration}),
            validation_markets=len({row["market_id"] for row in validation}),
            purged_markets=len(set(fold.purged_market_ids)),
            embargoed_markets=len(set(fold.embargoed_market_ids)),
            model_brier=model_brier, market_brier=market_brier,
            raw_alpha_brier=raw_metrics.model_brier,
            raw_alpha_probability_edge=raw_metrics.brier_improvement,
            raw_alpha_calibration_error=raw_metrics.calibration_error,
            market_model_weight=market_model_weight,
            alpha_weight=alpha_weight,
            market_model_brier=market_model_metrics.model_brier,
            calibrated_market_brier=calibrated_market_metrics.model_brier,
            probability_edge=market_brier - model_brier,
            calibration_error=fold_metrics.calibration_error,
        ))
        for row, probability, raw_probability in zip(validation, probabilities, validation_raw):
            bucket = row_time_bucket(row)
            regime = str(row["features"].get("regime_key", "unknown"))
            calibrated_oof.append((PredictionRecord(
                market_id=row["market_id"], model_probability=probability,
                market_probability=row["market_probability_up"], outcome=row["outcome"],
                regime=regime,
            ), bucket, regime))
            raw_oof.append((PredictionRecord(
                market_id=row["market_id"], model_probability=raw_probability,
                market_probability=row["market_probability_up"], outcome=row["outcome"],
                regime=regime,
            ), bucket, regime))
    if not reports:
        raise ValueError("no valid purged walk-forward folds")
    def summaries(records: list[tuple[PredictionRecord, str, str]], position: int) -> dict:
        keys = sorted({item[position] for item in records})
        result = {}
        for key in keys:
            selected = [item[0] for item in records if item[position] == key]
            if len({record.market_id for record in selected}) >= 5:
                result[key] = asdict(clustered_metrics(selected, bootstrap_samples=100))
        return result

    return WalkForwardProbabilityReport(
        folds=tuple(reports), validation_markets=sum(item.validation_markets for item in reports),
        mean_model_brier=mean(item.model_brier for item in reports),
        mean_market_brier=mean(item.market_brier for item in reports),
        mean_raw_alpha_brier=mean(item.raw_alpha_brier for item in reports),
        mean_raw_alpha_probability_edge=mean(item.raw_alpha_probability_edge for item in reports),
        mean_raw_alpha_calibration_error=mean(item.raw_alpha_calibration_error for item in reports),
        mean_market_model_weight=mean(item.market_model_weight for item in reports),
        mean_alpha_weight=mean(item.alpha_weight for item in reports),
        mean_market_model_brier=mean(item.market_model_brier for item in reports),
        mean_calibrated_market_brier=mean(item.calibrated_market_brier for item in reports),
        mean_probability_edge=mean(item.probability_edge for item in reports),
        mean_calibration_error=mean(item.calibration_error for item in reports),
        by_time_remaining=summaries(calibrated_oof, 1),
        by_regime=summaries(calibrated_oof, 2),
        raw_by_time_remaining=summaries(raw_oof, 1),
        raw_by_regime=summaries(raw_oof, 2),
    )
