"""Pure functions for position-level and portfolio-level risk math.

No I/O here — everything takes plain numbers/dicts so it can be unit
tested without a live IB Gateway connection.
"""

import math
from scipy.stats import norm


def stock_notional(quantity: float, price: float) -> float:
    return abs(quantity) * price


def leveraged_etf_notional(quantity: float, price: float, multiplier: float) -> float:
    return abs(quantity) * price * multiplier


def option_notional(contracts: float, underlying_price: float, contract_size: float = 100) -> float:
    return abs(contracts) * contract_size * underlying_price


def option_exposure(notional: float, delta: float) -> float:
    return notional * abs(delta)


def discount(notional: float, exposure: float) -> float:
    if notional == 0:
        return 0.0
    return 1.0 - exposure / notional


def _d1_d2(S: float, K: float, T: float, r: float, q: float, sigma: float) -> tuple[float, float]:
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return d1, d2


def bs_price(S: float, K: float, T: float, r: float, q: float, sigma: float, right: str) -> float:
    d1, d2 = _d1_d2(S, K, T, r, q, sigma)
    if right == "C":
        return S * math.exp(-q * T) * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * math.exp(-q * T) * norm.cdf(-d1)


def implied_vol(
    mark_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    q: float,
    right: str,
    lo: float = 1e-4,
    hi: float = 5.0,
    tol: float = 1e-6,
    max_iter: int = 100,
) -> float:
    """Compute implied volatility using bisection method.

    Parameters:
    lo: volatility search bounds (lower)
    hi: volatility search bounds (upper)
    tol: price-difference convergence threshold
    max_iter: bisection iteration cap
    """
    mid = (lo + hi) / 2
    for _ in range(max_iter):
        price = bs_price(S, K, T, r, q, mid, right)
        if abs(price - mark_price) < tol:
            break
        if price > mark_price:
            hi = mid
        else:
            lo = mid
        mid = (lo + hi) / 2
    return mid


def bs_greeks(S: float, K: float, T: float, r: float, q: float, sigma: float, right: str) -> dict[str, float]:
    d1, d2 = _d1_d2(S, K, T, r, q, sigma)
    pdf_d1 = norm.pdf(d1)
    if right == "C":
        delta = math.exp(-q * T) * norm.cdf(d1)
        theta_annual = (
            -S * math.exp(-q * T) * pdf_d1 * sigma / (2 * math.sqrt(T))
            - r * K * math.exp(-r * T) * norm.cdf(d2)
            + q * S * math.exp(-q * T) * norm.cdf(d1)
        )
    else:
        delta = -math.exp(-q * T) * norm.cdf(-d1)
        theta_annual = (
            -S * math.exp(-q * T) * pdf_d1 * sigma / (2 * math.sqrt(T))
            + r * K * math.exp(-r * T) * norm.cdf(-d2)
            - q * S * math.exp(-q * T) * norm.cdf(-d1)
        )
    vega_full = S * math.exp(-q * T) * pdf_d1 * math.sqrt(T)
    return {
        "delta": delta,
        "theta": theta_annual / 365.0,  # per calendar day
        "vega": vega_full / 100.0,      # per 1 vol point (1%)
    }


def aggregate_by_underlying(positions: list[dict]) -> list[dict]:
    totals: dict[str, dict] = {}
    for pos in positions:
        row = totals.setdefault(pos["underlying"], {"underlying": pos["underlying"], "notional": 0.0, "exposure": 0.0})
        row["notional"] += pos["notional"]
        row["exposure"] += pos["exposure"]
    return list(totals.values())


def portfolio_leverage(total_notional: float, total_exposure: float, nlv: float) -> dict[str, float]:
    return {
        "notional_leverage": total_notional / nlv,
        "exposure_leverage": total_exposure / nlv,
    }


def greeks_card(option_positions: list[dict]) -> dict[str, float]:
    return {
        "net_delta": sum(p["delta_shares"] for p in option_positions),
        "net_theta": sum(p["theta"] for p in option_positions),
        "net_vega": sum(p["vega"] for p in option_positions),
    }
