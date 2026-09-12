from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from .backtest import FillScenario, MakerFillInput, MakerFillSimulator
from .config import Settings
from .domain import BookLevel, OrderBook
from .edge import quote_taker
from .storage import SQLiteStore


def _book(raw: dict[str, Any]) -> OrderBook:
    return OrderBook(
        token_id=raw["token_id"],
        bids=tuple(BookLevel(float(level["price"]), float(level["size"])) for level in raw["bids"]),
        asks=tuple(BookLevel(float(level["price"]), float(level["size"])) for level in raw["asks"]),
        timestamp=datetime.fromisoformat(raw["source_timestamp"]),
    )


class PaperTradingRuntime:
    """Runs three counterfactual paper books; it never calls a live broker."""

    def __init__(self, settings: Settings, store: SQLiteStore) -> None:
        self.settings, self.store = settings, store
        self.simulator = MakerFillSimulator()
        self.store.initialize_paper_accounts(settings.paper_starting_cash)

    def create_from_next_signal(self) -> int:
        signal = self.store.next_paper_signal()
        if signal is None:
            return 0
        features = signal["features"]
        side = features.get("execution_side")
        price = features.get("execution_price")
        size = float(features.get("execution_size") or 0)
        if side not in ("UP", "DOWN") or price is None or size <= 0:
            self.store.audit("paper_signal_rejected", {"market_id": signal["market_id"], "reason": "invalid_order_intent"})
            return 0
        raw_book = self.store.latest_book_for_outcome(signal["market_id"], side)
        if raw_book is not None:
            book = _book(raw_book)
            best_ask = book.best_ask
            if best_ask is not None and best_ask > 0:
                for capital in (10.0, 50.0, 100.0, 500.0, 1000.0):
                    requested_shares = capital / best_ask
                    quote = quote_taker(book, requested_shares)
                    executable_fraction = quote.filled_size / requested_shares
                    self.store.save_capacity_point({
                        "market_id": signal["market_id"],
                        "prediction_timestamp": signal["prediction_timestamp"], "side": side,
                        "capital": capital, "executable_fraction": executable_fraction,
                        "average_price": quote.average_price,
                        "average_slippage": quote.slippage_per_share,
                        "net_edge": float(signal["conservative_edge"] or 0) - quote.slippage_per_share,
                        "capacity_limited": executable_fraction < 1.0 - 1e-12,
                    })
        created = 0
        for scenario in FillScenario:
            created += int(self.store.create_paper_order({
                "market_id": signal["market_id"], "prediction_timestamp": signal["prediction_timestamp"],
                "scenario": scenario.value, "kind": signal["kind"], "side": side,
                "limit_price": float(price), "requested_shares": size,
            }))
        return created

    def update_orders(self, now: datetime | None = None) -> dict[str, int]:
        now = now or datetime.now(timezone.utc)
        filled = cancelled = 0
        for order in self.store.open_paper_orders():
            raw = self.store.latest_book_for_outcome(order["market_id"], order["side"])
            if raw is None:
                continue
            book = _book(raw)
            if order["kind"] == "TAKER":
                quote = quote_taker(book, order["requested_shares"])
                if quote.filled_size > 0:
                    filled += int(self.store.fill_paper_order(
                        order["id"], quote.filled_size / order["requested_shares"],
                        quote.filled_size, quote.average_price,
                    ))
                    continue
            else:
                ask = book.best_ask
                touched = ask is not None and ask <= order["limit_price"]
                traded_through = ask is not None and ask < order["limit_price"]
                queue = sum(level.size for level in book.bids if abs(level.price - order["limit_price"]) < 1e-12)
                result = self.simulator.simulate(MakerFillInput(
                    limit_price=order["limit_price"], touched=touched,
                    traded_through=traded_through, queue_ahead=queue,
                    traded_volume_at_price=0.0, order_size=order["requested_shares"],
                    adverse_move=max(0.0, (order["limit_price"] - (book.best_bid or order["limit_price"]))),
                ), FillScenario(order["scenario"]))
                if result.filled_size > 0:
                    filled += int(self.store.fill_paper_order(
                        order["id"], result.fill_probability, result.filled_size, order["limit_price"],
                    ))
                    continue
            if now >= datetime.fromisoformat(order["end_time"]):
                self.store.cancel_paper_order(order["id"])
                cancelled += 1
        settled = self.store.settle_paper_orders()
        return {"filled": filled, "cancelled": cancelled, "settled": settled}

    async def run_forever(self) -> None:
        while True:
            try:
                self.create_from_next_signal()
                self.update_orders()
            except Exception as error:
                self.store.audit("paper_runtime_error", {"error": str(error)})
            await asyncio.sleep(self.settings.sync_interval_seconds)
