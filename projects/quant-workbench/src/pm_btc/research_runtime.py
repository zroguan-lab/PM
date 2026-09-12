from __future__ import annotations

import asyncio
import json
from dataclasses import fields
from datetime import datetime, timedelta, timezone
from statistics import median, pstdev
from pathlib import Path
from typing import Any

from .config import Settings
from .domain import BookLevel, ChainlinkObservation, ExecutionKind, MarketRuleVersion, OrderBook, ProbabilityEstimate, ResolutionState, Side, VerificationStatus
from .edge import EdgeCalculator
from .execution import ExecutionPolicy, MakerAssumptions
from .models import MarketModel
from .resolution import ResolutionStateEngine
from .publication import PublishedModel
from .storage import SQLiteStore
from .regime import RegimeEngine, RegimeThresholds
from .training import FEATURE_SCHEMA_VERSION, REALTIME_FEATURE_VERSION


def _book(token_id: str, raw: dict[str, Any]) -> OrderBook:
    return OrderBook(
        token_id=token_id,
        bids=tuple(BookLevel(float(level["price"]), float(level["size"])) for level in raw["bids"]),
        asks=tuple(BookLevel(float(level["price"]), float(level["size"])) for level in raw["asks"]),
        timestamp=datetime.fromisoformat(raw["source_timestamp"]),
    )


