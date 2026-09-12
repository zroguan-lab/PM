from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Lock
import time
from urllib.parse import urlparse
from pathlib import Path

from .config import Settings
from .publication import PublishedModel
from .storage import SQLiteStore


def _age_seconds(now: datetime, timestamp: str | None) -> float | None:
    if not timestamp:
        return None
    return max(0.0, (now - datetime.fromisoformat(timestamp)).total_seconds())


def _build_health(settings: Settings, sync: dict, prediction: dict | None, now: datetime) -> dict:
    latest_binance = sync.get("latest_binance_feature_at")
    binance_age = _age_seconds(now, latest_binance)
    latest_clob = sync.get("latest_polymarket_clob_event_at")
    clob_age = _age_seconds(now, latest_clob)
    latest_orderbook = sync.get("latest_complete_orderbook_pair_at") or sync.get("latest_orderbook_snapshot_at")
    orderbook_age = _age_seconds(now, latest_orderbook)
    latest_binance_ws = sync.get("latest_binance_ws_event_at")
    binance_ws_age = _age_seconds(now, latest_binance_ws)
    binance_ws_stream_ages = {
        name: _age_seconds(now, item["last_received_timestamp"])
        for name, item in (sync.get("binance_ws_stream_health") or {}).items()
    }
    required_binance_streams = {"spot", "futures_public", "futures_market"}
    latest_chainlink = sync.get("latest_chainlink_observation_at")
    chainlink_age = _age_seconds(now, latest_chainlink)
    return {
        "binance_age_seconds": binance_age,
        "binance_fresh": (
            binance_age is not None and binance_age < settings.binance_slow_feature_stale_seconds
        ),
        "binance_ws_age_seconds": binance_ws_age,
        "binance_ws_stream_ages": binance_ws_stream_ages,
        "binance_ws_fresh": (
            required_binance_streams.issubset(binance_ws_stream_ages)
            and all(
                binance_ws_stream_ages[name] is not None
                and binance_ws_stream_ages[name] <= settings.data_stale_seconds
                for name in required_binance_streams
            )
        ),
        "polymarket_orderbook_age_seconds": orderbook_age,
        "polymarket_orderbook_fresh": (
            orderbook_age is not None
            and orderbook_age <= settings.polymarket_rest_orderbook_stale_seconds
        ),
        "polymarket_clob_ws_age_seconds": clob_age,
        "polymarket_clob_ws_fresh": clob_age is not None and clob_age <= settings.data_stale_seconds,
        "polymarket_clob_age_seconds": clob_age,
        "polymarket_clob_fresh": clob_age is not None and clob_age <= settings.data_stale_seconds,
        "chainlink_configured": sync.get("verified_chainlink_observations", 0) > 0,
        "chainlink_age_seconds": chainlink_age,
        "chainlink_fresh": (
            chainlink_age is not None
            and chainlink_age <= settings.chainlink_heartbeat_stale_seconds
        ),
        "prediction_state": prediction["decision"] if prediction else "NO_DATA",
    }


def _build_btc_judgment(prediction: dict | None, chainlink_fresh: bool) -> dict:
    """Project an honest directional view separately from trade authorization.

    This is a Chainlink resolution-state judgment, not a calibrated probability.
    It remains useful while the Alpha publication gate is closed, but can never
    authorize an order by itself.
    """
    waiting = {
        "status": "WAITING",
        "direction": None,
        "strength": None,
        "basis": "CHAINLINK_RESOLUTION_STATE",
        "resolution_pressure": None,
        "trade_decision": prediction["decision"] if prediction else "NO_TRADE",
        "tradable": False,
    }
    if not prediction or not chainlink_fresh:
        return waiting
    features = prediction.get("features") or {}
    pressure = features.get("resolution_pressure")
    if not isinstance(pressure, (int, float)):
        return waiting
    magnitude = abs(float(pressure))
    if magnitude < 0.35:
        direction = "NEUTRAL"
    else:
        direction = "UP" if pressure > 0 else "DOWN"
    strength = "STRONG" if magnitude >= 2.0 else "MODERATE" if magnitude >= 0.75 else "WEAK"
    trade_decision = prediction.get("decision", "NO_TRADE")
    return {
        "status": "READY",
        "direction": direction,
        "strength": strength,
        "basis": "CHAINLINK_RESOLUTION_STATE",
        "resolution_pressure": float(pressure),
        "required_remaining_twap": features.get("required_remaining_twap"),
        "current_cumulative_twap": features.get("current_cumulative_twap"),
        "provisional_resolution": features.get("provisional_resolution"),
        "trade_decision": trade_decision,
        "tradable": trade_decision != "NO_TRADE",
    }


