from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Callable

from websockets.asyncio.client import connect

from .config import Settings
from .storage import SQLiteStore


def _source_time(value: Any) -> datetime:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)
    if numeric > 10_000_000_000:
        numeric /= 1000
    return datetime.fromtimestamp(numeric, tz=timezone.utc)


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class BinanceWebSocketRuntime:
    """Archive official Binance streams and derive replayable order-flow features.

    Binance is feature-only. No value emitted by this runtime is used as a
    settlement label; Chainlink remains the sole label and resolution source.
    """

    def __init__(
        self,
        settings: Settings,
        store: SQLiteStore,
        connector: Callable[..., Any] = connect,
    ) -> None:
        self.settings = settings
        self.store = store
        self.connector = connector
        self._pending_events: list[dict[str, Any]] = []
        self._pending_hashes: set[str] = set()
        self._recent_hashes: set[str] = set()
        self._recent_order: deque[str] = deque()
        self._recent_limit = 100_000
        self._orderflow: dict[tuple[str, str], dict[str, Any]] = {}
        self._books: dict[str, dict[str, Any]] = {}
        self._stream_health: dict[str, dict[str, Any]] = {}
        self._last_book_saved_at: dict[str, datetime] = {}
        self._connection_established: dict[str, bool] = {}

    def stream_urls(self) -> dict[str, str]:
        return {name: candidates[0] for name, candidates in self.stream_url_candidates().items()}

    def stream_url_candidates(self) -> dict[str, tuple[str, ...]]:
        symbol = self.settings.binance_symbol.lower()
        return {
            "spot": tuple(
                self._combined_url(base, (
                    f"{symbol}@aggTrade", f"{symbol}@bookTicker", f"{symbol}@depth5@100ms",
                ))
                for base in (
                    self.settings.binance_spot_ws_base_url,
                    *self.settings.binance_spot_ws_fallback_urls,
                )
            ),
            "futures_public": (self._combined_url(
                self.settings.binance_futures_public_ws_base_url,
                (f"{symbol}@bookTicker", f"{symbol}@depth5@100ms"),
            ),),
            "futures_market": (self._combined_url(
                self.settings.binance_futures_market_ws_base_url,
                (f"{symbol}@aggTrade", f"{symbol}@markPrice@1s"),
            ),),
        }

    @staticmethod
    def _combined_url(base: str, streams: tuple[str, ...]) -> str:
        separator = "&" if "?" in base else "?"
        return f"{base.rstrip('/')}{separator}streams={'/'.join(streams)}"

    @staticmethod
    def _source(connection_name: str) -> str:
        return "SPOT" if connection_name == "spot" else "FUTURES"

    def _queue_raw_event(self, record: dict[str, Any]) -> bool:
        digest = str(record["event_hash"])
        if digest in self._pending_hashes or digest in self._recent_hashes:
            return False
        self._pending_events.append(record)
        self._pending_hashes.add(digest)
        return True

    def flush_raw_events(self) -> int:
        if not self._pending_events:
            return 0
        events = self._pending_events
        self._pending_events = []
        self._pending_hashes = set()
        saved = self.store.save_binance_ws_event_batch(events)
        for event in events:
            digest = str(event["event_hash"])
            if digest in self._recent_hashes:
                continue
            if len(self._recent_order) >= self._recent_limit:
                expired = self._recent_order.popleft()
                self._recent_hashes.discard(expired)
            self._recent_order.append(digest)
            self._recent_hashes.add(digest)
        return saved

    def flush_orderflow(self) -> int:
        flows = list(self._orderflow.values())
        self._orderflow = {}
        for flow in flows:
            self.store.upsert_binance_orderflow_second(flow)
        return len(flows)

    def flush(self) -> dict[str, int]:
        for health in self._stream_health.values():
            self.store.update_binance_ws_stream_health(health)
        return {
            "events_saved": self.flush_raw_events(),
            "orderflow_buckets_saved": self.flush_orderflow(),
            "streams_updated": len(self._stream_health),
        }

    def _aggregate_trade(
        self,
        source: str,
        timestamp: datetime,
        received: datetime,
        payload: dict[str, Any],
    ) -> None:
        price = float(payload["p"])
        quantity = float(payload["q"])
        taker_buy = not bool(payload.get("m"))
        bucket = timestamp.replace(microsecond=0).isoformat()
        key = (source, bucket)
        flow = self._orderflow.setdefault(key, {
            "source": source, "bucket_timestamp": bucket,
            "received_timestamp": received.isoformat(),
            "buy_quantity": 0.0, "sell_quantity": 0.0,
            "buy_notional": 0.0, "sell_notional": 0.0,
            "trade_count": 0, "last_price": price,
        })
        side = "buy" if taker_buy else "sell"
        flow[f"{side}_quantity"] += quantity
        flow[f"{side}_notional"] += price * quantity
        flow["trade_count"] += 1
        flow["last_price"] = price
        flow["received_timestamp"] = max(flow["received_timestamp"], received.isoformat())

    def _save_book_if_due(self, source: str) -> bool:
        state = self._books.get(source)
        if not state or any(float(state.get(key) or 0) <= 0 for key in ("best_bid", "best_ask")):
            return False
        if float(state["best_ask"]) < float(state["best_bid"]):
            return False
        now = datetime.now(timezone.utc)
        last = self._last_book_saved_at.get(source)
        if last is not None and (
            now - last
        ).total_seconds() < self.settings.binance_ws_book_snapshot_interval_seconds:
            return False
        values = {
            "source": source,
            "source_timestamp": state["source_timestamp"],
            "received_timestamp": state["received_timestamp"],
            "best_bid": float(state["best_bid"]), "best_ask": float(state["best_ask"]),
            "best_bid_size": float(state.get("best_bid_size") or 0),
            "best_ask_size": float(state.get("best_ask_size") or 0),
            "depth_bid_size": float(state.get("depth_bid_size") or state.get("best_bid_size") or 0),
            "depth_ask_size": float(state.get("depth_ask_size") or state.get("best_ask_size") or 0),
            "update_id": str(state.get("update_id") or ""),
        }
        values["snapshot_hash"] = _hash(values)
        saved = self.store.save_binance_ws_book_snapshot(values)
        if saved:
            self._last_book_saved_at[source] = now
        return saved

    def _update_book(
        self,
        source: str,
        stream: str,
        timestamp: datetime,
        received: datetime,
        payload: dict[str, Any],
    ) -> bool:
        state = self._books.setdefault(source, {})
        changed = False
        if "@bookTicker" in stream:
            state.update({
                "best_bid": float(payload["b"]), "best_ask": float(payload["a"]),
                "best_bid_size": float(payload["B"]), "best_ask_size": float(payload["A"]),
                "update_id": payload.get("u") or payload.get("lastUpdateId"),
            })
            changed = True
        elif "@depth" in stream:
            bids = payload.get("bids") if isinstance(payload.get("bids"), list) else payload.get("b")
            asks = payload.get("asks") if isinstance(payload.get("asks"), list) else payload.get("a")
            bids = bids or []
            asks = asks or []
            if bids and asks:
                state.update({
                    "best_bid": float(bids[0][0]), "best_ask": float(asks[0][0]),
                    "best_bid_size": float(bids[0][1]), "best_ask_size": float(asks[0][1]),
                    "depth_bid_size": sum(float(level[1]) for level in bids),
                    "depth_ask_size": sum(float(level[1]) for level in asks),
                    "update_id": payload.get("u") or payload.get("lastUpdateId"),
                })
                changed = True
        if not changed:
            return False
        state["source_timestamp"] = timestamp.isoformat()
        state["received_timestamp"] = received.isoformat()
        return self._save_book_if_due(source)

    def ingest_message(self, connection_name: str, message: str | bytes) -> dict[str, int]:
        if isinstance(message, bytes):
            message = message.decode("utf-8")
        envelope = json.loads(message)
        if not isinstance(envelope, dict):
            raise ValueError("Binance combined stream message must be an object")
        stream = str(envelope.get("stream") or "")
        payload = envelope.get("data", envelope)
        if not isinstance(payload, dict):
            raise ValueError("Binance stream data must be an object")
        received = datetime.now(timezone.utc)
        timestamp = _source_time(payload.get("E") or payload.get("T"))
        source = self._source(connection_name)
        digest = _hash({"connection": connection_name, "stream": stream, "data": payload})
        self._stream_health[connection_name] = {
            "connection_name": connection_name, "last_stream": stream,
            "last_source_timestamp": timestamp.isoformat(),
            "last_received_timestamp": received.isoformat(),
        }
        queued = self._queue_raw_event({
            "event_hash": digest, "connection": connection_name, "stream": stream,
            "source": source, "source_timestamp": timestamp.isoformat(),
            "received_timestamp": received.isoformat(), "raw": envelope,
        })
        trades = 0
        books = 0
        event_type = str(payload.get("e") or "")
        if queued and (event_type == "aggTrade" or "@aggTrade" in stream):
            self._aggregate_trade(source, timestamp, received, payload)
            trades = 1
        if queued and ("@bookTicker" in stream or "@depth" in stream):
            books = int(self._update_book(source, stream, timestamp, received, payload))
        return {"events_queued": int(queued), "trades_aggregated": trades, "books_saved": books}

    async def _run_connection(self, name: str, url: str) -> None:
        async with self.connector(
            url, ping_interval=None, open_timeout=10, close_timeout=5,
            max_size=4 * 1024 * 1024,
            # Keep the official environment proxy/TLS path available. Some
            # networks can reach Binance futures only through that route.
            proxy=True,
        ) as websocket:
            self._connection_established[name] = True
            self.store.audit("binance_ws_connected", {"connection": name, "url": url.split("?")[0]})
            async for message in websocket:
                self.ingest_message(name, message)
        raise ConnectionError(f"Binance {name} WebSocket closed")

    async def _connection_forever(self, name: str, urls: str | tuple[str, ...]) -> None:
        candidates = (urls,) if isinstance(urls, str) else tuple(dict.fromkeys(urls))
        if not candidates:
            raise ValueError(f"Binance {name} has no WebSocket endpoint candidates")
        delay = 1.0
        candidate_index = 0
        while True:
            self._connection_established[name] = False
            url = candidates[candidate_index]
            try:
                await self._run_connection(name, url)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                established = self._connection_established.get(name, False)
                retry_seconds = 1.0 if established else delay
                if not established and len(candidates) > 1:
                    candidate_index = (candidate_index + 1) % len(candidates)
                    # Try each official route promptly; only back off after a full cycle.
                    retry_seconds = 1.0
                    if candidate_index == 0:
                        delay = min(delay * 2, 30.0)
                self.store.audit("binance_ws_error", {
                    "connection": name, "endpoint": url.split("?")[0],
                    "error": str(error), "retry_seconds": retry_seconds,
                })
                await asyncio.sleep(retry_seconds)
                if established:
                    delay = 1.0

    async def _flush_forever(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.settings.binance_ws_raw_batch_interval_seconds)
                self.flush()
        finally:
            self.flush()

    async def run_forever(self) -> None:
        urls = self.stream_url_candidates()
        await asyncio.gather(
            *(self._connection_forever(name, url) for name, url in urls.items()),
            self._flush_forever(),
        )

    async def collect_for(self, seconds: float) -> dict[str, int]:
        before = self.store.sync_status()
        task = asyncio.create_task(self.run_forever())
        try:
            await asyncio.wait_for(task, timeout=seconds)
        except TimeoutError:
            pass
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self.flush()
        after = self.store.sync_status()
        return {
            "events_saved": after["binance_ws_events"] - before["binance_ws_events"],
            "trades_saved": after["binance_ws_trades"] - before["binance_ws_trades"],
            "books_saved": after["binance_ws_book_snapshots"] - before["binance_ws_book_snapshots"],
        }
