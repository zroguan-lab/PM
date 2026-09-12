from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
from statistics import mean, pstdev

from .models import clamp_probability
from .training import (
    DEFAULT_ALPHA_FEATURES, LightGBMAlphaArtifact, LogisticAlphaArtifact,
    LogisticMarketArtifact, PlattArtifact, fit_logistic_alpha,
    fit_logistic_market, fit_stable_platt,
    select_alpha_weight, select_market_weight, shrink_alpha_probability,
)
from .walkforward import WalkForwardProbabilityReport, row_time_bucket, walk_forward_probability_report


class ModelGateError(ValueError):
    """A rejected candidate that still carries its already-computed OOF report."""

    def __init__(self, message: str, report: WalkForwardProbabilityReport) -> None:
        super().__init__(message)
        self.report = report


@dataclass(frozen=True)
class PublishedModel:
    alpha: dict
    platt: dict
    uncertainty_standard_error: float
    validation: dict
    independent_markets: int
    published_at: str
    market: dict | None = None
    market_weight: float = 1.0
    time_scope: str | None = None
    calibration_method: str = "platt"
    alpha_kind: str = "logistic"
    alpha_weight: float = 1.0
    artifact_hash: str = ""

    def __post_init__(self) -> None:
        if not self.artifact_hash:
            payload = {key: value for key, value in asdict(self).items() if key != "artifact_hash"}
            object.__setattr__(self, "artifact_hash", sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest())

    def _alpha(self) -> LogisticAlphaArtifact | LightGBMAlphaArtifact:
        values = dict(self.alpha)
        tuple_fields = ("feature_names", "feature_means", "feature_stds")
        for key in tuple_fields:
            values[key] = tuple(values[key])
        if self.alpha_kind.endswith("lightgbm"):
            return LightGBMAlphaArtifact(**values)
        if not self.alpha_kind.endswith("logistic"):
            raise ValueError(f"unsupported alpha kind: {self.alpha_kind}")
        values["coefficients"] = tuple(values["coefficients"])
        return LogisticAlphaArtifact(**values)

    def _platt(self) -> PlattArtifact:
        return PlattArtifact(**self.platt)

    def _market(self) -> LogisticMarketArtifact | None:
        if self.market is None:
            return None
        values = dict(self.market)
        for key in ("feature_names", "coefficients", "feature_means", "feature_stds"):
            values[key] = tuple(values[key])
        return LogisticMarketArtifact(**values)

    def predict(self, market_probability: float, features: dict) -> dict:
        market_model = self._market()
        modeled_market_probability = (
            market_model.predict(market_probability, features)
            if market_model is not None else market_probability
        )
        modeled_market_probability = shrink_alpha_probability(
            market_probability, modeled_market_probability, self.market_weight,
        )
        alpha = self._alpha()
        raw_unshrunk = alpha.predict(modeled_market_probability, features)
        raw = shrink_alpha_probability(
            modeled_market_probability, raw_unshrunk, self.alpha_weight,
        )
        calibrated = self._platt().calibrate(raw)
        missing = sum(name not in features or features[name] is None for name in alpha.feature_names)
        extreme = 0
        for name, center, scale in zip(alpha.feature_names, alpha.feature_means, alpha.feature_stds):
            if name in features and features[name] is not None:
                extreme += abs((float(features[name]) - center) / scale) > 5
        ood_risk = (missing + extreme) / max(len(alpha.feature_names), 1)
        width = 1.2815515655446004 * self.uncertainty_standard_error * (1.0 + ood_risk)
        return {
            "market_model_probability": modeled_market_probability,
            "p_raw": raw, "p_calibrated": calibrated,
            "p_lower": clamp_probability(calibrated - width),
            "p_upper": clamp_probability(calibrated + width),
            "ood_risk": ood_risk, "model_version": f"published-{self.artifact_hash[:12]}",
        }

    def save(self, path: str) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(asdict(self), indent=2, sort_keys=True), encoding="utf-8")

    @classmethod
    def load(cls, path: str) -> "PublishedModel":
        values = json.loads(Path(path).read_text(encoding="utf-8"))
        expected = values.pop("artifact_hash")
        artifact = cls(**values)
        if artifact.artifact_hash != expected:
            raise ValueError("published model artifact hash mismatch")
        return cls(**values, artifact_hash=expected)


