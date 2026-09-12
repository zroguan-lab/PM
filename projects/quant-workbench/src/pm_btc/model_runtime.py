from __future__ import annotations

import asyncio
import json
from pathlib import Path
import os
import sys

from .config import Settings
from .publication import ModelGateError, PublishedModel, publish_model
from .storage import SQLiteStore
from .training import (
    REALTIME_ALPHA_FEATURES, REALTIME_FEATURE_VERSION, fit_lightgbm_alpha,
)
from .walkforward import row_time_bucket


def _report_summary(report) -> dict:
    return {
        "model_brier": report.mean_model_brier,
        "market_brier": report.mean_market_brier,
        "raw_alpha_brier": report.mean_raw_alpha_brier,
        "raw_alpha_probability_edge": report.mean_raw_alpha_probability_edge,
        "raw_alpha_calibration_error": report.mean_raw_alpha_calibration_error,
        "calibrated_market_brier": report.mean_calibrated_market_brier,
        "market_model_brier": report.mean_market_model_brier,
        "mean_alpha_weight": report.mean_alpha_weight,
        "mean_market_model_weight": report.mean_market_model_weight,
        "probability_edge": report.mean_probability_edge,
        "calibration_error": report.mean_calibration_error,
    }


def _challenger_from_reports(logistic: dict | None, lightgbm: dict | None) -> dict | None:
    if logistic is None or lightgbm is None:
        return None
    return {
        "logistic": logistic,
        "lightgbm": lightgbm,
        "lightgbm_beats_logistic": lightgbm["model_brier"] < logistic["model_brier"],
        "lightgbm_probability_edge_positive": lightgbm["probability_edge"] > 0,
        "source": "reused_gate_oof_reports",
    }