class RealtimeResearchRuntime:
    """Creates auditable market-baseline rows; trading stays blocked until labels/model are valid."""

    def __init__(self, settings: Settings, store: SQLiteStore) -> None:
        self.settings, self.store = settings, store
        self.market_model = MarketModel()
        self.resolution_engine = ResolutionStateEngine()
        self.edge_calculator = EdgeCalculator()
        self.execution_policy = ExecutionPolicy(settings)
        self.published_model: PublishedModel | None = None
        self._published_model_mtime_ns: int | None = None
        model_path = Path(settings.published_model_path)
        if model_path.exists():
            try:
                self.published_model = PublishedModel.load(str(model_path))
                self._published_model_mtime_ns = model_path.stat().st_mtime_ns
            except (ValueError, KeyError, json.JSONDecodeError) as error:
                self.store.audit("published_model_rejected", {"error": str(error), "path": str(model_path)})

    def _refresh_published_model(self) -> None:
        model_path = Path(self.settings.published_model_path)
        if not model_path.exists():
            self.published_model = None
            self._published_model_mtime_ns = None
            return
        mtime = model_path.stat().st_mtime_ns
        if mtime == self._published_model_mtime_ns:
            return
        try:
            candidate = PublishedModel.load(str(model_path))
        except (ValueError, KeyError, json.JSONDecodeError) as error:
            self.store.audit("published_model_hot_reload_rejected", {"error": str(error), "path": str(model_path)})
            return
        previous = self.published_model.artifact_hash if self.published_model else None
        self.published_model = candidate
        self._published_model_mtime_ns = mtime
        self.store.audit("published_model_hot_reloaded", {
            "previous_artifact_hash": previous, "artifact_hash": candidate.artifact_hash,
            "independent_markets": candidate.independent_markets,
        })

    @staticmethod
    def _quantile(values: list[float], fraction: float, fallback: float) -> float:
        if not values:
            return fallback
        ordered = sorted(values)
        return ordered[round((len(ordered) - 1) * fraction)]

    def _regime_features(self, now: datetime, up_book: OrderBook | None, down_book: OrderBook | None) -> dict[str, Any]:
        mids = self.store.recent_spot_mids(360, now.isoformat())
        returns = [(mids[i] - mids[i - 1]) / mids[i - 1] for i in range(1, len(mids)) if mids[i - 1] > 0]
        window = 20
        rolling_vol = [pstdev(returns[i - window:i]) for i in range(window, len(returns) + 1)]
        rolling_trend = [sum(returns[i - window:i]) for i in range(window, len(returns) + 1)]
        current_vol = rolling_vol[-1] if rolling_vol else 0.0
        current_trend = rolling_trend[-1] if rolling_trend else 0.0
        history = self.store.recent_orderbook_microstructure(now.isoformat())
        historical_depth = [item["depth"] for item in history]
        historical_spread = [item["spread"] for item in history]
        books = [book for book in (up_book, down_book) if book is not None]
        current_depth = sum(sum(level.size for level in list(book.bids)[:5] + list(book.asks)[:5]) for book in books)
        current_spread = max((book.spread or 1.0 for book in books), default=1.0)
        thresholds = RegimeThresholds(
            volatility_low=self._quantile(rolling_vol[:-1], .33, max(current_vol * .8, 1e-9)),
            volatility_high=self._quantile(rolling_vol[:-1], .67, max(current_vol * 1.2, 2e-9)),
            trend_abs=max(median([abs(value) for value in rolling_trend[:-1]]) if len(rolling_trend) > 1 else .0001, 1e-6),
            liquidity_low=self._quantile(historical_depth, .33, max(current_depth * .8, 1.0)),
            spread_tight=self._quantile(historical_spread, .33, .02),
            spread_wide=self._quantile(historical_spread, .67, .10),
        )
        regime = RegimeEngine(thresholds).classify(current_vol, current_trend, current_depth, current_spread, now)
        codes = {"low": -1.0, "normal": 0.0, "high": 1.0, "down": -1.0, "flat": 0.0,
                 "up": 1.0, "thin": -1.0, "tight": -1.0, "wide": 1.0,
                 "asia": -1.0, "europe": 0.0, "us": 1.0}
        return {
            "volatility_regime": regime.volatility, "trend_regime": regime.trend,
            "liquidity_regime": regime.liquidity, "time_of_day_regime": regime.time_of_day,
            "spread_regime": regime.spread, "regime_key": regime.key,
            "volatility_regime_code": codes[regime.volatility], "trend_regime_code": codes[regime.trend],
            "liquidity_regime_code": codes[regime.liquidity], "time_of_day_regime_code": codes[regime.time_of_day],
            "spread_regime_code": codes[regime.spread], "rolling_volatility": current_vol,
            "rolling_trend": current_trend, "book_depth_top5": current_depth, "book_spread_max": current_spread,
        }

    def _resolution_features(self, inputs: dict[str, Any], now: datetime) -> tuple[dict[str, Any], list[str], ResolutionState | None]:
        raw = self.store.resolution_inputs(inputs["market_id"], inputs["rule_hash"])
        if not raw:
            return {}, ["chainlink_missing_or_unverified"], None
        rule_values = dict(raw["rule"])
        rule_values["start_time"] = datetime.fromisoformat(rule_values["start_time"])
        rule_values["end_time"] = datetime.fromisoformat(rule_values["end_time"])
        allowed = {item.name for item in fields(MarketRuleVersion)}
        rule = MarketRuleVersion(**{key: value for key, value in rule_values.items() if key in allowed})
        fee_features = {
            "taker_fee_rate_up": float((rule.fee_schedule.get("UP") or {}).get("rate", 0)),
            "taker_fee_rate_down": float((rule.fee_schedule.get("DOWN") or {}).get("rate", 0)),
            "taker_fee_exponent_up": float((rule.fee_schedule.get("UP") or {}).get("exponent", 1)),
            "taker_fee_exponent_down": float((rule.fee_schedule.get("DOWN") or {}).get("exponent", 1)),
        }
        if not raw["observations"]:
            return fee_features, ["chainlink_missing_or_unverified"], None
        observations = [ChainlinkObservation(
            stream_id=item["stream_id"], report_id=item["report_id"],
            source_timestamp=datetime.fromisoformat(item["source_timestamp"]),
            received_timestamp=datetime.fromisoformat(item["received_timestamp"]),
            twap_60s=float(item["twap_60s"]),
            verification_status=VerificationStatus(item["verification_status"]),
            raw_payload_hash=item["raw_payload_hash"], market_id=inputs["market_id"],
        ) for item in raw["observations"]]
        verified = [item for item in observations if item.verification_status is VerificationStatus.VERIFIED]
        exact_start = [item for item in verified if item.source_timestamp == rule.start_time]
        if not exact_start:
            return fee_features, ["chainlink_start_price_missing"], None
        mids = self.store.recent_spot_mids()
        price_std = max(pstdev(mids), 1.0) if len(mids) >= 2 else 1.0
        proxy = (inputs.get("binance") or {}).get("spot_mid")
        state = self.resolution_engine.calculate(
            rule, exact_start[0].twap_60s, observations, now, proxy, price_std
        )
        current_twap = float(state.current_cumulative_twap or state.start_price)
        gap = float(state.required_future_twap_gap or 0.0)
        remaining_zscore = (current_twap - state.start_price) / price_std
        divergence = float(proxy - current_twap) if proxy is not None else 0.0
        features = {
            **fee_features,
            "chainlink_start_price": state.start_price,
            "current_cumulative_twap": state.current_cumulative_twap,
            "remaining_duration": state.remaining_duration,
            "required_remaining_twap": state.required_remaining_twap,
            "required_future_twap_gap": state.required_future_twap_gap,
            "resolution_pressure": state.resolution_pressure,
            "gap_bps": gap / state.start_price * 10_000,
            "expected_remaining_price_std": price_std,
            "remaining_twap_zscore": remaining_zscore,
            "distance_to_lock": abs(remaining_zscore),
            "chainlink_binance_divergence": divergence,
            "chainlink_binance_divergence_bps": divergence / current_twap * 10_000,
            "resolution_confidence": state.resolution_confidence,
            "fraction_window_observed": state.fraction_window_observed,
            "provisional_resolution": state.provisional_resolution.value if state.provisional_resolution else None,
        }
        return features, list(state.no_trade_reasons), state

    def _binance_ws_features(self, now: datetime) -> tuple[dict[str, Any], list[str]]:
        features: dict[str, Any] = {}
        reasons: list[str] = []
        flows = self.store.recent_binance_orderflow(
            (now - timedelta(seconds=60)).replace(microsecond=0).isoformat(),
            now.replace(microsecond=0).isoformat(),
        )
        books = self.store.latest_binance_ws_books()
        for source, prefix in (("SPOT", "binance_spot"), ("FUTURES", "binance_futures")):
            flow = flows.get(source, {})
            buy_notional = float(flow.get("buy_notional") or 0.0)
            sell_notional = float(flow.get("sell_notional") or 0.0)
            gross_notional = buy_notional + sell_notional
            features.update({
                f"{prefix}_trade_count_60s": int(flow.get("trade_count") or 0),
                f"{prefix}_trade_notional_60s": gross_notional,
                f"{prefix}_trade_imbalance_60s": (
                    (buy_notional - sell_notional) / gross_notional if gross_notional > 0 else 0.0
                ),
            })
            book = books.get(source)
            if book is None:
                reasons.append(f"{prefix}_ws_book_missing")
                continue
            bid = float(book["best_bid"])
            ask = float(book["best_ask"])
            mid = (bid + ask) / 2
            top_total = float(book["best_bid_size"]) + float(book["best_ask_size"])
            depth_total = float(book["depth_bid_size"]) + float(book["depth_ask_size"])
            received = datetime.fromisoformat(str(book["received_timestamp"]))
            age = max(0.0, (now - received).total_seconds())
            features.update({
                f"{prefix}_ws_mid": mid,
                f"{prefix}_ws_spread_bps": (ask - bid) / mid * 10_000,
                f"{prefix}_ws_top_imbalance": (
                    (float(book["best_bid_size"]) - float(book["best_ask_size"])) / top_total
                    if top_total > 0 else 0.0
                ),
                f"{prefix}_ws_depth_imbalance": (
                    (float(book["depth_bid_size"]) - float(book["depth_ask_size"])) / depth_total
                    if depth_total > 0 else 0.0
                ),
                f"{prefix}_ws_age_seconds": age,
            })
            if age > self.settings.data_stale_seconds:
                reasons.append(f"{prefix}_ws_book_stale")
        spot_mid = features.get("binance_spot_ws_mid")
        futures_mid = features.get("binance_futures_ws_mid")
        if spot_mid and futures_mid:
            features["binance_ws_basis_bps"] = (futures_mid - spot_mid) / spot_mid * 10_000

        health = self.store.binance_ws_stream_health()
        for connection in ("spot", "futures_public", "futures_market"):
            item = health.get(connection)
            if item is None:
                reasons.append(f"binance_ws_{connection}_missing")
                continue
            age = max(0.0, (now - datetime.fromisoformat(item["last_received_timestamp"])).total_seconds())
            features[f"binance_ws_{connection}_age_seconds"] = age
            if age > self.settings.data_stale_seconds:
                reasons.append(f"binance_ws_{connection}_stale")
        return features, reasons

    def evaluate_once(self, now: datetime | None = None) -> dict[str, Any]:
        self._refresh_published_model()
        now = now or datetime.now(timezone.utc)
        inputs = self.store.current_research_inputs(now.isoformat())
        if inputs is None:
            return {"status": "NO_ACTIVE_MARKET", "saved": False}
        reasons: list[str] = []
        probability = None
        up_book = down_book = None
        if "UP" not in inputs["books"] or "DOWN" not in inputs["books"]:
            reasons.append("orderbook_incomplete")
        else:
            try:
                up_book = _book(inputs["up_token_id"], inputs["books"]["UP"])
                down_book = _book(inputs["down_token_id"], inputs["books"]["DOWN"])
                probability = self.market_model.probability_up(up_book, down_book)
            except ValueError:
                reasons.append("orderbook_two_sided_liquidity_missing")
        resolution_features, resolution_reasons, resolution_state = self._resolution_features(inputs, now)
        reasons.extend(resolution_reasons)
        if resolution_state is not None:
            self.store.save_resolution_state(
                resolution_state, inputs["rule_hash"], now.replace(microsecond=0).isoformat(),
                int(inputs["verified_chainlink_observations"]),
            )
        if not inputs.get("binance"):
            reasons.append("binance_features_missing")
        else:
            binance_timestamp = datetime.fromisoformat(str(inputs["binance"]["received_timestamp"]))
            if max(0.0, (now - binance_timestamp).total_seconds()) >= self.settings.binance_slow_feature_stale_seconds:
                reasons.append("binance_features_stale")
        binance_ws_features, binance_ws_reasons = self._binance_ws_features(now)
        reasons.extend(binance_ws_reasons)
        latest_clob_event = self.store.latest_polymarket_clob_event_at()
        clob_features_fresh = False
        if latest_clob_event is None:
            reasons.append("polymarket_clob_features_missing")
        else:
            clob_age = max(0.0, (now - datetime.fromisoformat(latest_clob_event)).total_seconds())
            if clob_age > self.settings.data_stale_seconds:
                reasons.append("polymarket_clob_features_stale")
            else:
                clob_features_fresh = True
        timestamp = now.replace(microsecond=0).isoformat()
        features = dict(inputs.get("binance") or {})
        features.update(binance_ws_features)
        features["feature_schema_version"] = FEATURE_SCHEMA_VERSION
        features["verified_chainlink_observations"] = inputs["verified_chainlink_observations"]
        recent_trades = self.store.recent_polymarket_trades(
            inputs["market_id"], (now - timedelta(seconds=60)).isoformat(), now.isoformat()
        )
        signed_volume = 0.0
        gross_volume = 0.0
        for trade in recent_trades:
            volume = float(trade["size"])
            favors_up = (
                (trade["outcome"] == "UP" and trade["side"] == "BUY")
                or (trade["outcome"] == "DOWN" and trade["side"] == "SELL")
            )
            signed_volume += volume if favors_up else -volume
            gross_volume += volume
        features.update({
            "polymarket_trade_count_60s": len(recent_trades),
            "polymarket_trade_volume_60s": gross_volume,
            "polymarket_trade_imbalance_60s": signed_volume / gross_volume if gross_volume > 0 else 0.0,
        })
        if clob_features_fresh and not binance_ws_reasons:
            features["realtime_feature_version"] = REALTIME_FEATURE_VERSION
        features.update(resolution_features)
        features.update(self._regime_features(now, up_book, down_book))
        model_values: dict[str, Any] = {}
        conservative_edge = None
        execution_decision = None
        system_state = self.store.get_system_state()
        if system_state["mode"] != "PAPER":
            reasons.append("system_not_paper_ready")
        remaining_seconds = max(0.0, (datetime.fromisoformat(inputs["end_time"]) - now).total_seconds())
        current_time_scope = "0-30s" if remaining_seconds <= 30 else "31-60s" if remaining_seconds <= 60 else "61-120s" if remaining_seconds <= 120 else "121-300s"
        features["time_scope"] = current_time_scope
        model_scope_allowed = self.published_model is None or self.published_model.time_scope in (None, current_time_scope)
        if self.published_model is not None and not model_scope_allowed:
            reasons.append("model_time_scope_excluded")
        if self.published_model is None or probability is None or not model_scope_allowed:
            reasons.append("trained_calibrated_alpha_model_unavailable")
        else:
            model_values = self.published_model.predict(probability, features)
            features["market_model_probability_up"] = model_values.get(
                "market_model_probability",
            )
            features["ood_risk"] = model_values["ood_risk"]
            estimate = ProbabilityEstimate(
                market_probability=probability,
                alpha_delta=model_values["p_calibrated"] - probability,
                p_raw=model_values["p_raw"], p_calibrated=model_values["p_calibrated"],
                p_lower=model_values["p_lower"], p_upper=model_values["p_upper"],
                confidence=max(0.0, 1.0 - (model_values["p_upper"] - model_values["p_lower"]) - model_values["ood_risk"]),
                ood_risk=model_values["ood_risk"], model_version=model_values["model_version"],
            )
            if model_values["ood_risk"] > self.settings.ood_risk_limit:
                reasons.append("ood_risk_high")
            if model_values["p_upper"] - model_values["p_lower"] > self.settings.probability_interval_max_width:
                reasons.append("probability_interval_too_wide")
            if up_book is not None and down_book is not None:
                up_edge = self.edge_calculator.calculate_taker(
                    Side.UP, estimate, up_book, 1.0,
                    float(features.get("taker_fee_rate_up", 0)),
                    stressed_slippage=0.005, execution_risk_penalty=0.002,
                    fee_exponent=int(features.get("taker_fee_exponent_up", 1)),
                )
                down_edge = self.edge_calculator.calculate_taker(
                    Side.DOWN, estimate, down_book, 1.0,
                    float(features.get("taker_fee_rate_down", 0)),
                    stressed_slippage=0.005, execution_risk_penalty=0.002,
                    fee_exponent=int(features.get("taker_fee_exponent_down", 1)),
                )
                conservative_edge = max(up_edge.conservative_net_edge, down_edge.conservative_net_edge)
                best_edge = up_edge if up_edge.conservative_net_edge >= down_edge.conservative_net_edge else down_edge
                features.update({
                    "best_edge_side": best_edge.side.value,
                    "research_side": best_edge.side.value,
                    "research_executable_price": best_edge.executable_price,
                    "research_fees_per_share": best_edge.fees,
                    "research_slippage_per_share": best_edge.slippage,
                    "research_raw_edge": best_edge.raw_edge,
                    "research_executable_edge": best_edge.executable_edge,
                    "research_net_edge": best_edge.net_edge,
                    "research_risk_adjusted_edge": best_edge.risk_adjusted_edge,
                    "research_conservative_net_edge": best_edge.conservative_net_edge,
                })
                if conservative_edge < self.settings.conservative_edge_buffer:
                    reasons.append("conservative_edge_below_buffer")
                if resolution_state is not None:
                    candidates = []
                    for side, book, edge in ((Side.UP, up_book, up_edge), (Side.DOWN, down_book, down_edge)):
                        bid, ask = book.best_bid, book.best_ask
                        if bid is None or ask is None:
                            continue
                        maker_price = min(ask, bid + max(0.001, min(0.01, (ask - bid) / 2)))
                        decision = self.execution_policy.choose(
                            side=side, probability=estimate, taker_edge=edge,
                            maker=MakerAssumptions(
                                price=maker_price, fill_probability=0.50,
                                adverse_selection_cost=0.002, opportunity_cost=0.001,
                                execution_risk_penalty=0.002,
                            ),
                            resolution=resolution_state, size=1.0,
                            data_age_seconds=max(0.0, (now - book.timestamp).total_seconds()),
                            execution_quality=1.0 if book.spread is not None and book.spread <= 0.10 else 0.0,
                            eligible=True, armed=True,
                        )
                        candidates.append(decision)
                    if candidates:
                        execution_decision = max(candidates, key=lambda item: item.expected_ev)
                        reasons.extend(execution_decision.reasons)
                        features.update({
                            "execution_kind": execution_decision.kind.value,
                            "execution_side": execution_decision.side.value if execution_decision.side else None,
                            "execution_price": execution_decision.price,
                            "execution_size": execution_decision.size,
                            "execution_expected_ev": execution_decision.expected_ev,
                            "execution_metadata": execution_decision.metadata,
                        })
        decision_name = "NO_TRADE"
        if execution_decision is not None and execution_decision.kind is not ExecutionKind.NO_TRADE and not reasons:
            decision_name = execution_decision.kind.value
        prediction = {
            "market_id": inputs["market_id"], "prediction_timestamp": timestamp,
            "market_probability_up": probability,
            "p_raw": model_values.get("p_raw"), "p_calibrated": model_values.get("p_calibrated"),
            "p_lower": model_values.get("p_lower"), "p_upper": model_values.get("p_upper"),
            "conservative_edge": conservative_edge, "decision": decision_name,
            "no_trade_reasons": sorted(set(reasons)), "features": features,
            "model_version": model_values.get("model_version", "market-baseline-only-v1"),
        }
        saved = self.store.save_research_prediction(prediction)
        return {"status": decision_name, "saved": saved, **prediction}

    def finalize_chainlink_labels(self, now: datetime | None = None) -> dict[str, int]:
        now = now or datetime.now(timezone.utc)
        finalized = 0
        rejected = 0
        for candidate in self.store.markets_pending_labels(now.isoformat()):
            raw = self.store.resolution_inputs(candidate["market_id"], candidate["rule_hash"])
            if not raw or not raw["observations"]:
                rejected += 1
                continue
            rule_values = dict(raw["rule"])
            rule_values["start_time"] = datetime.fromisoformat(rule_values["start_time"])
            rule_values["end_time"] = datetime.fromisoformat(rule_values["end_time"])
            allowed = {item.name for item in fields(MarketRuleVersion)}
            rule = MarketRuleVersion(**{key: value for key, value in rule_values.items() if key in allowed})
            observations = [ChainlinkObservation(
                stream_id=item["stream_id"], report_id=item["report_id"],
                source_timestamp=datetime.fromisoformat(item["source_timestamp"]),
                received_timestamp=datetime.fromisoformat(item["received_timestamp"]),
                twap_60s=float(item["twap_60s"]),
                verification_status=VerificationStatus(item["verification_status"]),
                raw_payload_hash=item["raw_payload_hash"], market_id=candidate["market_id"],
            ) for item in raw["observations"]]
            verified = [item for item in observations if item.verification_status is VerificationStatus.VERIFIED]
            exact_start = [item for item in verified if item.source_timestamp == rule.start_time]
            if not exact_start:
                rejected += 1
                continue
            state = self.resolution_engine.calculate(
                rule, exact_start[0].twap_60s, observations, rule.end_time, None, 1.0
            )
            self.store.save_resolution_state(
                state, candidate["rule_hash"], rule.end_time.isoformat(), len(verified),
            )
            if not state.complete or state.no_trade_reasons or state.current_cumulative_twap is None:
                rejected += 1
                continue
            saved = self.store.save_market_label({
                "market_id": candidate["market_id"], "rule_hash": candidate["rule_hash"],
                "start_price": state.start_price, "final_twap": state.current_cumulative_twap,
                "outcome": state.provisional_resolution.value,
                "observation_count": len(verified), "finalized_at": now.isoformat(),
            })
            finalized += int(saved)
        return {"finalized": finalized, "rejected": rejected}

    async def run_forever(self) -> None:
        while True:
            try:
                self.finalize_chainlink_labels()
                self.store.reconcile_resolved_markets()
                self.store.settle_research_ledger()
                self.evaluate_once()
            except Exception as error:
                self.store.audit("research_runtime_error", {"error": str(error)})
            await asyncio.sleep(self.settings.sync_interval_seconds)
