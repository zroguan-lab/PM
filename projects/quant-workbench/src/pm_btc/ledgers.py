from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .domain import ExecutionDecision, ExecutionKind, Side


@dataclass(frozen=True)
class LedgerEntry:
    market_id: str
    timestamp: datetime
    side: Side | None
    decision: ExecutionKind
    unit_edge: float
    price: float
    notional: float
    filled: float
    realized_pnl: float | None = None
    reasons: tuple[str, ...] = ()


@dataclass
class ResearchLedger:
    entries: list[LedgerEntry] = field(default_factory=list)

    def record(self, market_id: str, timestamp: datetime, decision: ExecutionDecision) -> None:
        self.entries.append(
            LedgerEntry(
                market_id=market_id,
                timestamp=timestamp,
                side=decision.side,
                decision=decision.kind,
                unit_edge=decision.conservative_edge,
                price=decision.price or 0.0,
                notional=1.0,
                filled=1.0 if decision.kind is not ExecutionKind.NO_TRADE else 0.0,
                reasons=decision.reasons,
            )
        )


@dataclass
class RealisticPaperLedger:
    starting_cash: float
    cash: float | None = None
    entries: list[LedgerEntry] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.starting_cash <= 0:
            raise ValueError("starting_cash must be positive")
        if self.cash is None:
            self.cash = self.starting_cash

    def record_fill(
        self,
        market_id: str,
        timestamp: datetime,
        decision: ExecutionDecision,
        fill_fraction: float,
    ) -> LedgerEntry:
        price = decision.price or 0.0
        if price <= 0:
            affordable_shares = 0.0
        else:
            affordable_shares = min(decision.size, (self.cash or 0.0) / price)
        filled = affordable_shares * max(0.0, min(1.0, fill_fraction))
        self.cash = (self.cash or 0.0) - filled * price
        entry = LedgerEntry(
            market_id=market_id,
            timestamp=timestamp,
            side=decision.side,
            decision=decision.kind,
            unit_edge=decision.conservative_edge,
            price=decision.price or 0.0,
            notional=filled * price,
            filled=filled,
            reasons=decision.reasons,
        )
        self.entries.append(entry)
        return entry

    def settle(self, entry_index: int, won: bool) -> float:
        old = self.entries[entry_index]
        payout = old.filled if won else 0.0
        cost = old.filled * old.price
        pnl = payout - cost
        self.cash = (self.cash or 0.0) + payout
        self.entries[entry_index] = LedgerEntry(**{**old.__dict__, "realized_pnl": pnl})
        return pnl


@dataclass(frozen=True)
class CapacityPoint:
    capital: float
    executable_fraction: float
    average_slippage: float
    net_edge: float
    capacity_limited: bool


class CapacityLedger:
    DEFAULT_CAPITALS = (10.0, 50.0, 100.0, 500.0, 1000.0)

    def evaluate(self, available_notional: float, base_edge: float, impact_per_usdc: float) -> list[CapacityPoint]:
        points: list[CapacityPoint] = []
        for capital in self.DEFAULT_CAPITALS:
            executable = min(capital, available_notional)
            fraction = executable / capital
            slippage = impact_per_usdc * executable
            points.append(
                CapacityPoint(
                    capital=capital,
                    executable_fraction=fraction,
                    average_slippage=slippage,
                    net_edge=base_edge - slippage,
                    capacity_limited=fraction < 1.0,
                )
            )
        return points