def _build_btc_trend_judgment(prediction: dict | None, binance_fresh: bool) -> dict:
    """Transparent BTC tape direction, kept separate from settlement and trading.

    This is deliberately an uncalibrated research score. It summarizes independent
    Binance spot/perpetual trades and top-of-book pressure and can never authorize
    an order or substitute for the published Alpha probability.
    """
    waiting = {
        "status": "WAITING", "direction": None, "strength": None,
        "basis": "BINANCE_ORDERFLOW_HEURISTIC_V1", "score": None,
        "confidence": None, "components": {}, "calibrated": False,
        "tradable": False,
    }
    if not prediction or not binance_fresh:
        return waiting
    features = prediction.get("features") or {}
    weights = {
        "spot_trade_imbalance_60s": ("binance_spot_trade_imbalance_60s", 0.30),
        "futures_trade_imbalance_60s": ("binance_futures_trade_imbalance_60s", 0.30),
        "spot_top_imbalance": ("binance_spot_ws_top_imbalance", 0.20),
        "futures_top_imbalance": ("binance_futures_ws_top_imbalance", 0.20),
    }
    components: dict[str, float] = {}
    weighted_score = total_weight = 0.0
    for label, (feature_name, weight) in weights.items():
        value = features.get(feature_name)
        if isinstance(value, (int, float)):
            bounded = max(-1.0, min(1.0, float(value)))
            components[label] = bounded
            weighted_score += bounded * weight
            total_weight += weight
    if len(components) < 3 or total_weight <= 0:
        return {**waiting, "components": components}
    score = weighted_score / total_weight
    active = [value for value in components.values() if abs(value) >= 0.05]
    direction = "NEUTRAL" if abs(score) < 0.08 else "UP" if score > 0 else "DOWN"
    agreement = (
        sum((value > 0) == (score > 0) for value in active) / len(active)
        if active and direction != "NEUTRAL" else 0.5
    )
    confidence = min(1.0, 0.6 * agreement + 0.4 * min(1.0, abs(score) * 2.0))
    magnitude = abs(score)
    strength = "STRONG" if magnitude >= 0.50 else "MODERATE" if magnitude >= 0.25 else "WEAK"
    return {
        "status": "READY", "direction": direction, "strength": strength,
        "basis": "BINANCE_ORDERFLOW_HEURISTIC_V1", "score": score,
        "confidence": confidence, "components": components,
        "calibrated": False, "tradable": False,
    }


def _readiness_item(name: str, ready: bool, evidence: dict, blocker: str | None = None) -> dict:
    item = {"name": name, "ready": ready, "evidence": evidence}
    if blocker and not ready:
        item["blocker"] = blocker
    return item


