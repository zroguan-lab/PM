from __future__ import annotations

from .training import DEFAULT_ALPHA_FEATURES, fit_lightgbm_alpha
from .walkforward import walk_forward_probability_report


def compare_lightgbm_challenger(
    rows: list[dict], train_count: int, calibration_count: int, validation_count: int,
    feature_names: tuple[str, ...] = DEFAULT_ALPHA_FEATURES,
) -> dict:
    logistic = walk_forward_probability_report(
        rows, train_count, calibration_count, validation_count,
        feature_names=feature_names,
    )
    lightgbm = walk_forward_probability_report(
        rows, train_count, calibration_count, validation_count,
        feature_names=feature_names, alpha_fitter=fit_lightgbm_alpha,
    )
    return {
        "logistic": {
            "model_brier": logistic.mean_model_brier,
            "market_brier": logistic.mean_market_brier,
            "raw_alpha_brier": logistic.mean_raw_alpha_brier,
            "raw_alpha_probability_edge": logistic.mean_raw_alpha_probability_edge,
            "raw_alpha_calibration_error": logistic.mean_raw_alpha_calibration_error,
            "calibrated_market_brier": logistic.mean_calibrated_market_brier,
            "market_model_brier": logistic.mean_market_model_brier,
            "mean_alpha_weight": logistic.mean_alpha_weight,
            "mean_market_model_weight": logistic.mean_market_model_weight,
            "probability_edge": logistic.mean_probability_edge,
            "calibration_error": logistic.mean_calibration_error,
        },
        "lightgbm": {
            "model_brier": lightgbm.mean_model_brier,
            "market_brier": lightgbm.mean_market_brier,
            "raw_alpha_brier": lightgbm.mean_raw_alpha_brier,
            "raw_alpha_probability_edge": lightgbm.mean_raw_alpha_probability_edge,
            "raw_alpha_calibration_error": lightgbm.mean_raw_alpha_calibration_error,
            "calibrated_market_brier": lightgbm.mean_calibrated_market_brier,
            "market_model_brier": lightgbm.mean_market_model_brier,
            "mean_alpha_weight": lightgbm.mean_alpha_weight,
            "mean_market_model_weight": lightgbm.mean_market_model_weight,
            "probability_edge": lightgbm.mean_probability_edge,
            "calibration_error": lightgbm.mean_calibration_error,
        },
        "lightgbm_beats_logistic": lightgbm.mean_model_brier < logistic.mean_model_brier,
        "lightgbm_probability_edge_positive": lightgbm.mean_probability_edge > 0,
    }
