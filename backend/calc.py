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
    if nlv == 0:
        return {"notional_leverage": 0.0, "exposure_leverage": 0.0}
    return {
        "notional_leverage": total_notional / nlv,
        "exposure_leverage": total_exposure / nlv,
    }


def cushion_level(cushion: float, warning_cushion: float = 0.20, danger_cushion: float = 0.10) -> str:
    """Maps a cushion ratio (ExcessLiquidity / NLV) to the safe/warning/danger
    band used by both the margin card and the roll what-if. Pure."""
    if cushion < danger_cushion:
        return "danger"
    if cushion < warning_cushion:
        return "warning"
    return "safe"


def margin_summary(
    nlv: float,
    maint_margin: float,
    excess_liquidity: float,
    lookahead_maint: float | None = None,
    lookahead_excess: float | None = None,
    *,
    cash: float | None = None,
    available_funds: float | None = None,
    warning_cushion: float = 0.20,
    danger_cushion: float = 0.10,
) -> dict:
    """Margin-buffer snapshot for the dashboard card.

    ``excess_liquidity`` is the dollar buffer to forced liquidation — IBKR
    starts auto-liquidating when it hits 0 (no traditional margin-call grace
    period). ``cushion`` = ExcessLiquidity / NLV is the same ratio IBKR
    reports; it drives the safe/warning/danger level via the configured
    thresholds. ``buffer_ratio`` = ExcessLiquidity / MaintMarginReq expresses
    the buffer relative to the *current* requirement (None when there's no
    maintenance requirement, e.g. a cash-only account). The look-ahead pair is
    IBKR's projection after the next known margin change (SPAN updates, options
    nearing expiry) — especially relevant for short options — and is omitted
    from the payload when the gateway doesn't supply it.

    ``cash`` and ``available_funds`` are a *separate* axis from the liquidation
    ``level``: they answer "can I still open / roll positions?", not "am I about
    to be force-liquidated?". They deliberately do NOT feed ``level`` (mixing the
    two would dilute the liquidation signal). ``available_funds`` (= ELV −
    InitMargin) is always ≤ excess_liquidity, so it hits zero *first* — it's the
    early warning that a roll/open is no longer possible; ``can_open_new`` flags
    that. Both are omitted from the payload when not supplied.

    Pure: takes plain numbers so it's unit-testable without a live gateway."""
    cushion = excess_liquidity / nlv if nlv else 0.0
    buffer_ratio = excess_liquidity / maint_margin if maint_margin else None
    level = cushion_level(cushion, warning_cushion, danger_cushion)
    summary = {
        "maintMargin": maint_margin,
        "excessLiquidity": excess_liquidity,
        "cushion": cushion,
        "bufferRatio": buffer_ratio,
        "level": level,
    }
    if lookahead_maint is not None:
        summary["lookAheadMaintMargin"] = lookahead_maint
    if lookahead_excess is not None:
        summary["lookAheadExcessLiquidity"] = lookahead_excess
    if cash is not None:
        summary["cash"] = cash
    if available_funds is not None:
        summary["availableFunds"] = available_funds
        summary["canOpenNew"] = available_funds > 0
    return summary


def regt_short_put_maint(
    contracts: float, S: float, K: float, put_mark: float, contract_size: float = 100
) -> float:
    """Reg T maintenance-margin approximation for a short (naked) put:

        per_share = max(0.20*S - max(S-K, 0), 0.10*K) + put_mark
        MM        = |contracts| * 100 * per_share

    This is the fallback estimate for the margin a short put currently ties up —
    the most fragile input to ``roll_what_if``. Callers should let the user
    override it with the actual TWS What-If figure, especially under Portfolio
    Margin where IBKR uses a TIMS scenario model rather than this linear rule.
    Pure."""
    per_share = max(0.20 * S - max(S - K, 0.0), 0.10 * K) + put_mark
    return abs(contracts) * contract_size * per_share


def call_strike_for_delta(
    S: float, target_delta: float, T: float, r: float, q: float, sigma: float
) -> float:
    """Strike whose Black-Scholes *call* delta equals ``target_delta`` — the
    closed-form inverse of ``delta = e^{-qT} · N(d1)``:

        N(d1) = target_delta · e^{qT}
        ln(K) = ln(S) + (r − q + σ²/2)·T − d1·σ·√T

    ``target_delta`` is clamped into (0, 1). Higher delta ⇒ deeper ITM ⇒ lower
    strike. Used to pick a replacement long-call strike that replicates (or
    exceeds) the short put's delta. Pure."""
    td = min(max(target_delta, 1e-6), 1.0 - 1e-6)
    n_d1 = min(max(td * math.exp(q * T), 1e-6), 1.0 - 1e-6)
    d1 = norm.ppf(n_d1)
    ln_k = math.log(S) + (r - q + 0.5 * sigma ** 2) * T - d1 * sigma * math.sqrt(T)
    return math.exp(ln_k)