def build_data_readiness(settings: Settings, sync: dict, health: dict, prediction: dict | None, model: dict | None) -> dict:
    stages = [
        _readiness_item(
            "polymarket_market_sync",
            sync.get("markets", 0) > 0,
            {
                "markets": sync.get("markets", 0),
                "latest_run_status": (sync.get("latest_run") or {}).get("status"),
            },
            "polymarket_market_missing",
        ),
        _readiness_item(
            "polymarket_rest_orderbook",
            sync.get("orderbook_snapshots", 0) > 0 and bool(health["polymarket_orderbook_fresh"]),
            {
                "orderbook_snapshots": sync.get("orderbook_snapshots", 0),
                "relevant_markets": sync.get("polymarket_relevant_markets", 0),
                "markets_with_books": sync.get("polymarket_relevant_markets_with_books", 0),
                "coverage": sync.get("polymarket_relevant_book_coverage", 0),
                "latest_orderbook_snapshot_at": sync.get("latest_orderbook_snapshot_at"),
                "latest_complete_orderbook_pair_at": sync.get("latest_complete_orderbook_pair_at"),
                "age_seconds": health["polymarket_orderbook_age_seconds"],
            },
            "polymarket_rest_orderbook_not_fresh",
        ),
        _readiness_item(
            "polymarket_clob_ws",
            bool(health["polymarket_clob_fresh"]),
            {
                "events": sync.get("polymarket_clob_events", 0),
                "trades": sync.get("polymarket_clob_trades", 0),
                "age_seconds": health["polymarket_clob_age_seconds"],
            },
            "polymarket_clob_not_fresh",
        ),
        _readiness_item(
            "binance_features",
            bool(health["binance_fresh"] and health["binance_ws_fresh"]),
            {
                "slow_snapshots": sync.get("binance_feature_snapshots", 0),
                "ws_events": sync.get("binance_ws_events", 0),
                "ws_stream_ages": health["binance_ws_stream_ages"],
            },
            "binance_feature_or_ws_not_fresh",
        ),
        _readiness_item(
            "chainlink_resolution_source",
            bool(health["chainlink_configured"] and health["chainlink_fresh"]),
            {
                "verified_observations": sync.get("verified_chainlink_observations", 0),
                "labels": sync.get("chainlink_market_labels", 0),
                "age_seconds": health["chainlink_age_seconds"],
            },
            "chainlink_verified_twap_not_fresh",
        ),
        _readiness_item(
            "research_prediction_loop",
            sync.get("research_predictions", 0) > 0 and prediction is not None,
            {
                "research_predictions": sync.get("research_predictions", 0),
                "latest_prediction_decision": prediction["decision"] if prediction else None,
            },
            "research_predictions_missing",
        ),
        _readiness_item(
            "published_model",
            model is not None and not model.get("invalid"),
            {
                "published": model is not None,
                "invalid": bool(model and model.get("invalid")),
                "independent_markets": None if model is None else model.get("independent_markets"),
            },
            "published_model_missing_or_invalid",
        ),
    ]
    blocking = [stage["blocker"] for stage in stages if not stage["ready"] and stage.get("blocker")]
    data_ready = all(stage["ready"] for stage in stages[:-1])
    research_ready = data_ready and stages[-1]["ready"]
    return {
        "status": "READY_FOR_PAPER" if research_ready else "WAITING_FOR_MODEL" if data_ready else "DATA_BLOCKED",
        "data_ready": data_ready,
        "research_ready": research_ready,
        "live_ready": False,
        "stages": stages,
        "blocking_reasons": blocking,
        "thresholds": {
            "clob_max_age_seconds": settings.data_stale_seconds,
            "binance_ws_max_age_seconds": settings.data_stale_seconds,
            "binance_slow_feature_max_age_seconds": settings.binance_slow_feature_stale_seconds,
            "polymarket_rest_orderbook_max_age_seconds": settings.polymarket_rest_orderbook_stale_seconds,
            "chainlink_max_age_seconds": settings.chainlink_heartbeat_stale_seconds,
            "conservative_edge_buffer": settings.conservative_edge_buffer,
        },
    }