class AutoModelRuntime:
    """Publishes only models that pass purged probability-edge and calibration gates."""

    TIME_SCOPES = ("0-30s", "31-60s", "61-120s", "121-300s")

    def __init__(self, settings: Settings, store: SQLiteStore) -> None:
        self.settings, self.store = settings, store
        self._last_attempted_markets = store.get_last_model_attempt()

    def _published_market_count(self) -> int:
        path = Path(self.settings.published_model_path)
        if not path.exists():
            return 0
        try:
            return PublishedModel.load(str(path)).independent_markets
        except (ValueError, KeyError):
            return 0

    def _try_realtime_candidate(self, rows: list[dict], minimum: int) -> tuple[PublishedModel | None, dict]:
        realtime_rows = [
            row for row in rows
            if row["features"].get("realtime_feature_version") == REALTIME_FEATURE_VERSION
            and all(row["features"].get(name) is not None for name in REALTIME_ALPHA_FEATURES)
        ]
        independent = len({row["market_id"] for row in realtime_rows})
        evidence: dict = {
            "feature_version": REALTIME_FEATURE_VERSION,
            "independent_markets": independent,
            "required_markets": minimum,
            "feature_count": len(REALTIME_ALPHA_FEATURES),
        }
        if independent < minimum:
            evidence["status"] = "WAITING_FOR_REALTIME_MARKETS"
            return None, evidence
        train_count = max(12, int(independent * 0.4))
        calibration_count = max(6, int(independent * 0.2))
        validation_count = max(6, int(independent * 0.2))
        errors: dict[str, str] = {}
        for kind, fitter in (("logistic", None), ("lightgbm", fit_lightgbm_alpha)):
            try:
                kwargs = {
                    "rows": realtime_rows, "train_count": train_count,
                    "calibration_count": calibration_count, "validation_count": validation_count,
                    "minimum_markets": minimum, "feature_names": REALTIME_ALPHA_FEATURES,
                    "alpha_kind": f"realtime-{kind}",
                }
                if fitter is not None:
                    kwargs["alpha_fitter"] = fitter
                artifact = publish_model(**kwargs)
                evidence.update({
                    "status": "SELECTED", "alpha_kind": artifact.alpha_kind,
                    "probability_edge": artifact.validation["selected_probability_edge"],
                })
                return artifact, evidence
            except (ImportError, ValueError) as error:
                errors[kind] = str(error)
        evidence.update({"status": "REJECTED", "errors": errors})
        return None, evidence

    def _try_base_family(
        self, rows: list[dict], minimum: int, *, kind: str,
    ) -> tuple[PublishedModel | None, dict[str, str], dict[str, int], dict[str, dict]]:
        fitter = fit_lightgbm_alpha if kind == "lightgbm" else None
        errors: dict[str, str] = {}
        reports: dict[str, dict] = {}
        scope_markets = {
            scope: len({
                row["market_id"] for row in rows if row_time_bucket(row) == scope
            })
            for scope in self.TIME_SCOPES
        }
        candidates: list[PublishedModel] = []
        independent = len({row["market_id"] for row in rows})
        attempts: list[tuple[str | None, int]] = [(None, independent)] + [
            (scope, scope_markets[scope]) for scope in self.TIME_SCOPES
            if scope_markets[scope] >= minimum
        ]
        for scope, candidate_markets in attempts:
            train_count = max(12, int(candidate_markets * 0.4))
            calibration_count = max(6, int(candidate_markets * 0.2))
            validation_count = max(6, int(candidate_markets * 0.2))
            label = scope or "global"
            kwargs = {
                "rows": rows, "train_count": train_count,
                "calibration_count": calibration_count,
                "validation_count": validation_count,
                "minimum_markets": minimum, "time_scope": scope,
                "minimum_validation_markets": 30 if scope else 0,
                "alpha_kind": kind,
            }
            if fitter is not None:
                kwargs["alpha_fitter"] = fitter
            try:
                candidates.append(publish_model(**kwargs))
            except (ImportError, ValueError) as error:
                errors[label] = str(error)
                if isinstance(error, ModelGateError):
                    reports[label] = _report_summary(error.report)
        if not candidates:
            return None, errors, scope_markets, reports
        selected = max(
            candidates,
            key=lambda artifact: (
                float(artifact.validation["selected_probability_edge"]),
                -float(artifact.validation.get("selected_calibration_error", float("inf"))),
            ),
        )
        return selected, errors, scope_markets, reports

    def evaluate_once(self) -> dict:
        rows = self.store.alpha_training_rows()
        independent = len({row["market_id"] for row in rows})
        minimum = self.settings.auto_publish_min_markets
        published = self._published_market_count()
        if independent < minimum:
            return {"status": "WAITING_FOR_MARKETS", "independent_markets": independent, "minimum": minimum}
        if independent < published + self.settings.auto_retrain_market_interval:
            return {"status": "MODEL_CURRENT", "independent_markets": independent, "published_markets": published}
        if (
            self._last_attempted_markets >= minimum
            and independent < self._last_attempted_markets + self.settings.auto_retrain_market_interval
        ):
            return {
                "status": "WAITING_RETRY_INTERVAL", "independent_markets": independent,
                "next_attempt": self._last_attempted_markets + self.settings.auto_retrain_market_interval,
            }
        if independent == self._last_attempted_markets:
            return {"status": "ALREADY_ATTEMPTED", "independent_markets": independent}
        self._last_attempted_markets = independent
        self.store.set_last_model_attempt(independent)
        self.store.audit("auto_model_training_started", {
            "independent_markets": independent,
            "feature_schema_version": rows[-1]["features"].get("feature_schema_version") if rows else None,
        })
        artifact, logistic_errors, scope_markets, logistic_reports = self._try_base_family(
            rows, minimum, kind="logistic",
        )
        lightgbm_errors: dict[str, str] = {}
        lightgbm_reports: dict[str, dict] = {}
        realtime_evidence: dict | None = None
        if artifact is None:
            artifact, lightgbm_errors, _, lightgbm_reports = self._try_base_family(
                rows, minimum, kind="lightgbm",
            )
            if artifact is not None:
                self.store.audit("auto_lightgbm_model_selected", {
                    "independent_markets": independent, "scope": artifact.time_scope,
                    "logistic_rejections": logistic_errors,
                    "lightgbm_rejections": lightgbm_errors,
                })
        elif artifact.time_scope is not None:
            self.store.audit("auto_scoped_model_selected", {
                "independent_markets": independent, "scope": artifact.time_scope,
                "logistic_rejections": logistic_errors,
            })
        if artifact is None:
            artifact, realtime_evidence = self._try_realtime_candidate(rows, minimum)
            self.store.audit(
                "auto_realtime_model_selected" if artifact is not None else "realtime_challenger_evaluated",
                realtime_evidence,
            )
        if artifact is None:
            combined = json.dumps({
                "logistic": logistic_errors, "lightgbm": lightgbm_errors,
            }, sort_keys=True)
            challenger = _challenger_from_reports(
                logistic_reports.get("global"), lightgbm_reports.get("global"),
            )
            if challenger is not None:
                self.store.audit("lightgbm_challenger_evaluated", {
                    "independent_markets": independent, **challenger,
                })
            self.store.audit("auto_model_rejected", {
                "independent_markets": independent, "error": combined,
                "challenger": challenger, "scoped_markets": scope_markets,
                "realtime_challenger": realtime_evidence,
            })
            return {
                "status": "REJECTED", "independent_markets": independent,
                "reason": combined, "challenger": challenger,
                "realtime_challenger": realtime_evidence,
            }
        target = Path(self.settings.published_model_path)
        temporary = target.with_suffix(target.suffix + ".tmp")
        artifact.save(str(temporary))
        temporary.replace(target)
        self.store.audit("auto_model_published", {
            "independent_markets": independent, "artifact_hash": artifact.artifact_hash,
            "probability_edge": artifact.validation["selected_probability_edge"],
            "alpha_kind": artifact.alpha_kind,
            "calibration_method": artifact.calibration_method,
        })
        return {
            "status": "PUBLISHED", "independent_markets": independent,
            "artifact_hash": artifact.artifact_hash, "alpha_kind": artifact.alpha_kind,
            "calibration_method": artifact.calibration_method,
        }

    async def run_forever(self) -> None:
        while True:
            try:
                independent = int(self.store.sync_status().get("training_ready_markets", 0))
                published = self._published_market_count()
                minimum = self.settings.auto_publish_min_markets
                retry_base = max(published, self._last_attempted_markets)
                should_attempt = (
                    independent >= minimum
                    and (retry_base < minimum or independent >= retry_base + self.settings.auto_retrain_market_interval)
                )
                if should_attempt:
                    environment = os.environ.copy()
                    process = await asyncio.create_subprocess_exec(
                        sys.executable, "-m", "pm_btc.cli", "auto-model-once",
                        "--database", self.settings.database_path,
                        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                        env=environment,
                    )
                    await process.wait()
                    self._last_attempted_markets = self.store.get_last_model_attempt()
                    if process.returncode != 0:
                        self.store.audit("auto_model_subprocess_error", {
                            "returncode": process.returncode, "independent_markets": independent,
                        })
            except Exception as error:
                self.store.audit("auto_model_runtime_error", {"error": str(error)})
            await asyncio.sleep(max(self.settings.sync_interval_seconds * 5, 10.0))
