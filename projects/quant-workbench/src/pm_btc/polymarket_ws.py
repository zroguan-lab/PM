from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any, Callable

from websockets.asyncio.client import connect

from .config import Settings
from .domain import BookLevel, OrderBook
from .storage import SQLiteStore
from .trusted_dns import TrustedDnsResolver


def _source_time(value: Any) -> datetime:
    try:
        numeric = int(str(value))
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)
    if numeric > 10_000_000_000:
        numeric /= 1000
    return datetime.fromtimestamp(numeric, tz=timezone.utc)


def _event_hash(payload: dict[str, Any]) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class PolymarketClobWebSocketRuntime:
    """Archives and reconstructs the official public CLOB market stream."""

    def __init__(
        self,
        settings: Settings,
        store: SQLiteStore,
        connector: Callable[..., Any] = connect,
        resolver: TrustedDnsResolver | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.connector = connector
        self.resolver = resolver
        self._token_meta: dict[str, dict[str, Any]] = {}
        self._books: dict[str, dict[str, dict[str, str]]] = {}
        self._last_book_saved_at: dict[str, datetime] = {}
        self._pending_events: list[dict[str, Any]] = []
        self._pending_event_hashes: set[str] = set()
        self._recent_event_hashes: set[str] = set()
        self._recent_event_order: deque[str] = deque()
        self._recent_event_limit = 50_000
        self._connection_established = False
        self._route = "ambient_proxy"

    def _refresh_token_metadata(self, now: datetime | None = None) -> set[str]:
        now = now or datetime.now(timezone.utc)
        rows = self.store.polymarket_stream_tokens(
            now.isoformat(),
            (now + timedelta(minutes=5)).isoformat(),
        )
        self._token_meta = {str(item["token_id"]): item for item in rows}
        return set(self._token_meta)

    def _seed_book_from_store(self, token_id: str) -> dict[str, dict[str, str]] | None:
        meta = self._token_meta.get(token_id)
        if meta is None:
            return None
        saved = self.store.latest_book_for_outcome(meta["market_id"], meta["outcome"])
        if saved is None:
            return None
        state = {
            "bids": {str(item["price"]): str(item["size"]) for item in saved["bids"]},
            "asks": {str(item["price"]): str(item["size"]) for item in saved["asks"]},
        }
        self._books[token_id] = state
        return state

    @staticmethod
    def _book_payload(state: dict[str, dict[str, str]], event_hash: str) -> dict[str, Any]:
        return {
            "bids": [
                {"price": price, "size": size}
                for price, size in sorted(state["bids"].items(), key=lambda item: float(item[0]), reverse=True)
            ],
            "asks": [
                {"price": price, "size": size}
                for price, size in sorted(state["asks"].items(), key=lambda item: float(item[0]))
            ],
            "hash": f"ws-{event_hash}",
        }

    def _save_book(self, token_id: str, timestamp: datetime, event_hash: str) -> bool:
        meta = self._token_meta.get(token_id)
        state = self._books.get(token_id)
        if meta is None or state is None:
            return False
        saved_at = self._last_book_saved_at.get(token_id)
        current = datetime.now(timezone.utc)
        if saved_at is not None and (
            current - saved_at
        ).total_seconds() < self.settings.polymarket_ws_book_snapshot_interval_seconds:
            return False
        raw = self._book_payload(state, event_hash)
        book = OrderBook(
            token_id=token_id,
            bids=tuple(BookLevel(float(item["price"]), float(item["size"])) for item in raw["bids"]),
            asks=tuple(BookLevel(float(item["price"]), float(item["size"])) for item in raw["asks"]),
            timestamp=timestamp,
        )
        saved = self.store.save_orderbook(meta["market_id"], meta["outcome"], book, raw)
        if saved:
            self._last_book_saved_at[token_id] = current
        return saved

    def _queue_raw_event(self, event: dict[str, Any]) -> bool:
        digest = str(event["event_hash"])
        if digest in self._pending_event_hashes or digest in self._recent_event_hashes:
            return False
        self._pending_events.append(event)
        self._pending_event_hashes.add(digest)
        return True

    def flush_raw_events(self) -> int:
        if not self._pending_events:
            return 0
        events = self._pending_events
        self._pending_events = []
        self._pending_event_hashes = set()
        saved = self.store.save_polymarket_clob_event_batch(events)
        for event in events:
            digest = str(event["event_hash"])
            if digest in self._recent_event_hashes:
                continue
            if len(self._recent_event_order) >= self._recent_event_limit:
                expired = self._recent_event_order.popleft()
                self._recent_event_hashes.discard(expired)
            self._recent_event_order.append(digest)
            self._recent_event_hashes.add(digest)
        return saved

    def ingest_event(self, payload: dict[str, Any], archive_immediately: bool = True) -> dict[str, int]:
        if not isinstance(payload, dict):
            raise ValueError("Polymarket CLOB event must be an object")
        event_type = str(payload.get("event_type") or "unknown")
        timestamp = _source_time(payload.get("timestamp"))
        received = datetime.now(timezone.utc)
        digest = _event_hash(payload)
        asset_id = str(payload.get("asset_id") or "")
        if not asset_id and event_type == "price_change":
            changes = payload.get("price_changes") or []
            if changes:
                asset_id = str(changes[0].get("asset_id") or "")
        meta = self._token_meta.get(asset_id)
        condition_id = str(payload.get("market") or (meta or {}).get("condition_id") or "")
        event_record = {
            "event_hash": digest, "event_type": event_type,
            "market_id": (meta or {}).get("market_id"), "condition_id": condition_id or None,
            "asset_id": asset_id or None, "source_timestamp": timestamp.isoformat(),
            "received_timestamp": received.isoformat(), "raw": payload,
        }
        saved_event = (
            self.store.save_polymarket_clob_event(event_record)
            if archive_immediately else self._queue_raw_event(event_record)
        )
        books_saved = 0
        trades_saved = 0
        if event_type == "book" and asset_id:
            self._books[asset_id] = {
                "bids": {str(item["price"]): str(item["size"]) for item in payload.get("bids", [])},
                "asks": {str(item["price"]): str(item["size"]) for item in payload.get("asks", [])},
            }
            books_saved += int(self._save_book(asset_id, timestamp, digest))
        elif event_type == "price_change":
            changed_tokens: set[str] = set()
            for change in payload.get("price_changes") or []:
                token_id = str(change.get("asset_id") or "")
                if not token_id:
                    continue
                state = self._books.get(token_id) or self._seed_book_from_store(token_id)
                if state is None:
                    continue
                side = str(change.get("side") or "").upper()
                levels = state["bids"] if side == "BUY" else state["asks"] if side == "SELL" else None
                if levels is None:
                    continue
                price = str(change["price"])
                size = str(change["size"])
                if float(size) <= 0:
                    levels.pop(price, None)
                else:
                    levels[price] = size
                changed_tokens.add(token_id)
            for token_id in changed_tokens:
                books_saved += int(self._save_book(token_id, timestamp, f"{digest}-{token_id}"))
        elif event_type == "last_trade_price" and meta is not None:
            trades_saved += int(self.store.save_polymarket_clob_trade({
                "event_hash": digest, "market_id": meta["market_id"],
                "condition_id": condition_id, "asset_id": asset_id,
                "outcome": meta["outcome"], "price": float(payload["price"]),
                "size": float(payload["size"]), "side": str(payload["side"]).upper(),
                "fee_rate_bps": float(payload.get("fee_rate_bps") or 0),
                "transaction_hash": payload.get("transaction_hash"),
                "source_timestamp": timestamp.isoformat(), "received_timestamp": received.isoformat(),
            }))
        return {"events_saved": int(saved_event), "books_saved": books_saved, "trades_saved": trades_saved}

    def ingest_message(self, message: str | bytes, archive_immediately: bool = True) -> dict[str, int]:
        if isinstance(message, bytes):
            message = message.decode("utf-8")
        if message == "PONG":
            return {"events_saved": 0, "books_saved": 0, "trades_saved": 0}
        decoded = json.loads(message)
        events = decoded if isinstance(decoded, list) else [decoded]
        totals = {"events_saved": 0, "books_saved": 0, "trades_saved": 0}
        for event in events:
            result = self.ingest_event(event, archive_immediately=archive_immediately)
            for key in totals:
                totals[key] += result[key]
        return totals

    async def _run_connection(self) -> None:
        tokens = self._refresh_token_metadata()
        if not tokens:
            self.store.audit("polymarket_clob_ws_waiting_for_markets", {})
            await asyncio.sleep(1.0)
            return
        connection_kwargs: dict[str, Any] = {
            "proxy": True if self._route == "ambient_proxy" else None,
        }
        resolved_address = None
        trusted_dns = self.resolver is not None and self._route == "trusted_dns"
        if trusted_dns:
            try:
                target = await self.resolver.resolve_websocket(self.settings.polymarket_clob_ws_url)
                connection_kwargs = target.connection_kwargs()
                resolved_address = target.address
            except Exception as error:
                self.store.audit("polymarket_clob_ws_trusted_dns_error", {"error": str(error)})
                trusted_dns = False
        async with self.connector(
            self.settings.polymarket_clob_ws_url,
            ping_interval=None,
            open_timeout=10,
            close_timeout=5,
            max_size=8 * 1024 * 1024,
            **connection_kwargs,
        ) as websocket:
            self._connection_established = True
            await websocket.send(json.dumps({
                "assets_ids": sorted(tokens), "type": "market",
                "initial_dump": True, "level": 2, "custom_feature_enabled": True,
            }))
            subscribed = set(tokens)
            self.store.audit("polymarket_clob_ws_connected", {
                "assets": len(subscribed),
                "resolved_address": resolved_address,
                "route": "trusted_dns" if trusted_dns else self._route,
                "trusted_dns": trusted_dns,
            })
            loop = asyncio.get_running_loop()
            next_ping = loop.time() + self.settings.polymarket_ws_heartbeat_seconds
            next_refresh = loop.time() + self.settings.polymarket_ws_subscription_refresh_seconds
            next_flush = loop.time() + self.settings.polymarket_ws_raw_batch_interval_seconds
            last_received = loop.time()
            try:
                while True:
                    timeout = max(0.1, min(next_ping, next_refresh, next_flush) - loop.time())
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=timeout)
                    except TimeoutError:
                        message = None
                    if message is not None:
                        self.ingest_message(message, archive_immediately=False)
                        last_received = loop.time()
                    current = loop.time()
                    if current >= next_flush:
                        self.flush_raw_events()
                        next_flush = current + self.settings.polymarket_ws_raw_batch_interval_seconds
                    if current >= next_ping:
                        await websocket.send("PING")
                        next_ping = current + self.settings.polymarket_ws_heartbeat_seconds
                    if current >= next_refresh:
                        wanted = self._refresh_token_metadata()
                        added, removed = wanted - subscribed, subscribed - wanted
                        if added:
                            await websocket.send(json.dumps({
                                "operation": "subscribe", "assets_ids": sorted(added),
                                "level": 2, "custom_feature_enabled": True,
                            }))
                        if removed:
                            await websocket.send(json.dumps({
                                "operation": "unsubscribe", "assets_ids": sorted(removed),
                            }))
                            for token_id in removed:
                                self._books.pop(token_id, None)
                        if added or removed:
                            self.store.audit("polymarket_clob_ws_subscription_updated", {
                                "added": len(added), "removed": len(removed), "assets": len(wanted),
                            })
                        subscribed = wanted
                        next_refresh = current + self.settings.polymarket_ws_subscription_refresh_seconds
                    if current - last_received > self.settings.polymarket_ws_heartbeat_seconds * 3:
                        raise TimeoutError("Polymarket CLOB WebSocket heartbeat timed out")
            finally:
                self.flush_raw_events()

    async def run_forever(self) -> None:
        delay = 1.0
        while True:
            self._connection_established = False
            try:
                await self._run_connection()
                delay = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as error:
                retry_seconds = 1.0 if self._connection_established else delay
                self.store.audit("polymarket_clob_ws_error", {
                    "error": str(error),
                    "retry_seconds": retry_seconds,
                    "route": self._route,
                })
                if not self._connection_established and self.resolver is not None:
                    self._route = {
                        "ambient_proxy": "trusted_dns",
                        "trusted_dns": "direct",
                        "direct": "ambient_proxy",
                    }.get(self._route, "ambient_proxy")
                    self.store.audit("polymarket_clob_ws_route_fallback", {
                        "next_route": self._route,
                    })
                    retry_seconds = min(retry_seconds, 1.0)
                await asyncio.sleep(retry_seconds)
                delay = 1.0 if self._connection_established else min(delay * 2, 30.0)

    async def collect_for(self, seconds: float) -> dict[str, int]:
        before = self.store.sync_status()
        try:
            await asyncio.wait_for(self._run_connection(), timeout=seconds)
        except TimeoutError:
            pass
        after = self.store.sync_status()
        return {
            "events_saved": after["polymarket_clob_events"] - before["polymarket_clob_events"],
            "trades_saved": after["polymarket_clob_trades"] - before["polymarket_clob_trades"],
            "books_saved": after["orderbook_snapshots"] - before["orderbook_snapshots"],
        }