def status_payload(settings: Settings) -> dict:
    now = datetime.now(timezone.utc)
    store = SQLiteStore(settings.database_path, read_only=True)
    try:
        sync = store.sync_status()
        prediction = store.latest_research_prediction()
        live_markets = store.live_polymarket_markets(
            now.isoformat(), (now + timedelta(minutes=10)).isoformat(), limit=2,
        )
        system_state = store.get_system_state()
        risk_snapshot = store.latest_statistical_risk_snapshot()
        latest_model_audit = store.latest_model_audit()
        last_model_attempt = store.get_last_model_attempt()
    finally:
        store.close()
    prediction_age = _age_seconds(now, prediction["prediction_timestamp"] if prediction else None)
    current_market = next((market for market in live_markets if market["phase"] == "CURRENT"), None)
    prediction_matches_current = bool(
        prediction and current_market and prediction["market_id"] == current_market["market_id"]
    )
    prediction_fresh = bool(
        prediction_matches_current
        and prediction_age is not None
        and prediction_age <= max(settings.data_stale_seconds, settings.sync_interval_seconds * 3)
    )
    settings_public = asdict(settings)
    settings_public["chainlink_api_key"] = "configured" if settings.chainlink_api_key else None
    settings_public["chainlink_api_secret"] = "configured" if settings.chainlink_api_secret else None
    published_model = None
    model_path = Path(settings.published_model_path)
    if model_path.exists():
        try:
            artifact = PublishedModel.load(str(model_path))
            published_model = {
                "artifact_hash": artifact.artifact_hash,
                "alpha_kind": artifact.alpha_kind,
                "market_kind": (
                    artifact.market.get("version") if artifact.market else "microprice"
                ),
                "market_weight": artifact.market_weight,
                "calibration_method": artifact.calibration_method,
                "alpha_weight": artifact.alpha_weight,
                "independent_markets": artifact.independent_markets,
                "time_scope": artifact.time_scope,
                "validation": artifact.validation,
            }
        except (ValueError, KeyError, json.JSONDecodeError):
            published_model = {"invalid": True}
    health = _build_health(settings, sync, prediction, now)
    current_prediction = prediction if prediction_fresh else None
    return {
        "mode": system_state["mode"], "armed": system_state["mode"] == "ARMED",
        "server_time": now.isoformat(),
        "sync": sync,
        "live_markets": live_markets,
        "latest_prediction": prediction,
        "current_prediction": current_prediction,
        "btc_judgment": _build_btc_judgment(current_prediction, health["chainlink_fresh"]),
        "btc_trend_judgment": _build_btc_trend_judgment(
            current_prediction, bool(health["binance_fresh"] and health["binance_ws_fresh"]),
        ),
        "prediction_health": {
            "fresh": prediction_fresh,
            "age_seconds": prediction_age,
            "matches_current_market": prediction_matches_current,
            "current_market_id": current_market["market_id"] if current_market else None,
            "latest_prediction_market_id": prediction["market_id"] if prediction else None,
        },
        "system_state": system_state,
        "statistical_risk": risk_snapshot,
        "model_runtime": {
            "last_attempted_markets": last_model_attempt,
            "next_attempt_markets": last_model_attempt + settings.auto_retrain_market_interval,
            "published": published_model,
            "latest_evaluation": latest_model_audit,
        },
        "health": health,
        "data_readiness": build_data_readiness(settings, sync, health, prediction, published_model),
        "settings": settings_public,
    }


def serve(settings: Settings, host: str = "127.0.0.1", port: int = 8000) -> None:
    cache_lock = Lock()
    cached: dict = {"at": 0.0, "payload": None}

    def cached_status_payload() -> dict:
        now = time.monotonic()
        with cache_lock:
            if cached["payload"] is None or now - cached["at"] >= 1.0:
                cached["payload"] = status_payload(settings)
                cached["at"] = time.monotonic()
            return cached["payload"]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path not in ("/api/status", "/api/health"):
                self.send_error(404)
                return
            payload = cached_status_payload()
            if path == "/api/health":
                payload = payload["health"]
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:
            return

    ThreadingHTTPServer((host, port), Handler).serve_forever()
