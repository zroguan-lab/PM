from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class KillReason(str, Enum):
    ROLLING_EV = "ROLLING_EV"
    BRIER = "BRIER"
    CALIBRATION = "CALIBRATION"
    FEATURE_DRIFT = "FEATURE_DRIFT"
    OOD = "OOD"
    PREDICTION_DRIFT = "PREDICTION_DRIFT"
    SLIPPAGE_DIVERGENCE = "SLIPPAGE_DIVERGENCE"
    DRAWDOWN = "DRAWDOWN"
    INTEGRITY = "INTEGRITY"


@dataclass(frozen=True)
class StatisticalSnapshot:
    rolling_ev_lower_bound: float | None = None
    brier_degradation: float | None = None
    calibration_error: float | None = None
    calibration_baseline: float | None = None
    feature_psi: float | None = None
    ood_fraction: float | None = None
    prediction_drift_windows: int = 0
    slippage_divergence: float | None = None
    drawdown: float | None = None
    integrity_ok: bool = True


class StatisticalKillSwitch:
    def evaluate(self, snapshot: StatisticalSnapshot) -> tuple[KillReason, ...]:
        reasons: list[KillReason] = []
        if snapshot.rolling_ev_lower_bound is not None and snapshot.rolling_ev_lower_bound <= 0:
            reasons.append(KillReason.ROLLING_EV)
        if snapshot.brier_degradation is not None and snapshot.brier_degradation > 0.01:
            reasons.append(KillReason.BRIER)
        if snapshot.calibration_error is not None:
            doubled = snapshot.calibration_baseline is not None and snapshot.calibration_error >= 2 * snapshot.calibration_baseline
            if snapshot.calibration_error > 0.05 or doubled:
                reasons.append(KillReason.CALIBRATION)
        if snapshot.feature_psi is not None and snapshot.feature_psi > 0.25:
            reasons.append(KillReason.FEATURE_DRIFT)
        if snapshot.ood_fraction is not None and snapshot.ood_fraction > 0.10:
            reasons.append(KillReason.OOD)
        if snapshot.prediction_drift_windows >= 3:
            reasons.append(KillReason.PREDICTION_DRIFT)
        if snapshot.slippage_divergence is not None and snapshot.slippage_divergence > 0.01:
            reasons.append(KillReason.SLIPPAGE_DIVERGENCE)
        if snapshot.drawdown is not None and snapshot.drawdown >= 0.05:
            reasons.append(KillReason.DRAWDOWN)
        if not snapshot.integrity_ok:
            reasons.append(KillReason.INTEGRITY)
        return tuple(reasons)

