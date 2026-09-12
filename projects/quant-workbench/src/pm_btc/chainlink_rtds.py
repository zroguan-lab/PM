from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from typing import Any, AsyncIterator, Callable

from websockets.asyncio.client import connect

from .domain import CHAINLINK_BTC_USD_TWAP_60S_STREAM_ID, ChainlinkObservation, VerificationStatus
from .storage import SQLiteStore
from .trusted_dns import TrustedDnsResolver


def _as_utc(timestamp: Any) -> datetime:
    if isinstance(timestamp, datetime):
        value = timestamp
    else:
        numeric = int(timestamp)
        if numeric > 10_000_000_000:
            numeric /= 1000
        value = datetime.fromtimestamp(numeric, tz=timezone.utc)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class PolymarketChainlinkRtdsRuntime:
    """Archives Polymarket's official credential-free relay of Chainlink 60s TWAP."""

    stream_id = CHAINLINK_BTC_USD_TWAP_60S_STREAM_ID

    def __init__(
        self, store: SQLiteStore, stream_factory: Callable[[], Any] | None = None,
        heartbeat_timeout_seconds: float = 90.0,
        resolver: TrustedDnsResolver | None = None,
        connector: Callable[..., Any] = connect,
        websocket_url: str = "wss://ws-live-data.polymarket.com",
    ) -> None:
        self.store = store
        self.stream_factory = stream_factory
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self.resolver = resolver
        self.connector = connector
        self.websocket_url = websocket_url
        # The official SDK keeps the platform's proxy/TLS behavior intact and is
        # therefore the primary route.  Manual socket routes are recovery paths.
        self._route = "official_sdk"

    def ingest_event(self, event: Any) -> dict[str, int]:
        payload = event.payload if hasattr(event, "payload") else event["payload"]
        get = (lambda name: getattr(payload, name)) if not isinstance(payload, dict) else payload.__getitem__
        symbol = str(get("symbol")).lower()
        window = int(get("window_seconds") if not isinstance(payload, dict) else payload.get("window_seconds", payload.get("window_s")))
        if symbol != "btc/usd" or window != 60:
            return {"matched_markets": 0, "saved": 0}
        observed_at = _as_utc(get("timestamp"))
        exact_value = str(get("value"))
        if Decimal(exact_value) <= 0:
            raise ValueError("Chainlink TWAP must be positive")
        raw = event if isinstance(event, dict) else (
            event.model_dump(mode="json") if hasattr(event, "model_dump") else canonical_event(event)
        )
        canonical = {
            "topic": getattr(event, "topic", None) if not isinstance(event, dict) else event.get("topic"),
            "symbol": symbol, "window_seconds": window,
            "timestamp": observed_at.isoformat(), "value": exact_value,
        }
        payload_hash = sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
        markets = self.store.markets_for_chainlink_timestamp(observed_at.isoformat())
        saved = 0
        received_at = datetime.now(timezone.utc)
        self.store.save_chainlink_rtds_event({
            "raw_payload_hash": payload_hash, "topic": canonical["topic"] or "crypto_prices_twap_sixty",
            "symbol": symbol, "window_seconds": window,
            "source_timestamp": observed_at.isoformat(), "received_timestamp": received_at.isoformat(),
            "exact_value": exact_value, "raw": raw,
        })
        for market in markets:
            before = self.store.connection.total_changes
            self.store.save_chainlink(ChainlinkObservation(
                stream_id=self.stream_id,
                source_timestamp=observed_at,
                received_timestamp=received_at,
                twap_60s=float(Decimal(exact_value)),
                report_id=f"rtds-{payload_hash}",
                verification_status=VerificationStatus.VERIFIED,
                raw_payload_hash=payload_hash,
                market_id=market["market_id"],
            ))
            saved += int(self.store.connection.total_changes > before)
        return {"matched_markets": len(markets), "saved": saved}

    async def _official_stream(self) -> AsyncIterator[Any]:
        from polymarket import AsyncPublicClient
        from polymarket.streams import CryptoPricesChainlinkTwapSpec

        async with AsyncPublicClient() as client:
            async with await client.subscribe(CryptoPricesChainlinkTwapSpec(
                window_seconds=60, symbols=["btc/usd"],
            )) as stream:
                async for event in stream:
                    yield event

    async def _websocket_stream(self, trusted_dns: bool) -> AsyncIterator[Any]:
        from polymarket.models.rtds_events import parse_rtds_event

        connection_kwargs: dict[str, Any] = {"proxy": None}
        resolved_address = None
        if trusted_dns:
            target = await self.resolver.resolve_websocket(self.websocket_url)  # type: ignore[union-attr]
            connection_kwargs = target.connection_kwargs()
            resolved_address = target.address
        async with self.connector(
            self.websocket_url,
            ping_interval=None,
            open_timeout=10,
            close_timeout=5,
            max_size=2 * 1024 * 1024,
            **connection_kwargs,
        ) as websocket:
            self.store.audit("chainlink_rtds_connected", {
                "resolved_address": resolved_address,
                "route": "trusted_dns" if trusted_dns else "direct",
                "trusted_dns": trusted_dns,
            })
            await websocket.send(json.dumps({
                "action": "subscribe",
                "subscriptions": [{"topic": "crypto_prices_twap_sixty", "type": "update"}],
            }))
            loop = asyncio.get_running_loop()
            last_received = loop.time()
            next_ping = loop.time() + 5.0
            while True:
                timeout = max(0.1, min(next_ping - loop.time(), self.heartbeat_timeout_seconds))
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=timeout)
                except TimeoutError:
                    message = None
                current = loop.time()
                if message is not None:
                    last_received = current
                    if isinstance(message, bytes):
                        message = message.decode("utf-8")
                    if message != "PONG":
                        raw = json.loads(message)
                        event = parse_rtds_event(raw)
                        payload = event.payload
                        if payload.symbol == "btc/usd" and payload.window_seconds == 60:
                            yield event
                if current >= next_ping:
                    await websocket.send("PING")
                    next_ping = current + 5.0
                if current - last_received > self.heartbeat_timeout_seconds:
                    raise TimeoutError("Polymarket Chainlink RTDS heartbeat timed out")

    async def _trusted_resolved_stream(self) -> AsyncIterator[Any]:
        async for event in self._websocket_stream(trusted_dns=True):
            yield event

    async def _direct_stream(self) -> AsyncIterator[Any]:
        async for event in self._websocket_stream(trusted_dns=False):
            yield event

    async def run_forever(self) -> None:
        delay = 1.0
        while True:
            try:
                if self.stream_factory:
                    source = self.stream_factory()
                    route = "custom"
                elif self._route == "official_sdk":
                    source = self._official_stream()
                    route = "official_sdk"
                elif self._route == "trusted_dns" and self.resolver is not None:
                    source = self._trusted_resolved_stream()
                    route = "trusted_dns"
                else:
                    source = self._direct_stream()
                    route = "direct"
                iterator = source.__aiter__()
                while True:
                    try:
                        event = await asyncio.wait_for(
                            iterator.__anext__(), timeout=self.heartbeat_timeout_seconds,
                        )
                    except StopAsyncIteration:
                        self.store.audit("chainlink_rtds_stream_ended", {"retry_seconds": delay})
                        await asyncio.sleep(delay)
                        delay = min(delay * 2, 30.0)
                        break
                    self.ingest_event(event)
                    delay = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as error:
                retry_seconds = delay
                self.store.audit("chainlink_rtds_error", {
                    "error": str(error),
                    "retry_seconds": retry_seconds,
                    "route": locals().get("route", "unknown"),
                })
                if self.stream_factory is None and self.resolver is not None:
                    self._route = {
                        "official_sdk": "trusted_dns",
                        "trusted_dns": "direct",
                        "direct": "official_sdk",
                    }.get(locals().get("route", "official_sdk"), "official_sdk")
                    self.store.audit("chainlink_rtds_route_fallback", {
                        "next_route": self._route,
                    })
                    retry_seconds = min(retry_seconds, 1.0)
                await asyncio.sleep(retry_seconds)
                delay = min(delay * 2, 30.0)


def canonical_event(event: Any) -> dict[str, Any]:
    payload = event.payload
    return {
        "topic": getattr(event, "topic", None), "type": getattr(event, "type", None),
        "timestamp": str(getattr(event, "timestamp", "")),
        "payload": {
            "symbol": str(payload.symbol), "timestamp": payload.timestamp,
            "value": str(payload.value), "window_seconds": payload.window_seconds,
        },
    }
