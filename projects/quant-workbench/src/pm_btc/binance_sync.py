from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any
from urllib.error import HTTPError, URLError

import httpx

from .config import Settings
from .polymarket_sync import JsonGetter
from .storage import SQLiteStore


def _mid(bid: float, ask: float) -> float:
    if bid <= 0 or ask <= 0 or ask < bid:
        raise ValueError("invalid Binance quote")
    return (bid + ask) / 2.0


def _imbalance(depth: dict[str, Any]) -> float | None:
    bid_size = sum(float(level[1]) for level in depth.get("bids", []))
    ask_size = sum(float(level[1]) for level in depth.get("asks", []))
    total = bid_size + ask_size
    return (bid_size - ask_size) / total if total > 0 else None


@dataclass(frozen=True)
class BinanceFeatureSnapshot:
    values: dict[str, Any]

    def storage_record(self) -> dict[str, Any]:
        return self.values


class BinanceHttpClient:
    """Public market-data client. Its output is feature-only and never a label."""

    def __init__(self, settings: Settings, getter: JsonGetter | None = None) -> None:
        self.settings = settings
        self._http = None if getter is not None else httpx.Client(
            timeout=httpx.Timeout(5.0),
            headers={"Accept": "application/json", "User-Agent": "pm-btc/0.1"},
        )
        self.getter = getter or self._httpx_get
        self._preferred_bases = {
            "spot": settings.binance_spot_base_url.rstrip("/"),
            "futures": settings.binance_futures_base_url.rstrip("/"),
        }

    def _httpx_get(self, url: str, params: dict[str, str] | None = None) -> dict[str, Any] | list[Any]:
        if self._http is None:
            raise RuntimeError("Binance HTTP client is not initialized")
        response = self._http.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def _bases(self, product: str) -> list[str]:
        if product == "spot":
            configured = (self.settings.binance_spot_base_url, *self.settings.binance_spot_fallback_urls)
        elif product == "futures":
            configured = (self.settings.binance_futures_base_url, *self.settings.binance_futures_fallback_urls)
        else:
            raise ValueError(f"unknown Binance product: {product}")
        ordered = (self._preferred_bases[product], *configured)
        return list(dict.fromkeys(value.rstrip("/") for value in ordered if value))

    def _get(self, product: str, path: str, params: dict[str, str]) -> tuple[dict[str, Any] | list[Any], str]:
        errors: list[str] = []
        for base_url in self._bases(product):
            try:
                value = self.getter(f"{base_url}{path}", params)
                self._preferred_bases[product] = base_url
                return value, base_url
            except HTTPError as error:
                # Never rotate hosts to evade bans, WAF blocks, client errors, or rate limits.
                if error.code < 500:
                    raise
                errors.append(f"{base_url}: HTTP {error.code}")
            except httpx.HTTPStatusError as error:
                status_code = error.response.status_code
                if status_code < 500:
                    raise
                errors.append(f"{base_url}: HTTP {status_code}")
            except (httpx.TransportError, URLError, TimeoutError, ConnectionError, OSError) as error:
                errors.append(f"{base_url}: {type(error).__name__}: {error}")
        detail = "; ".join(errors) or "no endpoints configured"
        raise ConnectionError(f"all official Binance {product} endpoints failed: {detail}")

    def snapshot(self) -> BinanceFeatureSnapshot:
        symbol = self.settings.binance_symbol
        # Probe each product concurrently so failover selects one healthy base, then
        # reuse those sticky bases for the remaining independent public requests.
        # This avoids opening six simultaneous TLS paths, which is less stable on
        # some networks than two small request waves.
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="binance-snapshot") as executor:
            spot_quote_future = executor.submit(
                self._get, "spot", "/api/v3/ticker/bookTicker", {"symbol": symbol}
            )
            futures_quote_future = executor.submit(
                self._get, "futures", "/fapi/v1/ticker/bookTicker", {"symbol": symbol}
            )
            spot_quote, spot_quote_base = spot_quote_future.result()
            futures_quote, futures_quote_base = futures_quote_future.result()
            remaining = {
                "spot_depth": executor.submit(
                    self._get, "spot", "/api/v3/depth", {"symbol": symbol, "limit": "20"}
                ),
                "futures_depth": executor.submit(
                    self._get, "futures", "/fapi/v1/depth", {"symbol": symbol, "limit": "20"}
                ),
                "premium": executor.submit(
                    self._get, "futures", "/fapi/v1/premiumIndex", {"symbol": symbol}
                ),
                "interest": executor.submit(
                    self._get, "futures", "/fapi/v1/openInterest", {"symbol": symbol}
                ),
            }
            spot_depth, spot_depth_base = remaining["spot_depth"].result()
            futures_depth, futures_depth_base = remaining["futures_depth"].result()
            premium, premium_base = remaining["premium"].result()
            interest, interest_base = remaining["interest"].result()
        payloads = [spot_quote, spot_depth, futures_quote, futures_depth, premium, interest]
        if not all(isinstance(value, dict) for value in payloads):
            raise ValueError("unexpected Binance response")
        spot_bid, spot_ask = float(spot_quote["bidPrice"]), float(spot_quote["askPrice"])
        future_bid, future_ask = float(futures_quote["bidPrice"]), float(futures_quote["askPrice"])
        spot_mid, future_mid = _mid(spot_bid, spot_ask), _mid(future_bid, future_ask)
        event_ms = max(int(value.get("time") or value.get("E") or 0) for value in payloads)
        source_time = datetime.fromtimestamp(event_ms / 1000, tz=timezone.utc) if event_ms else datetime.now(timezone.utc)
        received = datetime.now(timezone.utc)
        raw = {
            "spot_quote": spot_quote, "spot_depth": spot_depth,
            "futures_quote": futures_quote, "futures_depth": futures_depth,
            "premium": premium, "open_interest": interest,
            "source_endpoints": {
                "spot_quote": spot_quote_base, "spot_depth": spot_depth_base,
                "futures_quote": futures_quote_base, "futures_depth": futures_depth_base,
                "premium": premium_base, "open_interest": interest_base,
            },
        }
        digest = sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
        return BinanceFeatureSnapshot({
            "symbol": symbol, "source_timestamp": source_time.isoformat(),
            "received_timestamp": received.isoformat(), "spot_bid": spot_bid,
            "spot_ask": spot_ask, "spot_mid": spot_mid, "spot_imbalance": _imbalance(spot_depth),
            "futures_bid": future_bid, "futures_ask": future_ask, "futures_mid": future_mid,
            "futures_imbalance": _imbalance(futures_depth),
            "basis_bps": (future_mid - spot_mid) / spot_mid * 10_000,
            "open_interest": float(interest["openInterest"]),
            "funding_rate": float(premium["lastFundingRate"]),
            "mark_price": float(premium["markPrice"]), "index_price": float(premium["indexPrice"]),
            "raw": raw, "snapshot_hash": digest,
        })