def publish_model(
    rows: list[dict], train_count: int, calibration_count: int, validation_count: int,
    minimum_markets: int = 500, feature_names: tuple[str, ...] = DEFAULT_ALPHA_FEATURES,
    time_scope: str | None = None, minimum_validation_markets: int = 0,
    alpha_fitter=fit_logistic_alpha, alpha_kind: str = "logistic",
) -> PublishedModel:
    if time_scope is not None:
        rows = [row for row in rows if row_time_bucket(row) == time_scope]
    market_order: list[str] = []
    for row in rows:
        if row["market_id"] not in market_order:
            market_order.append(row["market_id"])
    if len(market_order) < minimum_markets:
        raise ValueError(f"only {len(market_order)} independent markets; minimum is {minimum_markets}")
    report = walk_forward_probability_report(
        rows, train_count, calibration_count, validation_count,
        max_lookback=timedelta(minutes=5), embargo=timedelta(minutes=5),
        feature_names=feature_names, time_scope=time_scope, alpha_fitter=alpha_fitter,
    )
    if report.validation_markets < minimum_validation_markets:
        raise ModelGateError(
            f"scoped validation sample gate failed: scope={time_scope}, "
            f"validation_markets={report.validation_markets}, minimum={minimum_validation_markets}",
            report,
        )
    platt_ece = mean(fold.calibration_error for fold in report.folds)
    use_platt = (
        report.mean_model_brier < report.mean_raw_alpha_brier
        and platt_ece < report.mean_raw_alpha_calibration_error
    )
    selected_edge = (
        report.mean_probability_edge if use_platt
        else report.mean_raw_alpha_probability_edge
    )
    selected_model_brier = report.mean_model_brier if use_platt else report.mean_raw_alpha_brier
    selected_ece = platt_ece if use_platt else report.mean_raw_alpha_calibration_error
    selected_time_metrics = (
        report.by_time_remaining if use_platt else report.raw_by_time_remaining
    )
    best_time = max(
        ((key, value["brier_improvement"]) for key, value in selected_time_metrics.items()),
        key=lambda item: item[1], default=("none", float("nan")),
    )
    best_time_ci = selected_time_metrics.get(best_time[0], {}).get(
        "brier_improvement_ci", (float("nan"), float("nan"))
    )
    best_time_metrics = selected_time_metrics.get(best_time[0], {})
    best_time_markets = int(best_time_metrics.get("independent_markets", 0))
    best_time_ece = float(best_time_metrics.get("calibration_error", float("nan")))
    if selected_edge <= 0:
        raise ModelGateError(
            "probability edge gate failed: "
            f"edge={selected_edge:.6f}, model_brier={selected_model_brier:.6f}, "
            f"market_brier={report.mean_market_brier:.6f}, calibration={'platt' if use_platt else 'identity'}, "
            f"best_time_bucket={best_time[0]}:{best_time[1]:.6f}, "
            f"best_time_ci90=[{best_time_ci[0]:.6f},{best_time_ci[1]:.6f}], "
            f"best_time_markets={best_time_markets}, best_time_ece={best_time_ece:.6f}",
            report,
        )
    if selected_ece > 0.05:
        raise ModelGateError(
            f"calibration gate failed: ece={selected_ece:.6f}, "
            f"edge={selected_edge:.6f}, calibration={'platt' if use_platt else 'identity'}, "
            f"best_time_bucket={best_time[0]}:{best_time[1]:.6f}, "
            f"best_time_ci90=[{best_time_ci[0]:.6f},{best_time_ci[1]:.6f}], "
            f"best_time_markets={best_time_markets}, best_time_ece={best_time_ece:.6f}",
            report,
        )
    calibration_ids = set(market_order[-calibration_count:])
    calibration_start = min(
        datetime.fromisoformat(row["start_time"]) for row in rows if row["market_id"] in calibration_ids
    )
    train_ids = {
        market for market in market_order[:-calibration_count]
        if max(datetime.fromisoformat(row["end_time"]) for row in rows if row["market_id"] == market)
        <= calibration_start - timedelta(minutes=5)
    }
    training = [row for row in rows if row["market_id"] in train_ids]
    calibration = [row for row in rows if row["market_id"] in calibration_ids]
    market_model = fit_logistic_market(training)
    calibration_market_predictions = [
        market_model.predict(float(row["market_probability_up"]), row["features"])
        for row in calibration
    ]
    market_weight = select_market_weight(calibration, calibration_market_predictions)
    market_training = [{
        **row,
        "raw_market_probability_up": float(row["market_probability_up"]),
        "market_probability_up": shrink_alpha_probability(
            float(row["market_probability_up"]),
            market_model.predict(float(row["market_probability_up"]), row["features"]),
            market_weight,
        ),
    } for row in training]
    market_calibration = [{
        **row,
        "raw_market_probability_up": float(row["market_probability_up"]),
        "market_probability_up": shrink_alpha_probability(
            float(row["market_probability_up"]),
            market_model.predict(float(row["market_probability_up"]), row["features"]),
            market_weight,
        ),
    } for row in calibration]
    alpha = alpha_fitter(market_training, feature_names=feature_names)
    unshrunk = [
        alpha.predict(row["market_probability_up"], row["features"])
        for row in market_calibration
    ]
    alpha_weight = select_alpha_weight(market_calibration, unshrunk)
    raw = [
        shrink_alpha_probability(row["market_probability_up"], probability, alpha_weight)
        for row, probability in zip(market_calibration, unshrunk)
    ]
    platt = (
        fit_stable_platt(
            raw, [row["outcome"] for row in market_calibration],
            [row["market_id"] for row in market_calibration],
        )
        if use_platt else PlattArtifact(
            slope=1.0, intercept=0.0, independent_markets=len(calibration_ids),
            regularization=0.0, intercept_regularization=0.0,
            selection_method="identity",
        )
    )
    residual_by_market: dict[str, list[float]] = {}
    for row, probability in zip(calibration, raw):
        calibrated = platt.calibrate(probability)
        residual_by_market.setdefault(row["market_id"], []).append(int(row["outcome"]) - calibrated)
    residuals = [mean(values) for values in residual_by_market.values()]
    standard_error = max(pstdev(residuals), 0.01)
    validation = report.to_dict()
    validation.update({
        "selected_probability_edge": selected_edge,
        "selected_model_brier": selected_model_brier,
        "selected_calibration_error": selected_ece,
        "selected_calibration_method": "platt" if use_platt else "identity",
    })
    return PublishedModel(
        alpha=asdict(alpha), platt=asdict(platt), market=asdict(market_model),
        uncertainty_standard_error=standard_error,
        validation=validation, independent_markets=len(market_order),
        published_at=datetime.now().astimezone().isoformat(), time_scope=time_scope,
        calibration_method="platt" if use_platt else "identity",
        alpha_kind=alpha_kind, market_weight=market_weight,
        alpha_weight=alpha_weight,
    )
