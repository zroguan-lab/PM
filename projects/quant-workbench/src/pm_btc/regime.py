from dataclasses import dataclass
from datetime import datetime

from .domain import Regime


@dataclass(frozen=True)
class RegimeThresholds:
    volatility_low: float
    volatility_high: float
    trend_abs: float
    liquidity_low: float
    spread_tight: float
    spread_wide: float


class RegimeEngine:
    def __init__(self, thresholds: RegimeThresholds) -> None:
        self.thresholds = thresholds

    def classify(
        self,
        volatility: float,
        trend: float,
        depth: float,
        spread: float,
        timestamp: datetime,
    ) -> Regime:
        t = self.thresholds
        vol = "low" if volatility < t.volatility_low else "high" if volatility > t.volatility_high else "normal"
        trend_name = "up" if trend > t.trend_abs else "down" if trend < -t.trend_abs else "flat"
        liquidity = "thin" if depth < t.liquidity_low else "normal"
        spread_name = "tight" if spread <= t.spread_tight else "wide" if spread >= t.spread_wide else "normal"
        hour = timestamp.hour
        tod = "asia" if hour < 8 else "europe" if hour < 16 else "us"
        return Regime(volatility=vol, trend=trend_name, liquidity=liquidity, time_of_day=tod, spread=spread_name)