class BinanceSynchronizer:
    def __init__(self, settings: Settings, client: BinanceHttpClient, store: SQLiteStore) -> None:
        self.settings, self.client, self.store = settings, client, store
        self._active_endpoints: tuple[str | None, str | None] | None = None

    async def sync_once(self) -> dict[str, Any]:
        snapshot = await asyncio.to_thread(self.client.snapshot)
        saved = self.store.save_binance_features(snapshot.storage_record())
        endpoints = snapshot.values["raw"]["source_endpoints"]
        active = (endpoints.get("spot_depth"), endpoints.get("futures_depth"))
        if active != self._active_endpoints:
            self.store.audit("binance_endpoint_selected", {
                "spot_base_url": active[0],
                "futures_base_url": active[1],
                "spot_is_fallback": active[0] != self.settings.binance_spot_base_url.rstrip("/"),
                "futures_is_fallback": active[1] != self.settings.binance_futures_base_url.rstrip("/"),
            })
            self._active_endpoints = active
        return {
            "status": "SUCCEEDED", "saved": saved,
            "source_timestamp": snapshot.values["source_timestamp"],
            "spot_base_url": active[0], "futures_base_url": active[1],
        }

    async def run_forever(self) -> None:
        while True:
            loop = asyncio.get_running_loop()
            started_at = loop.time()
            try:
                await self.sync_once()
            except Exception as error:
                self.store.audit("binance_sync_error", {"error": str(error)})
            elapsed = loop.time() - started_at
            await asyncio.sleep(max(0.0, self.settings.sync_interval_seconds - elapsed))
