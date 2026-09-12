from __future__ import annotations

from dataclasses import dataclass

from .domain import BookLevel, EdgeEstimate, OrderBook, ProbabilityEstimate, Side


def polymarket_fee_per_share(price: float, fee_rate: float, exponent: int = 1) -> float:
    if exponent < 1:
        raise ValueError("fee exponent must be positive")
    return round(fee_rate * (price * (1.0 - price)) ** exponent, 5)


@dataclass(frozen=True)
class FillQuote:
    average_price: float
    filled_size: float
    slippage_per_share: float


def quote_taker(book: OrderBook, requested_size: float) -> FillQuote:
    if requested_size <= 0:
        raise ValueError("requested_size must be positive")
    remaining = requested_size
    notional = 0.0
    best = book.best_ask
    if best is None:
        return FillQuote(average_price=1.0, filled_size=0.0, slippage_per_share=1.0)
    for level in sorted(book.asks, key=lambda item: item.price):
        take = min(remaining, level.size)
        notional += take * level.price
        remaining -= take
        if remaining <= 1e-12:
            break
    filled = requested_size - remaining
    if filled <= 0:
        return FillQuote(average_price=1.0, filled_size=0.0, slippage_per_share=1.0)
    average = notional / filled
    return FillQuote(average_price=average, filled_size=filled, slippage_per_share=max(0.0, average - best))


class EdgeCalculator:
    def calculate_taker(
        self,
        side: Side,
        probability: ProbabilityEstimate,
        book: OrderBook,
        size: float,
        fee_rate: float,
        stressed_slippage: float,
        execution_risk_penalty: float,
        fee_exponent: int = 1,
    ) -> EdgeEstimate:
        quote = quote_taker(book, size)
        p = probability.p_calibrated if side is Side.UP else 1.0 - probability.p_calibrated
        pm = probability.market_probability if side is Side.UP else 1.0 - probability.market_probability
        p_cons = probability.conservative(side)
        fee = polymarket_fee_per_share(quote.average_price, fee_rate, fee_exponent)
        slippage = quote.slippage_per_share
        executable = p - quote.average_price
        net = executable - fee - slippage
        uncertainty_penalty = max(0.0, p - p_cons)
        risk_adjusted = net - uncertainty_penalty - execution_risk_penalty
        stressed_cost = quote.average_price + fee + max(slippage, stressed_slippage)
        conservative = p_cons - stressed_cost - execution_risk_penalty
        return EdgeEstimate(
            side=side,
            raw_edge=p - pm,
            executable_edge=executable,
            net_edge=net,
            risk_adjusted_edge=risk_adjusted,
            conservative_net_edge=conservative,
            executable_price=quote.average_price,
            fees=fee,
            slippage=slippage,
            execution_risk_penalty=execution_risk_penalty,
        )
