from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import Settings
from .domain import CHAINLINK_BTC_USD_TWAP_60S_STREAM_ID, BookLevel, MarketRuleVersion, OrderBook
from .storage import SQLiteStore


JsonGetter = Callable[..., dict[str, Any] | list[Any]]


def _json_get(
    url: str,
    params: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any] | list[Any]:
    if params:
        url = f"{url}?{urlencode(params)}"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "pm-btc/0.1"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _decode_json_array(value: Any) -> list[str]:
    if isinstance(value, str):
        value = json.loads(value)
    return [str(item) for item in (value or [])]


def _utc_from_epoch(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


@dataclass(frozen=True)
class SyncedMarket:
    market_id: str
    slug: str
    condition_id: str
    start_time: datetime
    end_time: datetime
    active: bool
    closed: bool
    up_token_id: str
    down_token_id: str
    rule: MarketRuleVersion
    raw: dict[str, Any]

    def storage_record(self) -> dict[str, Any]:
        return {
            "market_id": self.market_id,
            "slug": self.slug,
            "condition_id": self.condition_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "active": self.active,
            "closed": self.closed,
            "up_token_id": self.up_token_id,
            "down_token_id": self.down_token_id,
            "rule_hash": self.rule.resolution_rule_hash,
            "raw": self.raw,
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }


class PolymarketHttpClient:
    def __init__(self, settings: Settings, getter: JsonGetter = _json_get) -> None:
        self.settings = settings
        self.getter = getter

    def _get(
        self,
        url: str,
        params: dict[str, str] | None,
        timeout: float,
    ) -> dict[str, Any] | list[Any]:
        try:
            return self.getter(url, params, timeout=timeout)
        except TypeError:
            # Unit-test fakes and older integrations only accept (url, params).
            return self.getter(url, params)

    def get_market_by_slug(self, slug: str) -> dict[str, Any] | None:
        try:
            value = self._get(
                f"{self.settings.gamma_base_url}/markets/slug/{slug}",
                None,
                self.settings.polymarket_gamma_timeout_seconds,
            )
        except HTTPError as error:
            if error.code == 404:
                return None
            raise
        if isinstance(value, dict) and value.get("id"):
            return value
        try:
            event = self._get(
                f"{self.settings.gamma_base_url}/events/slug/{slug}",
                None,
                self.settings.polymarket_gamma_timeout_seconds,
            )
        except HTTPError as error:
            if error.code == 404:
                return None
            raise
        if isinstance(event, dict):
            markets = event.get("markets") or []
            if markets and isinstance(markets[0], dict):
                market = dict(markets[0])
                market.setdefault("slug", slug)
                market.setdefault("resolutionSource", event.get("resolutionSource"))
                return market
        return None

    def discover_btc_5m(self, now: datetime | None = None) -> list[SyncedMarket]:
        now = now or datetime.now(timezone.utc)
        anchor = int(now.timestamp()) // 300 * 300
        discovered: list[SyncedMarket] = []
        epochs = [
            anchor + offset * 300
            for offset in range(-self.settings.discovery_past_markets, self.settings.discovery_future_markets + 1)
        ]
        with ThreadPoolExecutor(max_workers=min(8, len(epochs))) as pool:
            futures = {
                pool.submit(self.get_market_by_slug, f"btc-updown-5m-{epoch}"): epoch
                for epoch in epochs
            }
            for future in as_completed(futures):
                raw = future.result()
                if raw is not None:
                    discovered.append(self.parse_market(raw, futures[future]))
        return sorted(discovered, key=lambda market: market.start_time)

    def parse_market(self, raw: dict[str, Any], epoch: int | None = None) -> SyncedMarket:
        slug = str(raw["slug"])
        if epoch is None:
            epoch = int(slug.rsplit("-", 1)[-1])
        start = _utc_from_epoch(epoch)
        end = start + timedelta(minutes=5)
        outcomes = _decode_json_array(raw.get("outcomes"))
        token_ids = _decode_json_array(raw.get("clobTokenIds"))
        if len(outcomes) != 2 or len(token_ids) != 2:
            raise ValueError(f"market {slug} does not expose two outcome tokens")
        mapping = {outcome.upper(): token for outcome, token in zip(outcomes, token_ids)}
        up = mapping.get("UP") or mapping.get("YES")
        down = mapping.get("DOWN") or mapping.get("NO")
        if not up or not down:
            raise ValueError(f"market {slug} has unexpected outcomes {outcomes}")
        source = str(raw.get("resolutionSource") or self.settings.chainlink_stream_url)
        source_slug = source.rstrip("/").rsplit("/", 1)[-1].lower()
        stream_id = (
            CHAINLINK_BTC_USD_TWAP_60S_STREAM_ID
            if "btc-usd-twap-60s" in source_slug else source_slug
        )
        fee_schedule = raw.get("feeSchedule") or {"feesEnabled": bool(raw.get("feesEnabled"))}
        rule = MarketRuleVersion(
            market_id=str(raw["id"]), condition_id=str(raw.get("conditionId") or ""),
            resolution_source_url=source, chainlink_stream_id=stream_id,
            fee_rule_version=sha256(json.dumps(fee_schedule, sort_keys=True).encode()).hexdigest()[:16],
            fee_schedule=fee_schedule, market_schema_version="gamma-v1",
            tick_size=float(raw.get("orderPriceMinTickSize") or 0.01),
            minimum_order_size=float(raw.get("orderMinSize") or 1.0),
            start_time=start, end_time=end, token_ids={"UP": up, "DOWN": down},
        )
        return SyncedMarket(
            market_id=str(raw["id"]), slug=slug,
            condition_id=str(raw.get("conditionId") or ""), start_time=start, end_time=end,
            active=bool(raw.get("active", True)), closed=bool(raw.get("closed", False)),
            up_token_id=up, down_token_id=down, rule=rule, raw=raw,
        )

    def get_orderbook(self, token_id: str) -> tuple[OrderBook, dict[str, Any]]:
        raw = self._get(
            f"{self.settings.clob_base_url}/book",
            {"token_id": token_id},
            self.settings.polymarket_orderbook_timeout_seconds,
        )
        if not isinstance(raw, dict):
            raise ValueError("unexpected orderbook response")
        timestamp_raw = int(str(raw.get("timestamp") or "0"))
        if timestamp_raw > 10_000_000_000:
            timestamp_raw //= 1000
        timestamp = _utc_from_epoch(timestamp_raw) if timestamp_raw else datetime.now(timezone.utc)
        book = OrderBook(
            token_id=token_id,
            bids=tuple(BookLevel(float(level["price"]), float(level["size"])) for level in raw.get("bids", [])),
            asks=tuple(BookLevel(float(level["price"]), float(level["size"])) for level in raw.get("asks", [])),
            timestamp=timestamp,
        )
        return book, raw

    def get_fee_rate(self, token_id: str) -> dict[str, Any]:
        raw = self._get(
            f"{self.settings.clob_base_url}/fee-rate",
            {"token_id": token_id},
            self.settings.polymarket_clob_timeout_seconds,
        )
        if not isinstance(raw, dict) or "base_fee" not in raw:
            raise ValueError("unexpected fee-rate response")
        return {"base_fee": int(raw["base_fee"])}

    def get_clob_market_info(self, condition_id: str) -> dict[str, Any]:
        raw = self._get(
            f"{self.settings.clob_base_url}/clob-markets/{condition_id}",
            None,
            self.settings.polymarket_clob_timeout_seconds,
        )
        if not isinstance(raw, dict) or not isinstance(raw.get("fd"), dict):
            raise ValueError("unexpected CLOB market info response")
        details = raw["fd"]
        if "r" not in details or "e" not in details or "to" not in details:
            raise ValueError("CLOB market fee details are incomplete")
        return raw


class PolymarketSynchronizer:
    def __init__(self, settings: Settings, client: PolymarketHttpClient, store: SQLiteStore) -> None:
        self.settings = settings
        self.client = client
        self.store = store
        self._cached_markets: list[SyncedMarket] = []
        self._last_discovery_at: datetime | None = None
        self._fee_cache: dict[str, dict[str, Any]] = {}

    def _load_nearby_markets_from_store(self, now: datetime | None = None) -> list[SyncedMarket]:
        current_time = now or datetime.now(timezone.utc)
        rows = self.store.connection.execute(
            """SELECT market_id, slug, condition_id, start_time, end_time, active, closed,
            up_token_id, down_token_id, rule_hash, raw_json
            FROM polymarket_markets
            WHERE end_time >= ? AND start_time <= ?
            ORDER BY start_time""",
            (
                (current_time - timedelta(seconds=15)).isoformat(),
                (current_time + timedelta(minutes=5)).isoformat(),
            ),
        ).fetchall()
        markets: list[SyncedMarket] = []
        for row in rows:
            start = datetime.fromisoformat(row[3])
            end = datetime.fromisoformat(row[4])
            raw = json.loads(row[10])
            rule = MarketRuleVersion(
                market_id=row[0],
                condition_id=row[2],
                resolution_source_url=str(raw.get("resolutionSource") or self.settings.chainlink_stream_url),
                chainlink_stream_id=CHAINLINK_BTC_USD_TWAP_60S_STREAM_ID,
                fee_rule_version="cached",
                fee_schedule={},
                market_schema_version="cached-db",
                tick_size=float(raw.get("orderPriceMinTickSize") or 0.01),
                minimum_order_size=float(raw.get("orderMinSize") or 1.0),
                start_time=start,
                end_time=end,
                token_ids={"UP": row[7], "DOWN": row[8]},
                resolution_rule_hash=row[9],
            )
            markets.append(SyncedMarket(
                market_id=row[0], slug=row[1], condition_id=row[2],
                start_time=start, end_time=end, active=bool(row[5]), closed=bool(row[6]),
                up_token_id=row[7], down_token_id=row[8], rule=rule, raw=raw,
            ))
        if markets:
            self._cached_markets = markets
        return markets

    async def _with_fee_schedule(self, market: SyncedMarket) -> SyncedMarket:
        cache_key = f"condition:{market.condition_id}"
        if cache_key not in self._fee_cache:
            self._fee_cache[cache_key] = await asyncio.to_thread(
                self.client.get_clob_market_info, market.condition_id
            )
        info = self._fee_cache[cache_key]
        details = info["fd"]
        schedule: dict[str, Any] = {
            outcome: {
                "rate": float(details["r"]), "exponent": int(details["e"]),
                "taker_only": bool(details["to"]), "taker_base_fee_bps": int(info.get("tbf", 0)),
                "maker_base_fee_bps": int(info.get("mbf", 0)),
            }
            for outcome in ("UP", "DOWN")
        }
        fee_version = sha256(json.dumps(schedule, sort_keys=True).encode()).hexdigest()[:16]
        rule = replace(
            market.rule, fee_schedule=schedule, fee_rule_version=fee_version,
            tick_size=float(info.get("mts", market.rule.tick_size)),
            minimum_order_size=float(info.get("mos", market.rule.minimum_order_size)),
            market_schema_version=f"gamma-v1/clob-{info.get('v', 'unknown')}",
            resolution_rule_hash="",
        )
        return replace(market, rule=rule)

    async def _discover_and_persist(self, now: datetime | None) -> list[SyncedMarket]:
        current_time = now or datetime.now(timezone.utc)
        markets = await asyncio.to_thread(self.client.discover_btc_5m, now)
        fee_limit = asyncio.Semaphore(8)

        async def enrich_market(market: SyncedMarket) -> SyncedMarket:
            try:
                async with fee_limit:
                    return await self._with_fee_schedule(market)
            except (HTTPError, ValueError) as error:
                self.store.audit("fee_rate_sync_error", {
                    "market_id": market.market_id, "error": str(error),
                })
                return market

        markets = list(await asyncio.gather(*(enrich_market(market) for market in markets)))
        self._cached_markets = markets
        # Rule and Gamma snapshots only change on discovery refresh. Avoid dozens of
        # redundant SQLite commits on every two-second book poll.
        for market in markets:
            self.store.save_rule(market.rule)
            self.store.save_polymarket_market(market.storage_record())
        # Measure the refresh interval from completion. A slow discovery must not
        # immediately trigger another discovery before fast book polls can run.
        self._last_discovery_at = current_time if now is not None else datetime.now(timezone.utc)
        return markets

    @staticmethod
    def _relevant_markets(markets: list[SyncedMarket], current_time: datetime) -> list[SyncedMarket]:
        return [
            market for market in markets
            if market.end_time >= current_time - timedelta(seconds=15)
            and market.start_time <= current_time + timedelta(minutes=5)
        ]

    async def _poll_relevant_books(self, markets: list[SyncedMarket], current_time: datetime) -> dict[str, Any]:
        # WebSocket is the exact high-frequency source. REST snapshots are a recovery and
        # executable-price cross-check, so only poll the active and immediately-next 5m
        # markets instead of every future discovery candidate.
        relevant = self._relevant_markets(markets, current_time)
        requests = [
            (market, outcome, token)
            for market in relevant
            for outcome, token in (("UP", market.up_token_id), ("DOWN", market.down_token_id))
        ]

        async def fetch_book(item: tuple[SyncedMarket, str, str]):
            market, outcome, token = item
            last_error: Exception | None = None
            for attempt in range(2):
                try:
                    result = await asyncio.to_thread(self.client.get_orderbook, token)
                    return market, outcome, token, result, None
                except HTTPError as error:
                    if error.code in (404, 400):
                        return market, outcome, token, None, f"HTTP {error.code}"
                    last_error = error
                except Exception as error:
                    last_error = error
                if attempt == 0:
                    await asyncio.sleep(0.15)
            return market, outcome, token, None, str(last_error or "unknown orderbook error")

        books_saved = 0
        received_outcomes: dict[str, set[str]] = {}
        errors: list[str] = []
        results = await asyncio.gather(*(fetch_book(item) for item in requests))
        for market, outcome, token, result, error in results:
            observed_at = datetime.now(timezone.utc).isoformat()
            if result is None:
                errors.append(f"{market.market_id}:{outcome}:{error}")
                self.store.record_polymarket_book_gap(
                    market.market_id, token, outcome, observed_at,
                    error or "unknown orderbook error",
                )
                continue
            received_outcomes.setdefault(market.market_id, set()).add(outcome)
            book, raw = result
            books_saved += int(self.store.save_orderbook(market.market_id, outcome, book, raw))
            self.store.recover_polymarket_book_gaps(token, observed_at)
        return {
            "relevant_markets": len(relevant),
            "expected_books": len(requests),
            "received_books": sum(len(outcomes) for outcomes in received_outcomes.values()),
            "complete_markets": sum(outcomes == {"UP", "DOWN"} for outcomes in received_outcomes.values()),
            "books_saved": books_saved,
            "errors": errors,
        }

    async def refresh_markets_once(self, now: datetime | None = None) -> dict[str, Any]:
        run_id = self.store.start_sync_run()
        markets: list[SyncedMarket] = []
        try:
            markets = await self._discover_and_persist(now)
            self.store.finish_sync_run(run_id, "SUCCEEDED", len(markets), 0)
            self.store.audit("polymarket_market_discovery_succeeded", {"markets": len(markets)})
            return {"status": "SUCCEEDED", "markets": len(markets), "books_saved": 0}
        except Exception as error:
            self.store.finish_sync_run(run_id, "FAILED", len(markets), 0, str(error))
            raise

    async def poll_books_once(
        self,
        now: datetime | None = None,
        *,
        discover_if_empty: bool = True,
    ) -> dict[str, Any]:
        run_id = self.store.start_sync_run()
        markets = list(self._cached_markets)
        poll_started = (now or datetime.now(timezone.utc)).isoformat()
        stats = {
            "relevant_markets": 0, "expected_books": 0, "received_books": 0,
            "complete_markets": 0, "books_saved": 0,
        }
        try:
            current_time = now or datetime.now(timezone.utc)
            stored_markets = self._load_nearby_markets_from_store(current_time)
            if stored_markets:
                markets = stored_markets
            if not markets and discover_if_empty:
                markets = await self._discover_and_persist(now)
            if not markets:
                self.store.finish_sync_run(run_id, "SUCCEEDED", 0, 0)
                self.store.save_polymarket_book_poll_run({
                    **stats, "polled_at": poll_started,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "status": "SUCCEEDED", "error": None,
                })
                self.store.audit("polymarket_book_poll_no_cached_markets", {
                    "current_time": current_time.isoformat(),
                })
                return {"status": "SUCCEEDED", "markets": 0, "books_saved": 0}
            stats = await self._poll_relevant_books(markets, current_time)
            complete = stats["received_books"] == stats["expected_books"]
            poll_status = "SUCCEEDED" if complete else "PARTIAL"
            poll_error = "; ".join(stats.get("errors", [])) or None
            self.store.finish_sync_run(
                run_id, poll_status, len(markets), stats["books_saved"], poll_error,
            )
            self.store.save_polymarket_book_poll_run({
                **stats, "polled_at": poll_started,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "status": poll_status, "error": poll_error,
            })
            if not complete:
                self.store.audit("polymarket_book_poll_partial", {
                    "expected_books": stats["expected_books"],
                    "received_books": stats["received_books"],
                    "errors": stats.get("errors", []),
                })
            return {"status": poll_status, "markets": len(markets), **stats}
        except Exception as error:
            relevant = self._relevant_markets(markets, now or datetime.now(timezone.utc))
            stats["relevant_markets"] = len(relevant)
            stats["expected_books"] = len(relevant) * 2
            self.store.finish_sync_run(run_id, "FAILED", len(markets), stats["books_saved"], str(error))
            self.store.save_polymarket_book_poll_run({
                **stats, "polled_at": poll_started,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "status": "FAILED", "error": str(error),
            })
            raise

    async def sync_once(self, now: datetime | None = None, force_discovery: bool = True) -> dict[str, Any]:
        run_id = self.store.start_sync_run()
        markets: list[SyncedMarket] = []
        books_saved = 0
        try:
            current_time = now or datetime.now(timezone.utc)
            cache_age = (
                (current_time - self._last_discovery_at).total_seconds()
                if self._last_discovery_at else float("inf")
            )
            discovery_due = (
                force_discovery or not self._cached_markets
                or cache_age >= self.settings.market_discovery_interval_seconds
            )
            if self._cached_markets and not force_discovery:
                markets = self._cached_markets
                books_saved += (await self._poll_relevant_books(markets, current_time))["books_saved"]
                if discovery_due:
                    markets = await self._discover_and_persist(now)
            else:
                markets = await self._discover_and_persist(now) if discovery_due else self._cached_markets
                books_saved += (await self._poll_relevant_books(markets, current_time))["books_saved"]
            self.store.finish_sync_run(run_id, "SUCCEEDED", len(markets), books_saved)
            return {"status": "SUCCEEDED", "markets": len(markets), "books_saved": books_saved}
        except Exception as error:
            self.store.finish_sync_run(run_id, "FAILED", len(markets), books_saved, str(error))
            raise

    async def run_forever(self) -> None:
        async def book_loop() -> None:
            while True:
                try:
                    await self.poll_books_once()
                except Exception as error:
                    self.store.audit("polymarket_book_poll_error", {"error": str(error)})
                await asyncio.sleep(self.settings.sync_interval_seconds)

        async def discovery_loop() -> None:
            while True:
                try:
                    await self.refresh_markets_once()
                except Exception as error:
                    self.store.audit("polymarket_sync_error", {"error": str(error)})
                await asyncio.sleep(self.settings.market_discovery_interval_seconds)

        await asyncio.gather(book_loop(), discovery_loop())

    async def run_books_forever(self) -> None:
        while True:
            try:
                await self.poll_books_once(discover_if_empty=False)
            except Exception as error:
                self.store.audit("polymarket_book_poll_error", {"error": str(error)})
            await asyncio.sleep(self.settings.sync_interval_seconds)

    async def run_discovery_forever(self) -> None:
        while True:
            try:
                await self.refresh_markets_once()
            except Exception as error:
                self.store.audit("polymarket_sync_error", {"error": str(error)})
            await asyncio.sleep(self.settings.market_discovery_interval_seconds)


def create_synchronizer(settings: Settings) -> tuple[PolymarketSynchronizer, SQLiteStore]:
    database = Path(settings.database_path)
    database.parent.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(str(database))
    return PolymarketSynchronizer(settings, PolymarketHttpClient(settings), store), store
