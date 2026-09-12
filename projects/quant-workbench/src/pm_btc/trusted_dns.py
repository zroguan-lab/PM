from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import ipaddress
import json
from typing import Any, Callable
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class ResolvedWebSocketTarget:
    uri: str
    hostname: str
    address: str
    port: int

    def connection_kwargs(self) -> dict[str, Any]:
        # The TCP destination is overridden while TLS SNI and the HTTP Host
        # header continue to use the original URI hostname. Certificate
        # validation therefore remains mandatory.
        return {
            "host": self.address,
            "port": self.port,
            "server_hostname": self.hostname,
            "proxy": None,
        }


class TrustedDnsResolver:
    """Resolve public WebSocket hosts through DNS-over-HTTPS with a short cache."""

    def __init__(
        self,
        endpoint: str = "https://cloudflare-dns.com/dns-query",
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.endpoint = endpoint.rstrip("?")
        self.opener = opener
        self._cache: dict[str, tuple[datetime, tuple[str, ...]]] = {}
        self._next_address: dict[str, int] = {}

    def _resolve_ipv4_sync(self, hostname: str) -> tuple[str, ...]:
        now = datetime.now(timezone.utc)
        cached = self._cache.get(hostname)
        if cached is not None and cached[0] > now:
            return cached[1]
        query = urlencode({"name": hostname, "type": "A"})
        request = Request(
            f"{self.endpoint}?{query}",
            headers={"Accept": "application/dns-json", "User-Agent": "pm-btc/0.1"},
        )
        with self.opener(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if int(payload.get("Status", -1)) != 0:
            raise RuntimeError(f"trusted DNS returned status {payload.get('Status')!r}")
        addresses: list[str] = []
        ttl_values: list[int] = []
        for answer in payload.get("Answer") or []:
            if int(answer.get("type", 0)) != 1:
                continue
            try:
                address = ipaddress.ip_address(str(answer.get("data")))
            except ValueError:
                continue
            if address.version != 4 or not address.is_global:
                continue
            text = str(address)
            if text not in addresses:
                addresses.append(text)
            try:
                ttl_values.append(int(answer.get("TTL", 60)))
            except (TypeError, ValueError):
                ttl_values.append(60)
        if not addresses:
            raise RuntimeError(f"trusted DNS returned no public IPv4 address for {hostname}")
        ttl = max(30, min(300, min(ttl_values or [60])))
        result = tuple(addresses)
        self._cache[hostname] = (now + timedelta(seconds=ttl), result)
        return result

    async def resolve_websocket(self, uri: str) -> ResolvedWebSocketTarget:
        parsed = urlparse(uri)
        if parsed.scheme not in ("ws", "wss") or not parsed.hostname:
            raise ValueError(f"invalid WebSocket URI: {uri!r}")
        addresses = await asyncio.to_thread(self._resolve_ipv4_sync, parsed.hostname)
        index = self._next_address.get(parsed.hostname, 0) % len(addresses)
        self._next_address[parsed.hostname] = index + 1
        return ResolvedWebSocketTarget(
            uri=uri,
            hostname=parsed.hostname,
            address=addresses[index],
            port=parsed.port or (443 if parsed.scheme == "wss" else 80),
        )
