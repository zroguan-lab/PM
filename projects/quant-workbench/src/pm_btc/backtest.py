from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Iterable

from .domain import ExecutionKind


class FillScenario(str, Enum):
    OPTIMISTIC = "OPTIMISTIC"
    ESTIMATED = "ESTIMATED"
    CONSERVATIVE = "CONSERVATIVE"


@dataclass(frozen=True)
class MakerFillInput:
    limit_price: float
    touched: bool
    traded_through: bool
    queue_ahead: float
    traded_volume_at_price: float
    order_size: float
    adverse_move: float


@dataclass(frozen=True)
class FillResult:
    scenario: FillScenario
    fill_probability: float
    filled_size: float
    adverse_selection_cost: float
    estimated: bool = True


class MakerFillSimulator:
    def simulate(self, request: MakerFillInput, scenario: FillScenario) -> FillResult:
        if request.order_size <= 0:
            raise ValueError("order_size must be positive")
        if scenario is FillScenario.OPTIMISTIC:
            probability = 1.0 if request.touched else 0.0
        else:
            available = max(0.0, request.traded_volume_at_price - max(0.0, request.queue_ahead))
            base = min(1.0, available / request.order_size)
            if request.traded_through:
                base = max(base, 0.85)
            elif not request.touched:
                base = 0.0
            probability = base if scenario is FillScenario.ESTIMATED else base * 0.55
        filled = request.order_size * probability
        adverse_multiplier = {
            FillScenario.OPTIMISTIC: 0.0,
            FillScenario.ESTIMATED: 1.0,
            FillScenario.CONSERVATIVE: 1.5,
        }[scenario]
        return FillResult(
            scenario=scenario,
            fill_probability=probability,
            filled_size=filled,
            adverse_selection_cost=max(0.0, request.adverse_move) * adverse_multiplier,
            estimated=scenario is not FillScenario.OPTIMISTIC,
        )


@dataclass(frozen=True)
class MarketInterval:
    market_id: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class WalkForwardFold:
    train_market_ids: tuple[str, ...]
    calibration_market_ids: tuple[str, ...]
    validation_market_ids: tuple[str, ...]
    purged_market_ids: tuple[str, ...]
    embargoed_market_ids: tuple[str, ...]


class PurgedWalkForward:
    def __init__(self, max_lookback: timedelta, embargo: timedelta = timedelta(minutes=5)) -> None:
        self.max_lookback = max_lookback
        self.embargo = embargo

    def split(
        self,
        markets: Iterable[MarketInterval],
        train_count: int,
        calibration_count: int,
        validation_count: int,
    ) -> list[WalkForwardFold]:
        ordered = sorted(markets, key=lambda item: item.start)
        folds: list[WalkForwardFold] = []
        cursor = train_count
        while cursor + calibration_count + validation_count <= len(ordered):
            validation_start_idx = cursor + calibration_count
            calibration_start = ordered[cursor].start
            validation_start = ordered[validation_start_idx].start
            train = [m for m in ordered[:cursor] if m.end <= calibration_start - self.max_lookback]
            purged = [m for m in ordered[:cursor] if m not in train]
            calibration = [m for m in ordered[cursor:validation_start_idx] if m.end <= validation_start - self.max_lookback]
            purged.extend(m for m in ordered[cursor:validation_start_idx] if m not in calibration)
            validation_end_idx = validation_start_idx + validation_count
            validation = ordered[validation_start_idx:validation_end_idx]
            embargo_end = validation[-1].end + self.embargo
            embargoed = [m for m in ordered[validation_end_idx:] if m.start < embargo_end]
            folds.append(
                WalkForwardFold(
                    train_market_ids=tuple(m.market_id for m in train),
                    calibration_market_ids=tuple(m.market_id for m in calibration),
                    validation_market_ids=tuple(m.market_id for m in validation),
                    purged_market_ids=tuple(m.market_id for m in purged),
                    embargoed_market_ids=tuple(m.market_id for m in embargoed),
                )
            )
            cursor += validation_count
        return folds

