from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from .domain import OrderBook, Side


@dataclass(frozen=True)
class Eligibility:
    allowed: bool
    read_only: bool
    reasons: tuple[str, ...]
    country: str | None = None
    region: str | None = None


class PolymarketBroker(ABC):
    @abstractmethod
    async def discover_markets(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def get_market_rules(self, market_id: str) -> dict[str, Any]: ...

    @abstractmethod
    async def get_order_book(self, token_id: str) -> OrderBook: ...

    @abstractmethod
    async def estimate_taker_fill(self, token_id: str, size: float) -> dict[str, float]: ...

    @abstractmethod
    async def place_limit_order(self, token_id: str, side: Side, price: float, size: float) -> str: ...

    @abstractmethod
    async def place_market_order(self, token_id: str, side: Side, size: float) -> str: ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> None: ...

    @abstractmethod
    async def cancel_all(self) -> None: ...

    @abstractmethod
    async def get_orders(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def get_fills(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def get_positions(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def get_balances(self) -> dict[str, float]: ...

    @abstractmethod
    async def get_fee_schedule(self, market_id: str) -> dict[str, Any]: ...

    @abstractmethod
    async def check_eligibility(self) -> Eligibility: ...

    @abstractmethod
    async def redeem_positions(self, market_id: str) -> str: ...


class ReadOnlyOfficialPolymarketBroker(PolymarketBroker):
    """Safe default adapter. Live mutation is impossible until an SDK client is injected."""

    def __init__(self, public_client: Any | None = None, live_client: Any | None = None) -> None:
        self.public_client = public_client
        self.live_client = live_client

    def _require_public(self) -> Any:
        if self.public_client is None:
            raise RuntimeError("official Polymarket public SDK client is not configured")
        return self.public_client

    def _require_live(self) -> Any:
        if self.live_client is None:
            raise PermissionError("broker is READ_ONLY; live SDK client and eligibility are required")
        return self.live_client

    async def discover_markets(self) -> list[dict[str, Any]]:
        result = self._require_public().get_markets()
        return list(result)

    async def get_market_rules(self, market_id: str) -> dict[str, Any]:
        return dict(self._require_public().get_market(market_id))

    async def get_order_book(self, token_id: str) -> OrderBook:
        raise NotImplementedError("map the active official SDK OrderBook type at the adapter boundary")

    async def estimate_taker_fill(self, token_id: str, size: float) -> dict[str, float]:
        return dict(self._require_public().calculate_market_price(token_id, "BUY", size))

    async def place_limit_order(self, token_id: str, side: Side, price: float, size: float) -> str:
        client = self._require_live()
        result = client.create_and_post_order(token_id=token_id, side=side.value, price=price, size=size)
        return str(result["orderID"])

    async def place_market_order(self, token_id: str, side: Side, size: float) -> str:
        client = self._require_live()
        result = client.create_and_post_market_order(token_id=token_id, side=side.value, amount=size)
        return str(result["orderID"])

    async def cancel_order(self, order_id: str) -> None:
        self._require_live().cancel_order(order_id)

    async def cancel_all(self) -> None:
        self._require_live().cancel_all()

    async def get_orders(self) -> list[dict[str, Any]]:
        return list(self._require_live().get_open_orders())

    async def get_fills(self) -> list[dict[str, Any]]:
        return list(self._require_live().get_trades())

    async def get_positions(self) -> list[dict[str, Any]]:
        raise NotImplementedError("positions require the official Data API adapter")

    async def get_balances(self) -> dict[str, float]:
        return dict(self._require_live().get_balance_allowance())

    async def get_fee_schedule(self, market_id: str) -> dict[str, Any]:
        return dict(self._require_public().get_clob_market_info(market_id))

    async def check_eligibility(self) -> Eligibility:
        if self.live_client is None:
            return Eligibility(False, True, ("live_client_not_configured",))
        return Eligibility(True, False, ())

    async def redeem_positions(self, market_id: str) -> str:
        raise NotImplementedError("redemption is intentionally disabled until the wallet adapter is configured")


class PaperBroker(PolymarketBroker):
    def __init__(self, books: dict[str, OrderBook] | None = None, eligible: bool = True) -> None:
        self.books = books or {}
        self.eligible = eligible
        self.orders: list[dict[str, Any]] = []

    async def discover_markets(self) -> list[dict[str, Any]]: return []
    async def get_market_rules(self, market_id: str) -> dict[str, Any]: return {"market_id": market_id}
    async def get_order_book(self, token_id: str) -> OrderBook: return self.books[token_id]
    async def estimate_taker_fill(self, token_id: str, size: float) -> dict[str, float]: return {"size": size}

    async def place_limit_order(self, token_id: str, side: Side, price: float, size: float) -> str:
        order_id = f"paper-{len(self.orders)+1}"
        self.orders.append({"id": order_id, "token_id": token_id, "side": side.value, "price": price, "size": size})
        return order_id

    async def place_market_order(self, token_id: str, side: Side, size: float) -> str:
        return await self.place_limit_order(token_id, side, self.books[token_id].best_ask or 1.0, size)

    async def cancel_order(self, order_id: str) -> None:
        self.orders = [order for order in self.orders if order["id"] != order_id]

    async def cancel_all(self) -> None: self.orders.clear()
    async def get_orders(self) -> list[dict[str, Any]]: return list(self.orders)
    async def get_fills(self) -> list[dict[str, Any]]: return []
    async def get_positions(self) -> list[dict[str, Any]]: return []
    async def get_balances(self) -> dict[str, float]: return {"paper": 0.0}
    async def get_fee_schedule(self, market_id: str) -> dict[str, Any]: return {"rate": 0.07}
    async def check_eligibility(self) -> Eligibility: return Eligibility(self.eligible, not self.eligible, () if self.eligible else ("paper_ineligible",))
    async def redeem_positions(self, market_id: str) -> str: return f"paper-redeem-{market_id}"


class ReplayBroker(PaperBroker):
    """Deterministic broker used by event replay backtests."""

