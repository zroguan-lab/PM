from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from typing import Any


CHAINLINK_BTC_USD_TWAP_60S_STREAM_ID = "polymarket-rtds:chainlink:btc/usd:twap-60s"


class Side(str, Enum):
    UP = "UP"
    DOWN = "DOWN"


class ExecutionKind(str, Enum):
    MAKER = "MAKER"
    TAKER = "TAKER"
    NO_TRADE = "NO_TRADE"


class SystemMode(str, Enum):
    READ_ONLY = "READ_ONLY"
    DISARMED = "DISARMED"
    PAPER = "PAPER"
    ARMED = "ARMED"


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    INVALID = "INVALID"


@dataclass(frozen=True)
class ChainlinkObservation:
    stream_id: str
    source_timestamp: datetime
    received_timestamp: datetime
    twap_60s: float
    report_id: str
    verification_status: VerificationStatus
    raw_payload_hash: str
    market_id: str

    def __post_init__(self) -> None:
        if self.source_timestamp.tzinfo is None or self.received_timestamp.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        if self.twap_60s <= 0:
            raise ValueError("twap_60s must be positive")


@dataclass(frozen=True)
class MarketRuleVersion:
    market_id: str
    condition_id: str
    resolution_source_url: str
    chainlink_stream_id: str
    fee_rule_version: str
    fee_schedule: dict[str, Any]
    market_schema_version: str
    tick_size: float
    minimum_order_size: float
    start_time: datetime
    end_time: datetime
    token_ids: dict[str, str]
    resolution_rule_hash: str = ""

    def __post_init__(self) -> None:
        if self.end_time <= self.start_time:
            raise ValueError("end_time must follow start_time")
        if not self.resolution_rule_hash:
            payload = {
                "source": self.resolution_source_url,
                "stream": self.chainlink_stream_id,
                "start": self.start_time.astimezone(timezone.utc).isoformat(),
                "end": self.end_time.astimezone(timezone.utc).isoformat(),
                "schema": self.market_schema_version,
                "tokens": self.token_ids,
                "condition_id": self.condition_id,
                "fee_rule_version": self.fee_rule_version,
                "fee_schedule": self.fee_schedule,
                "tick_size": self.tick_size,
                "minimum_order_size": self.minimum_order_size,
            }
            object.__setattr__(
                self,
                "resolution_rule_hash",
                sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
            )


@dataclass(frozen=True)
class BookLevel:
    price: float
    size: float


@dataclass(frozen=True)
class OrderBook:
    token_id: str
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
    timestamp: datetime

    @property
    def best_bid(self) -> float | None:
        return max((level.price for level in self.bids), default=None)

    @property
    def best_ask(self) -> float | None:
        return min((level.price for level in self.asks), default=None)

    @property
    def spread(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid

    @property
    def microprice(self) -> float | None:
        if not self.bids or not self.asks:
            return None
        bid = max(self.bids, key=lambda x: x.price)
        ask = min(self.asks, key=lambda x: x.price)
        total = bid.size + ask.size
        if total <= 0:
            return (bid.price + ask.price) / 2
        return (ask.price * bid.size + bid.price * ask.size) / total


@dataclass(frozen=True)
class ResolutionState:
    market_id: str
    start_price: float
    accumulated_price_time: float
    current_cumulative_twap: float | None
    remaining_duration: float
    required_remaining_twap: float | None
    required_future_twap_gap: float | None
    resolution_pressure: float | None
    provisional_resolution: Side | None
    resolution_confidence: float
    fraction_window_observed: float
    complete: bool
    no_trade_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class Regime:
    volatility: str
    trend: str
    liquidity: str
    time_of_day: str
    spread: str

    @property
    def key(self) -> str:
        return "|".join((self.volatility, self.trend, self.liquidity, self.time_of_day, self.spread))


@dataclass(frozen=True)
class ProbabilityEstimate:
    market_probability: float
    alpha_delta: float
    p_raw: float
    p_calibrated: float
    p_lower: float
    p_upper: float
    confidence: float
    ood_risk: float
    model_version: str

    def conservative(self, side: Side) -> float:
        return self.p_lower if side is Side.UP else 1.0 - self.p_upper


@dataclass(frozen=True)
class EdgeEstimate:
    side: Side
    raw_edge: float
    executable_edge: float
    net_edge: float
    risk_adjusted_edge: float
    conservative_net_edge: float
    executable_price: float
    fees: float
    slippage: float
    execution_risk_penalty: float


@dataclass(frozen=True)
class ExecutionDecision:
    kind: ExecutionKind
    side: Side | None
    price: float | None
    size: float
    expected_ev: float
    conservative_edge: float
    reasons: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
