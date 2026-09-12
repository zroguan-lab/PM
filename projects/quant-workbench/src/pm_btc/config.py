from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    gamma_base_url: str = "https://gamma-api.polymarket.com"
    clob_base_url: str = "https://clob.polymarket.com"
    polymarket_clob_ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    polymarket_rtds_ws_url: str = "wss://ws-live-data.polymarket.com"
    polymarket_ws_subscription_refresh_seconds: float = 15.0
    polymarket_ws_heartbeat_seconds: float = 10.0
    polymarket_ws_book_snapshot_interval_seconds: float = 1.0
    polymarket_ws_raw_batch_interval_seconds: float = 1.0
    websocket_trusted_dns_enabled: bool = True
    trusted_dns_over_https_url: str = "https://cloudflare-dns.com/dns-query"
    chainlink_stream_url: str = "https://data.chain.link/streams/btc-usd-twap-60s-streams"
    chainlink_api_base_url: str = "https://api.dataengine.chain.link"
    chainlink_api_key: str | None = None
    chainlink_api_secret: str | None = None
    binance_spot_base_url: str = "https://api.binance.com"
    binance_spot_fallback_urls: tuple[str, ...] = (
        "https://api-gcp.binance.com",
        "https://api1.binance.com",
        "https://api2.binance.com",
        "https://api3.binance.com",
        "https://api4.binance.com",
        "https://data-api.binance.vision",
    )
    binance_futures_base_url: str = "https://fapi.binance.com"
    binance_futures_fallback_urls: tuple[str, ...] = ()
    binance_spot_ws_base_url: str = "wss://stream.binance.com:9443/stream"
    binance_spot_ws_fallback_urls: tuple[str, ...] = (
        "wss://stream.binance.com:443/stream",
        "wss://data-stream.binance.vision/stream",
    )
    binance_futures_public_ws_base_url: str = "wss://fstream.binance.com/public/stream"
    binance_futures_market_ws_base_url: str = "wss://fstream.binance.com/market/stream"
    binance_ws_raw_batch_interval_seconds: float = 1.0
    binance_ws_book_snapshot_interval_seconds: float = 0.5
    binance_symbol: str = "BTCUSDT"
    database_path: str = "data/pm_btc.sqlite3"
    published_model_path: str = "artifacts/published-model.json"
    paper_starting_cash: float = 1000.0
    sync_interval_seconds: float = 2.0
    market_discovery_interval_seconds: float = 30.0
    polymarket_gamma_timeout_seconds: float = 5.0
    polymarket_clob_timeout_seconds: float = 5.0
    polymarket_orderbook_timeout_seconds: float = 2.0
    discovery_past_markets: int = 12
    # Four future windows (20 minutes) are sufficient for subscription handoff.
    # Scanning 24 future markets made every live discovery cycle network-bound.
    discovery_future_markets: int = 4
    conservative_edge_buffer: float = 0.01
    uncertainty_confidence: float = 0.90
    data_stale_seconds: float = 3.0
    polymarket_rest_orderbook_stale_seconds: float = 30.0
    binance_slow_feature_stale_seconds: float = 10.0
    chainlink_heartbeat_stale_seconds: float = 90.0
    probability_interval_max_width: float = 0.30
    ood_risk_limit: float = 0.10
    research_days: int = 30
    research_trades: int = 500
    auto_publish_min_markets: int = 30
    auto_retrain_market_interval: int = 10
    live_days: int = 60
    live_markets: int = 2000
    live_cap_usdc: float = 50.0
    per_trade_risk: float = 0.005
    daily_loss_limit: float = 0.02
    total_exposure_limit: float = 0.03

    @classmethod
    def from_env(cls) -> "Settings":
        def boolean(name: str, default: bool) -> bool:
            value = os.getenv(name)
            if value is None:
                return default
            return value.strip().lower() not in ("0", "false", "no", "off")

        def urls(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
            value = os.getenv(name)
            if value is None:
                return default
            return tuple(item.strip().rstrip("/") for item in value.split(",") if item.strip())

        return cls(
            chainlink_api_key=os.getenv("CHAINLINK_API_KEY"),
            chainlink_api_secret=os.getenv("CHAINLINK_API_SECRET"),
            polymarket_clob_ws_url=os.getenv("POLYMARKET_CLOB_WS_URL", cls.polymarket_clob_ws_url),
            polymarket_rtds_ws_url=os.getenv("POLYMARKET_RTDS_WS_URL", cls.polymarket_rtds_ws_url),
            websocket_trusted_dns_enabled=boolean(
                "WEBSOCKET_TRUSTED_DNS_ENABLED", cls.websocket_trusted_dns_enabled
            ),
            trusted_dns_over_https_url=os.getenv(
                "TRUSTED_DNS_OVER_HTTPS_URL", cls.trusted_dns_over_https_url
            ),
            binance_spot_base_url=os.getenv("BINANCE_SPOT_BASE_URL", cls.binance_spot_base_url).rstrip("/"),
            binance_spot_fallback_urls=urls("BINANCE_SPOT_FALLBACK_URLS", cls.binance_spot_fallback_urls),
            binance_futures_base_url=os.getenv("BINANCE_FUTURES_BASE_URL", cls.binance_futures_base_url).rstrip("/"),
            binance_futures_fallback_urls=urls("BINANCE_FUTURES_FALLBACK_URLS", cls.binance_futures_fallback_urls),
            binance_spot_ws_base_url=os.getenv("BINANCE_SPOT_WS_BASE_URL", cls.binance_spot_ws_base_url),
            binance_spot_ws_fallback_urls=urls(
                "BINANCE_SPOT_WS_FALLBACK_URLS", cls.binance_spot_ws_fallback_urls
            ),
            binance_futures_public_ws_base_url=os.getenv(
                "BINANCE_FUTURES_PUBLIC_WS_BASE_URL", cls.binance_futures_public_ws_base_url
            ),
            binance_futures_market_ws_base_url=os.getenv(
                "BINANCE_FUTURES_MARKET_WS_BASE_URL", cls.binance_futures_market_ws_base_url
            ),
            binance_ws_raw_batch_interval_seconds=float(os.getenv(
                "BINANCE_WS_RAW_BATCH_INTERVAL_SECONDS", cls.binance_ws_raw_batch_interval_seconds
            )),
            binance_ws_book_snapshot_interval_seconds=float(os.getenv(
                "BINANCE_WS_BOOK_SNAPSHOT_INTERVAL_SECONDS", cls.binance_ws_book_snapshot_interval_seconds
            )),
            binance_slow_feature_stale_seconds=float(os.getenv(
                "BINANCE_SLOW_FEATURE_STALE_SECONDS", cls.binance_slow_feature_stale_seconds
            )),
            polymarket_rest_orderbook_stale_seconds=float(os.getenv(
                "POLYMARKET_REST_ORDERBOOK_STALE_SECONDS", cls.polymarket_rest_orderbook_stale_seconds
            )),
            polymarket_gamma_timeout_seconds=float(os.getenv(
                "POLYMARKET_GAMMA_TIMEOUT_SECONDS", cls.polymarket_gamma_timeout_seconds
            )),
            polymarket_clob_timeout_seconds=float(os.getenv(
                "POLYMARKET_CLOB_TIMEOUT_SECONDS", cls.polymarket_clob_timeout_seconds
            )),
            polymarket_orderbook_timeout_seconds=float(os.getenv(
                "POLYMARKET_ORDERBOOK_TIMEOUT_SECONDS", cls.polymarket_orderbook_timeout_seconds
            )),
            market_discovery_interval_seconds=float(os.getenv(
                "MARKET_DISCOVERY_INTERVAL_SECONDS", cls.market_discovery_interval_seconds
            )),
            discovery_past_markets=int(os.getenv("DISCOVERY_PAST_MARKETS", cls.discovery_past_markets)),
            discovery_future_markets=int(os.getenv("DISCOVERY_FUTURE_MARKETS", cls.discovery_future_markets)),
            database_path=os.getenv("PM_BTC_DATABASE", cls.database_path),
        )