def roll_what_if(
    *,
    excess_liquidity: float,
    nlv: float,
    mm_sp: float,
    close_sp_debit: float,
    open_call_premium: float = 0.0,
    open_etf_value: float = 0.0,
    etf_maint_rate: float = 0.50,
    cash: float | None = None,
    available_funds: float | None = None,
    loan_value_other: float = 0.0,
    warning_cushion: float = 0.20,
    danger_cushion: float = 0.10,
) -> dict:
    """Estimate the effect of rolling a short put into a long call and/or a
    leveraged ETF, on two independent axes (mirroring ``margin_summary``). Pure;
    see TODO.md for the derivation and the (important) limitations — this is an
    order-of-magnitude guide, not a substitute for TWS What-If under PM.

    (a) Liquidation buffer. Closing the short put releases its maintenance
        margin (+``mm_sp`` to Excess Liquidity, NLV-neutral at the mark); buying
        a long call spends premium with no loan value (−premium); buying a
        leveraged ETF with cash ties up its maintenance margin
        (−``etf_maint_rate`` × value). ``cushion``/``level`` reuse the
        ``cushion_level`` thresholds.

    (b) Funding feasibility. A long call must be paid in full (no margin loan)
        and buying back the put is a cash debit, so the cash outflow is
        ``close_sp_debit + open_call_premium + open_etf_value``, funded by
        ``cash`` plus the loan value of other pledgeable securities
        (``loan_value_other``). ``surplus >= 0`` means the roll is executable.

    ``mm_sp`` is the *most fragile* input (the put's current maintenance
    margin) — pass the TWS What-If value when available; ``regt_short_put_maint``
    is only an approximation."""
    delta_close_sp = mm_sp
    delta_open_call = -open_call_premium
    delta_buy_etf = -(etf_maint_rate * open_etf_value)
    excess_after = excess_liquidity + delta_close_sp + delta_open_call + delta_buy_etf

    cushion_before = excess_liquidity / nlv if nlv else 0.0
    cushion_after = excess_after / nlv if nlv else 0.0

    result = {
        "excessLiquidityBefore": excess_liquidity,
        "excessLiquidityAfter": excess_after,
        "cushionBefore": cushion_before,
        "cushionAfter": cushion_after,
        "levelBefore": cushion_level(cushion_before, warning_cushion, danger_cushion),
        "levelAfter": cushion_level(cushion_after, warning_cushion, danger_cushion),
        "deltaExcessLiquidity": {
            "closeShortPut": delta_close_sp,
            "openLongCall": delta_open_call,
            "buyLeveragedEtf": delta_buy_etf,
        },
        "mmSp": mm_sp,
        "closeSpDebit": close_sp_debit,
        "openCallPremium": open_call_premium,
        "openEtfValue": open_etf_value,
    }

    if cash is not None:
        outflow = close_sp_debit + open_call_premium + open_etf_value
        surplus = cash + loan_value_other - outflow
        result["fundingOutflow"] = outflow
        result["surplus"] = surplus
        result["canExecute"] = surplus >= 0
        result["shortfall"] = max(-surplus, 0.0)
    if available_funds is not None:
        # Aggregate cross-check (TODO.md §2): releasing the put frees ~mm_sp of
        # initial margin back into AvailableFunds.
        result["availableFundsAfter"] = available_funds + mm_sp

    return result


def exposure_match_sizing(
    contracts: float,
    underlying_price: float,
    delta_sp: float,
    *,
    call_delta: float | None = None,
    etf_leverage: float = 2.0,
    etf_price: float | None = None,
    contract_size: float = 100,
) -> dict:
    """Size a replacement leg to match the short put's current delta exposure:

        E_target = |contracts| * 100 * S * |delta_sp|

    A long call replicating it needs ``Q = E_target / (100*S*call_delta)``
    contracts; a leveraged ETF needs ``V = E_target / leverage`` of market value
    (``shares = V / price``). Pure."""
    exposure_target = abs(contracts) * contract_size * underlying_price * abs(delta_sp)
    result = {"exposureTarget": exposure_target}
    if call_delta:
        result["callContracts"] = exposure_target / (contract_size * underlying_price * call_delta)
    etf_value = exposure_target / etf_leverage if etf_leverage else 0.0
    result["etfValue"] = etf_value
    if etf_price:
        result["etfShares"] = etf_value / etf_price
    return result


def greeks_card(option_positions: list[dict]) -> dict[str, float]:
    return {
        "net_delta": sum(p["delta_shares"] for p in option_positions),
        "net_theta": sum(p["theta"] for p in option_positions),
        "net_vega": sum(p["vega"] for p in option_positions),
    }
