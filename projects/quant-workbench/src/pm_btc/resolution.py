from __future__ import annotations

from datetime import datetime
from math import ceil, isfinite

from .domain import ChainlinkObservation, MarketRuleVersion, ResolutionState, Side, VerificationStatus


class ResolutionStateEngine:
    """Reconstructs the Chainlink-rule state without using exchange prices as labels."""

    def calculate(
        self,
        rule: MarketRuleVersion,
        start_price: float,
        observations: list[ChainlinkObservation],
        now: datetime,
        proxy_price: float | None,
        expected_remaining_price_std: float,
    ) -> ResolutionState:
        reasons: list[str] = []
        if start_price <= 0:
            raise ValueError("start_price must be positive")
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")

        verified: dict[datetime, ChainlinkObservation] = {}
        for observation in observations:
            if observation.market_id != rule.market_id:
                continue
            if observation.stream_id != rule.chainlink_stream_id:
                reasons.append("chainlink_stream_mismatch")
                continue
            if observation.verification_status is not VerificationStatus.VERIFIED:
                reasons.append("chainlink_unverified")
                continue
            if rule.start_time <= observation.source_timestamp <= rule.end_time:
                verified[observation.source_timestamp] = observation

        ordered = sorted(verified.values(), key=lambda x: x.source_timestamp)
        total_duration = (rule.end_time - rule.start_time).total_seconds()
        cutoff = min(max(now, rule.start_time), rule.end_time)
        observed_duration = (cutoff - rule.start_time).total_seconds()
        remaining_duration = max((rule.end_time - cutoff).total_seconds(), 0.0)

        accumulated = 0.0
        if ordered:
            for index, item in enumerate(ordered):
                next_time = ordered[index + 1].source_timestamp if index + 1 < len(ordered) else cutoff
                segment_start = max(item.source_timestamp, rule.start_time)
                segment_end = min(next_time, cutoff, rule.end_time)
                seconds = max((segment_end - segment_start).total_seconds(), 0.0)
                accumulated += item.twap_60s * seconds

        current_twap = ordered[-1].twap_60s if ordered else None
        # Polymarket compares the Chainlink 60-second TWAP at the interval end
        # with the 60-second TWAP at the interval start. It does not average the
        # rolling TWAP stream over the entire five-minute market again.
        required = start_price if remaining_duration > 0 else None

        gap = None
        pressure = None
        if required is not None and proxy_price is not None and isfinite(proxy_price):
            gap = proxy_price - start_price
            if expected_remaining_price_std > 0:
                pressure = gap / expected_remaining_price_std

        exact_end_present = any(item.source_timestamp == rule.end_time for item in ordered)
        complete = remaining_duration == 0 and observed_duration == total_duration and exact_end_present
        provisional = None
        if current_twap is not None:
            provisional = Side.UP if current_twap >= start_price else Side.DOWN

        expected_buckets = max(int(ceil(observed_duration / 60)), 0)
        covered_buckets = {
            min(int((item.source_timestamp - rule.start_time).total_seconds() // 60), 4)
            for item in ordered
        }
        required_buckets = set(range(expected_buckets))
        if not required_buckets.issubset(covered_buckets):
            reasons.append("chainlink_observation_gap")
        if current_twap is None:
            reasons.append("chainlink_state_incomplete")
        if remaining_duration == 0 and not exact_end_present:
            reasons.append("chainlink_end_price_missing")
        confidence = min(1.0, len(covered_buckets) / max(expected_buckets, 1))
        if reasons:
            confidence *= 0.5

        return ResolutionState(
            market_id=rule.market_id,
            start_price=start_price,
            accumulated_price_time=accumulated,
            current_cumulative_twap=current_twap,
            remaining_duration=remaining_duration,
            required_remaining_twap=required,
            required_future_twap_gap=gap,
            resolution_pressure=pressure,
            provisional_resolution=provisional,
            resolution_confidence=confidence,
            fraction_window_observed=observed_duration / total_duration,
            complete=complete,
            no_trade_reasons=tuple(sorted(set(reasons))),
        )
