from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .domain import EdgeEstimate, ExecutionDecision, ExecutionKind, ProbabilityEstimate, ResolutionState, Side


@dataclass(frozen=True)
class MakerAssumptions:
    price: float
    fill_probability: float
    adverse_selection_cost: float
    opportunity_cost: float
    execution_risk_penalty: float


class NoTradeFilter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def reasons(
        self,
        probability: ProbabilityEstimate,
        resolution: ResolutionState,
        conservative_edge: float,
        data_age_seconds: float,
        execution_quality: float,
        eligible: bool,
        armed: bool,
    ) -> tuple[str, ...]:
        reasons = list(resolution.no_trade_reasons)
        if conservative_edge < self.settings.conservative_edge_buffer:
            reasons.append("conservative_edge_below_buffer")
        if probability.ood_risk > self.settings.ood_risk_limit:
            reasons.append("ood_risk_high")
        if probability.p_upper - probability.p_lower > self.settings.probability_interval_max_width:
            reasons.append("probability_interval_too_wide")
        if data_age_seconds > self.settings.data_stale_seconds:
            reasons.append("data_stale")
        if execution_quality <= 0:
            reasons.append("execution_quality_insufficient")
        if not eligible:
            reasons.append("account_or_region_ineligible")
        if not armed:
            reasons.append("system_disarmed")
        return tuple(sorted(set(reasons)))


class ExecutionPolicy:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.filter = NoTradeFilter(settings)

    def choose(
        self,
        side: Side,
        probability: ProbabilityEstimate,
        taker_edge: EdgeEstimate,
        maker: MakerAssumptions,
        resolution: ResolutionState,
        size: float,
        data_age_seconds: float,
        execution_quality: float,
        eligible: bool,
        armed: bool,
    ) -> ExecutionDecision:
        p_cons = probability.conservative(side)
        maker_net = p_cons - maker.price - maker.execution_risk_penalty
        maker_ev = (
            maker.fill_probability * maker_net
            - maker.adverse_selection_cost
            - maker.opportunity_cost
        )
        taker_ev = taker_edge.conservative_net_edge
        selected = max(maker_ev, taker_ev)
        reasons = self.filter.reasons(
            probability,
            resolution,
            selected,
            data_age_seconds,
            execution_quality,
            eligible,
            armed,
        )
        if reasons:
            return ExecutionDecision(
                kind=ExecutionKind.NO_TRADE,
                side=None,
                price=None,
                size=0.0,
                expected_ev=selected,
                conservative_edge=selected,
                reasons=reasons,
                metadata={"maker_ev": maker_ev, "taker_ev": taker_ev},
            )
        if maker_ev >= taker_ev:
            return ExecutionDecision(
                kind=ExecutionKind.MAKER,
                side=side,
                price=maker.price,
                size=size,
                expected_ev=maker_ev,
                conservative_edge=maker_ev,
                metadata={"fill_probability": maker.fill_probability, "taker_ev": taker_ev},
            )
        return ExecutionDecision(
            kind=ExecutionKind.TAKER,
            side=side,
            price=taker_edge.executable_price,
            size=size,
            expected_ev=taker_ev,
            conservative_edge=taker_ev,
            metadata={"maker_ev": maker_ev},
        )

