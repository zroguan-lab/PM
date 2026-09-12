from dataclasses import dataclass


@dataclass(frozen=True)
class GateEvidence:
    days: int
    settled_trades: int
    independent_markets: int
    model_brier: float
    market_brier: float
    net_ev: float
    recent_30d_ev: float
    conservative_ev: float
    paper_pnl: float
    calibration_degraded: bool
    dominant_regime_share: float
    clean_operation_days: int
    eligible: bool
    kill_switch_tested: bool


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reasons: tuple[str, ...]


def research_gate(evidence: GateEvidence) -> GateResult:
    reasons: list[str] = []
    if evidence.days < 30: reasons.append("less_than_30_days")
    if evidence.settled_trades < 500: reasons.append("less_than_500_trades")
    if evidence.model_brier >= evidence.market_brier: reasons.append("no_probability_edge")
    if evidence.net_ev <= 0: reasons.append("net_ev_not_positive")
    if evidence.dominant_regime_share > 0.70: reasons.append("regime_concentration_high")
    return GateResult(not reasons, tuple(reasons))


def live_gate(evidence: GateEvidence) -> GateResult:
    reasons = list(research_gate(evidence).reasons)
    if evidence.days < 60: reasons.append("less_than_60_days")
    if evidence.independent_markets < 2000: reasons.append("less_than_2000_independent_markets")
    if evidence.recent_30d_ev <= 0: reasons.append("recent_ev_not_positive")
    if evidence.conservative_ev <= 0: reasons.append("conservative_ev_not_positive")
    if evidence.paper_pnl <= 0: reasons.append("paper_pnl_not_positive")
    if evidence.calibration_degraded: reasons.append("calibration_degraded")
    if evidence.clean_operation_days < 7: reasons.append("insufficient_clean_operation")
    if not evidence.eligible: reasons.append("ineligible")
    if not evidence.kill_switch_tested: reasons.append("kill_switch_not_tested")
    return GateResult(not reasons, tuple(dict.fromkeys(reasons)))

