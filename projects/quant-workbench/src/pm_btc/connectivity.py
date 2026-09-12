from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from typing import Any, Callable
from urllib.request import Request, urlopen

from websockets.asyncio.client import connect

from .config import Settings
from .trusted_dns import TrustedDnsResolver


@dataclass(frozen=True)
class ConnectivityProbe:
    name: str
    kind: str
    url: str
    status: str
    latency_ms: float | None
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _elapsed_ms(start: float) -> float:
    return round((asyncio.get_running_loop().time() - start) * 1000, 2)


async def _http_probe(
    name: str,
    url: str,
    timeout_seconds: float,
    getter: Callable[..., Any] = urlopen,
) -> ConnectivityProbe:
    loop = asyncio.get_running_loop()
    start = loop.time()

    def request_once() -> int:
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "pm-btc/0.1"})
        with getter(request, timeout=timeout_seconds) as response:
            if hasattr(response, "status"):
                return int(response.status)
            return int(response.getcode())

    try:
        status_code = await asyncio.wait_for(asyncio.to_thread(request_once), timeout_seconds + 1)
        status = "OK" if status_code < 500 else "ERROR"
        return ConnectivityProbe(name, "http", url, status, _elapsed_ms(start), f"http_status={status_code}")
    except TimeoutError as error:
        return ConnectivityProbe(name, "http", url, "TIMEOUT", _elapsed_ms(start), str(error))
    except Exception as error:
        return ConnectivityProbe(name, "http", url, "ERROR", _elapsed_ms(start), str(error))


async def _websocket_probe(
    name: str,
    url: str,
    timeout_seconds: float,
    subscribe_payload: dict[str, Any] | None = None,
    resolver: TrustedDnsResolver | None = None,
    connector: Callable[..., Any] = connect,
) -> ConnectivityProbe:
    loop = asyncio.get_running_loop()
    start = loop.time()
    connection_kwargs: dict[str, Any] = {"proxy": None}
    resolved_address = None
    if resolver is not None:
        try:
            target = await asyncio.wait_for(resolver.resolve_websocket(url), timeout_seconds)
            connection_kwargs.update(target.connection_kwargs())
            resolved_address = target.address
        except Exception as error:
            return ConnectivityProbe(name, "websocket", url, "DNS_ERROR", _elapsed_ms(start), str(error))
    try:
        async with connector(
            url,
            ping_interval=None,
            open_timeout=timeout_seconds,
            close_timeout=2,
            max_size=2 * 1024 * 1024,
            **connection_kwargs,
        ) as websocket:
            if subscribe_payload is not None:
                await websocket.send(json.dumps(subscribe_payload))
            return ConnectivityProbe(name, "websocket", url, "OK", _elapsed_ms(start), _route_detail(resolved_address))
    except TimeoutError as error:
        return ConnectivityProbe(name, "websocket", url, "TIMEOUT", _elapsed_ms(start), _route_detail(resolved_address, error))
    except Exception as error:
        return ConnectivityProbe(name, "websocket", url, "ERROR", _elapsed_ms(start), _route_detail(resolved_address, error))


def _route_detail(resolved_address: str | None, error: Exception | None = None) -> str | None:
    parts = []
    if resolved_address is not None:
        parts.append(f"resolved_address={resolved_address}")
    if error is not None:
        parts.append(str(error))
    return "; ".join(parts) if parts else None


def _websocket_route_probes(
    name: str,
    url: str,
    timeout_seconds: float,
    subscribe_payload: dict[str, Any] | None,
    resolver: TrustedDnsResolver | None,
) -> list[Any]:
    probes = [
        _websocket_probe(
            f"{name}:direct",
            url,
            timeout_seconds,
            subscribe_payload=subscribe_payload,
        )
    ]
    if resolver is not None:
        probes.append(
            _websocket_probe(
                f"{name}:trusted_dns",
                url,
                timeout_seconds,
                subscribe_payload=subscribe_payload,
                resolver=resolver,
            )
        )
    return probes


def _required_groups(results: list[dict[str, Any]]) -> dict[str, bool]:
    groups = {
        "binance_spot_http": [item for item in results if item["name"].startswith("binance_spot_http:")],
        "binance_futures_http": [item for item in results if item["name"].startswith("binance_futures_http:")],
        "polymarket_gamma": [item for item in results if item["name"] == "polymarket_gamma"],
        "polymarket_clob_http": [item for item in results if item["name"] == "polymarket_clob"],
        "polymarket_clob_ws": [item for item in results if item["name"].startswith("polymarket_clob_ws:")],
        "polymarket_chainlink_rtds": [
            item for item in results if item["name"].startswith("polymarket_chainlink_rtds:")
        ],
        "binance_spot_ws": [item for item in results if item["name"].startswith("binance_spot_ws:")],
        "binance_futures_ws": [item for item in results if item["name"].startswith("binance_futures_public_ws:")],
    }
    return {
        name: any(item["status"] == "OK" for item in group)
        for name, group in groups.items()
    }


async def connectivity_report(settings: Settings, timeout_seconds: float = 10.0) -> dict[str, Any]:
    resolver = TrustedDnsResolver(settings.trusted_dns_over_https_url) if settings.websocket_trusted_dns_enabled else None
    binance_spot_urls = [
        settings.binance_spot_base_url,
        *settings.binance_spot_fallback_urls,
    ]
    binance_futures_urls = [
        settings.binance_futures_base_url,
        *settings.binance_futures_fallback_urls,
    ]
    binance_spot_ws_urls = [
        settings.binance_spot_ws_base_url,
        *settings.binance_spot_ws_fallback_urls,
    ]
    probes = [
        *(
            _http_probe(f"binance_spot_http:{index}", url.rstrip("/") + "/api/v3/time", timeout_seconds)
            for index, url in enumerate(binance_spot_urls)
        ),
        *(
            _http_probe(f"binance_futures_http:{index}", url.rstrip("/") + "/fapi/v1/time", timeout_seconds)
            for index, url in enumerate(binance_futures_urls)
        ),
        _http_probe("polymarket_gamma", settings.gamma_base_url.rstrip("/") + "/markets?limit=1", timeout_seconds),
        _http_probe("polymarket_clob", settings.clob_base_url.rstrip("/") + "/ok", timeout_seconds),
        *_websocket_route_probes(
            "polymarket_clob_ws",
            settings.polymarket_clob_ws_url,
            timeout_seconds,
            subscribe_payload={"type": "market", "assets_ids": []},
            resolver=resolver,
        ),
        *_websocket_route_probes(
            "polymarket_chainlink_rtds",
            settings.polymarket_rtds_ws_url,
            timeout_seconds,
            subscribe_payload={
                "action": "subscribe",
                "subscriptions": [{"topic": "crypto_prices_twap_sixty", "type": "update"}],
            },
            resolver=resolver,
        ),
        *(
            _websocket_probe(
                f"binance_spot_ws:{index}",
                f"{url.rstrip('/')}?streams={settings.binance_symbol.lower()}@bookTicker",
                timeout_seconds,
            )
            for index, url in enumerate(binance_spot_ws_urls)
        ),
        _websocket_probe(
            "binance_futures_public_ws:0",
            f"{settings.binance_futures_public_ws_base_url.rstrip('/')}?streams={settings.binance_symbol.lower()}@bookTicker",
            timeout_seconds,
        ),
    ]
    results = [probe.to_dict() for probe in await asyncio.gather(*probes)]
    groups = _required_groups(results)
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "timeout_seconds": timeout_seconds,
        "ok": all(groups.values()),
        "required_groups": groups,
        "probes": results,
    }
