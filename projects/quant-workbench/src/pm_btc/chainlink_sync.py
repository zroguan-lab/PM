from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import hmac
import json
import time
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import Settings
from .storage import SQLiteStore


def authentication_headers(api_key: str, api_secret: str, full_path: str, timestamp_ms: int) -> dict[str, str]:
    body_hash = sha256(b"").hexdigest()
    message = f"GET {full_path} {body_hash} {api_key} {timestamp_ms}"
    signature = hmac.new(api_secret.encode(), message.encode(), sha256).hexdigest()
    return {
        "Accept": "application/json",
        "Authorization": api_key,
        "X-Authorization-Timestamp": str(timestamp_ms),
        "X-Authorization-Signature-SHA256": signature,
        "User-Agent": "pm-btc/0.1",
    }


class ChainlinkDataStreamsClient:
    """Archives signed Data Streams reports; decoding/verification is a separate mandatory gate."""

    def __init__(self, settings: Settings, opener: Callable[..., Any] = urlopen) -> None:
        self.settings, self.opener = settings, opener

    def latest_report(self, feed_id: str) -> dict[str, Any]:
        key, secret = self.settings.chainlink_api_key, self.settings.chainlink_api_secret
        if not key or not secret:
            raise RuntimeError("CHAINLINK_API_KEY and CHAINLINK_API_SECRET are required")
        query = urlencode({"feedID": feed_id})
        path = f"/api/v1/reports/latest?{query}"
        timestamp_ms = int(time.time() * 1000)
        request = Request(
            f"{self.settings.chainlink_api_base_url}{path}",
            headers=authentication_headers(key, secret, path, timestamp_ms),
        )
        with self.opener(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        report = payload.get("report") if isinstance(payload, dict) else None
        if not isinstance(report, dict) or not report.get("fullReport"):
            raise ValueError("unexpected Chainlink report response")
        raw_hash = sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        return {
            "feed_id": str(report.get("feedID") or feed_id),
            "observations_timestamp": datetime.fromtimestamp(int(report["observationsTimestamp"]), tz=timezone.utc).isoformat(),
            "valid_from_timestamp": datetime.fromtimestamp(int(report["validFromTimestamp"]), tz=timezone.utc).isoformat(),
            "received_timestamp": datetime.now(timezone.utc).isoformat(),
            "full_report": str(report["fullReport"]), "raw_payload_hash": raw_hash,
            "verification_status": "UNVERIFIED",
        }


class ChainlinkRawSynchronizer:
    def __init__(self, client: ChainlinkDataStreamsClient, store: SQLiteStore) -> None:
        self.client, self.store = client, store

    def sync_once(self, feed_id: str) -> dict[str, Any]:
        report = self.client.latest_report(feed_id)
        saved = self.store.save_chainlink_raw_report(report)
        return {
            "status": "ARCHIVED_UNVERIFIED", "saved": saved,
            "feed_id": report["feed_id"],
            "observations_timestamp": report["observations_timestamp"],
        }
