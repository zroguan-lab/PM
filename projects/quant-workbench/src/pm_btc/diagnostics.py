from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta

from .backtest import MarketInterval, PurgedWalkForward
from .statistics import PredictionRecord, clustered_metrics
from .training import (
    DEFAULT_ALPHA_FEATURES, fit_logistic_alpha, fit_logistic_market,
    fit_stable_platt, select_market_weight, shrink_alpha_probability,
)


def _time_bucket(seconds: float) -> str:
    if seconds <= 30:
        return "0-30s"
    if seconds <= 60:
        return "31-60s"
    if seconds <= 120:
        return "61-120s"
    return "121-300s"


def purged_oof_diagnostics(
    rows: list[dict], train_count: int, calibration_count: int, validation_count: int,
    feature_names: tuple[str, ...] = DEFAULT_ALPHA_FEATURES,
) -> dict:
    by_market: dict[str, dict] = {}
    for row in rows:
        by_market.setdefault(row["market_id"], row)
    intervals = [MarketInterval(
        market_id=market_id, start=datetime.fromisoformat(row["start_time"]),
        end=datetime.fromisoformat(row["end_time"]),
    ) for market_id, row in by_market.items()]
    folds = PurgedWalkForward(timedelta(minutes=5), timedelta(minutes=5)).split(
        intervals, train_count, calibration_count, validation_count,
    )
    predictions: list[tuple[PredictionRecord, str, str]] = []
    for fold in folds:
        train_ids, calibration_ids, validation_ids = map(set, (
            fold.train_market_ids, fold.calibration_market_ids, fold.validation_market_ids,
        ))
        train = [row for row in rows if row["market_id"] in train_ids]
        calibration = [row for row in rows if row["market_id"] in calibration_ids]
        validation = [row for row in rows if row["market_id"] in validation_ids]
        if len(train_ids) < 2 or len(calibration_ids) < 2 or not validation:
            continue
        market_model = fit_logistic_market(train)
        calibration_market_predictions = [
            market_model.predict(row["market_probability_up"], row["features"])
            for row in calibration
        ]
        market_weight = select_market_weight(
            calibration, calibration_market_predictions,
        )
        def adjusted(row: dict) -> dict:
            raw_probability = float(row["market_probability_up"])
            modeled_probability = market_model.predict(raw_probability, row["features"])
            return {
                **row,
                "market_probability_up": shrink_alpha_probability(
                    raw_probability, modeled_probability, market_weight,
                ),
            }
        adjusted_train = [{
            **adjusted(row),
        } for row in train]
        adjusted_calibration = [adjusted(row) for row in calibration]
        adjusted_validation = [adjusted(row) for row in validation]
        alpha = fit_logistic_alpha(adjusted_train, feature_names=feature_names)
        raw = [
            alpha.predict(row["market_probability_up"], row["features"])
            for row in adjusted_calibration
        ]
        platt = fit_stable_platt(
            raw, [row["outcome"] for row in adjusted_calibration],
            [row["market_id"] for row in adjusted_calibration],
        )
        for row, adjusted in zip(validation, adjusted_validation):
            probability = platt.calibrate(
                alpha.predict(adjusted["market_probability_up"], adjusted["features"]),
            )
            remaining = max(0.0, (datetime.fromisoformat(row["end_time"]) - datetime.fromisoformat(row["prediction_timestamp"])).total_seconds())
            record = PredictionRecord(
                market_id=row["market_id"], model_probability=probability,
                market_probability=row["market_probability_up"], outcome=row["outcome"],
                regime=str(row["features"].get("regime_key", "unknown")),
            )
            predictions.append((record, _time_bucket(remaining), record.regime))
    if not predictions:
        raise ValueError("no valid out-of-fold predictions")

    def summarize(items: list[PredictionRecord]) -> dict:
        metrics = clustered_metrics(items, bootstrap_samples=300)
        return asdict(metrics)

    overall = summarize([item[0] for item in predictions])
    by_time = {
        bucket: summarize([record for record, value, _ in predictions if value == bucket])
        for bucket in ("0-30s", "31-60s", "61-120s", "121-300s")
        if len({record.market_id for record, value, _ in predictions if value == bucket}) >= 5
    }
    regimes = sorted({regime for _, _, regime in predictions})
    by_regime = {
        regime: summarize([record for record, _, value in predictions if value == regime])
        for regime in regimes
        if len({record.market_id for record, _, value in predictions if value == regime}) >= 5
    }
    return {"overall": overall, "by_time_remaining": by_time, "by_regime": by_regime}
