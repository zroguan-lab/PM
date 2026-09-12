from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
from math import sqrt
from pathlib import Path
from statistics import mean, pstdev

from .config import Settings
from .publication import PublishedModel
from .storage import SQLiteStore
from .risk import StatisticalKillSwitch, StatisticalSnapshot


def build_statistical_snapshot(
    settings: Settings, store: SQLiteStore, status: dict | None = None,
) -> StatisticalSnapshot:
    evaluation = store.recent_model_evaluation_rows(300)
    by_market: dict[str, list[dict]] = {}
    for row in evaluation:
        by_market.setdefault(row["market_id"], []).append(row)
    brier_degradation = calibration_error = ood_fraction = None
    if len(by_market) >= 30:
        model_brier = mean(mean((r["model_probability"] - r["outcome"]) ** 2 for r in group) for group in by_market.values())
        market_brier = mean(mean((r["market_probability"] - r["outcome"]) ** 2 for r in group) for group in by_market.values())
        brier_degradation = model_brier - market_brier
        weighted = [(row, 1.0 / len(group)) for group in by_market.values() for row in group]
        calibration_error = 0.0
        for index in range(10):
            low, high = index / 10, (index + 1) / 10
            bucket = [(row, weight) for row, weight in weighted if low <= row["model_probability"] < high or (index == 9 and row["model_probability"] == 1)]
            if bucket:
                weight_sum = sum(weight for _, weight in bucket)
                predicted = sum(row["model_probability"] * weight for row, weight in bucket) / weight_sum
                observed = sum(row["outcome"] * weight for row, weight in bucket) / weight_sum
                calibration_error += weight_sum / len(by_market) * abs(predicted - observed)
        ood_fraction = mean(
            mean(float(r["features"].get("ood_risk", 0)) > settings.ood_risk_limit for r in group)
            for group in by_market.values()
        )
    pnls = store.recent_settled_market_pnls(200)
    rolling_ev_lower_bound = None
    if len(pnls) >= 200:
        rolling_ev_lower_bound = mean(pnls) - 1.2815515655446004 * pstdev(pnls) / sqrt(len(pnls))
    drawdown = None
    if pnls:
        equity = peak = settings.paper_starting_cash
        worst = 0.0
        for pnl in pnls:
            equity += pnl
            peak = max(peak, equity)
            worst = max(worst, (peak - equity) / peak if peak > 0 else 1.0)
        drawdown = worst
    status = status or store.sync_status()
    return StatisticalSnapshot(
        rolling_ev_lower_bound=rolling_ev_lower_bound,
        brier_degradation=brier_degradation,
        calibration_error=calibration_error,
        ood_fraction=ood_fraction,
        drawdown=drawdown,
        integrity_ok=status.get("resolution_reconciliation_mismatches", 0) == 0,
    )


class RiskMonitorRuntime:
    """Fail-closed readiness state. It can enter PAPER, never ARMED automatically."""

    def __init__(self, settings: Settings, store: SQLiteStore) -> None:
        self.settings, self.store = settings, store
        self.kill_switch = StatisticalKillSwitch()
        self._last_snapshot_at: datetime | None = None

    def evaluate_once(self) -> dict:
        blocking: list[str] = []
        advisory: list[str] = []
        model_path = Path(self.settings.published_model_path)
        if not model_path.exists():
            blocking.append("published_model_missing")
        else:
            try:
                PublishedModel.load(str(model_path))
            except (ValueError, KeyError):
                blocking.append("published_model_invalid")
        status = self.store.sync_status()
        if status.get("resolution_reconciliation_mismatches", 0) > 0:
            blocking.append("resolution_reconciliation_mismatch")
        latest_chainlink = status.get("latest_chainlink_observation_at")
        if not latest_chainlink:
            blocking.append("chainlink_feed_unavailable")
        else:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(latest_chainlink)).total_seconds()
            if age > self.settings.chainlink_heartbeat_stale_seconds:
                blocking.append("chainlink_feed_stale")
        latest_binance = status.get("latest_binance_feature_at")
        if not latest_binance:
            blocking.append("binance_feed_unavailable")
        else:
            binance_age = (datetime.now(timezone.utc) - datetime.fromisoformat(latest_binance)).total_seconds()
            if binance_age >= self.settings.binance_slow_feature_stale_seconds:
                blocking.append("binance_feed_stale")
        ws_health = status.get("binance_ws_stream_health") or {}
        for connection in ("spot", "futures_public", "futures_market"):
            stream = ws_health.get(connection)
            if stream is None:
                blocking.append(f"binance_ws_{connection}_unavailable")
                continue
            ws_age = (
                datetime.now(timezone.utc) - datetime.fromisoformat(stream["last_received_timestamp"])
            ).total_seconds()
            if ws_age > self.settings.data_stale_seconds:
                blocking.append(f"binance_ws_{connection}_stale")
        latest_clob = status.get("latest_polymarket_clob_event_at")
        if not latest_clob:
            blocking.append("polymarket_clob_feed_unavailable")
        else:
            clob_age = (datetime.now(timezone.utc) - datetime.fromisoformat(latest_clob)).total_seconds()
            if clob_age > self.settings.data_stale_seconds:
                blocking.append("polymarket_clob_feed_stale")
        if status.get("reconciled_market_labels", 0) < self.settings.research_trades:
            advisory.append("research_gate_labels_incomplete")
        snapshot = build_statistical_snapshot(self.settings, self.store, status)
        kill_reasons = [reason.value for reason in self.kill_switch.evaluate(snapshot)]
        if kill_reasons:
            blocking.extend(f"statistical_kill:{reason}" for reason in kill_reasons)
        now = datetime.now(timezone.utc)
        if self._last_snapshot_at is None or (now - self._last_snapshot_at).total_seconds() >= 30:
            self.store.save_statistical_risk_snapshot(asdict(snapshot), kill_reasons)
            self._last_snapshot_at = now
        mode = "DISARMED" if blocking else "PAPER"
        reasons = blocking + advisory
        self.store.set_system_state(mode, reasons)
        return {"mode": mode, "blocking_reasons": blocking, "advisory_reasons": advisory, "reasons": reasons}

    async def run_forever(self) -> None:
        while True:
            try:
                self.evaluate_once()
            except Exception as error:
                self.store.set_system_state("DISARMED", ["risk_monitor_error"])
                self.store.audit("risk_monitor_error", {"error": str(error)})
            await asyncio.sleep(max(self.settings.sync_interval_seconds * 2, 5.0))
