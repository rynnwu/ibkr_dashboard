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


def signed_dollar_delta(position: dict, contract_size: float = 100) -> float:
    """Signed market exposure of one position in *dollars of underlying delta*.

    Unlike the donut ``exposure`` (which is ``notional × |delta|``, always
    positive), this carries direction — long market exposure is positive, short
    is negative — so net long/short cancels correctly when summed. This is the
    correct base for a market hedge.

      - option: ``quantity × 100 × delta × underlying_price`` — both ``quantity``
        (long/short) and ``delta`` (right) carry sign, so a short put is +, a
        long put is −.
      - stock / leveraged ETF: ``sign(quantity) × notional`` (the ``notional``
        already folds in the ETF multiplier; ``delta`` already encodes the sign).

    Pure."""
    if position["type"] in ("COPT", "POPT"):
        delta = position.get("delta")
        underlying_price = position.get("underlying_price")
        if delta is None or underlying_price is None:
            return 0.0
        return position["quantity"] * contract_size * delta * underlying_price
    sign = 1.0 if position["quantity"] >= 0 else -1.0
    return sign * position["notional"]


def beta_weighted_exposure(positions: list[dict], betas: dict[str, float], default_beta: float = 1.0) -> dict:
    """Net signed dollar-delta beta-weighted to the S&P 500, plus a per-underlying
    breakdown. ``betas`` maps an underlying symbol to its beta vs SPX; missing
    symbols use ``default_beta``. Pure.

    Returns ``{netBetaWeightedExposure, breakdown: [{underlying, signedDelta,
    beta, betaWeighted}], defaulted: [symbols that used default_beta]}``."""
    by_underlying: dict[str, float] = {}
    for pos in positions:
        by_underlying[pos["underlying"]] = by_underlying.get(pos["underlying"], 0.0) + signed_dollar_delta(pos)

    breakdown = []
    defaulted: list[str] = []
    net = 0.0
    for underlying, signed in by_underlying.items():
        if underlying in betas:
            beta = betas[underlying]
        else:
            beta = default_beta
            defaulted.append(underlying)
        weighted = signed * beta
        net += weighted
        breakdown.append({"underlying": underlying, "signedDelta": signed, "beta": beta, "betaWeighted": weighted})

    return {"netBetaWeightedExposure": net, "breakdown": breakdown, "defaulted": defaulted}


def etf_hedge_candidates(
    positions: list[dict],
    etf_specs: list[dict],
    nlv: float,
    concentration_threshold: float = 0.6,
    levels: dict[str, float] | None = None,
) -> dict:
    """Compare candidate hedge ETFs (e.g. SPY / QQQ / SMH) against the portfolio's
    net signed dollar-delta, to (1) suggest which instrument best fits the book and
    (2) express the current exposure as a multiple of NLV in each ETF's own terms.
    Pure — no I/O; a config-driven order-of-magnitude guide like the SPX hedge.

    Each ``etf_specs`` entry is ``{symbol, label, broad: bool, defaultBeta: float,
    betas: {underlying -> beta vs this ETF}}``. A holding is *covered* by an ETF
    when it has an explicit ``betas`` entry (i.e. it sits in that ETF's universe);
    otherwise ``defaultBeta`` applies (≈1.0 for the broad market, ≈0 for a sector
    ETF whose universe the name is outside of).

    For each ETF E, over per-underlying signed dollar-delta ``s_u``
    (:func:`signed_dollar_delta`, long +, short −):

      - ``netExposure`` = Σ_u s_u · beta(u, E)        — exposure beta-weighted to E
      - ``leverage``    = netExposure / NLV           — "times of NLV right now"
      - ``coverage``    = Σ_{u in E} |s_u| / Σ_u |s_u| — the share of the book's
        gross directional exposure that lives in E's universe

    ``levels`` (optional) maps an ETF symbol to its current spot price; surfaced
    per candidate as ``level`` (None when absent) so the hedge what-if can model-
    price against the chosen ETF.

    Recommendation: the most-covering *sector* ETF whose coverage ≥
    ``concentration_threshold`` (a tighter, cheaper hedge for a concentrated book),
    otherwise the broad-market ETF. Returns ``{candidates: [...] sorted by coverage
    desc, recommended: symbol|None, recommendedReason}``."""
    levels = levels or {}
    by_underlying: dict[str, float] = {}
    for pos in positions:
        by_underlying[pos["underlying"]] = by_underlying.get(pos["underlying"], 0.0) + signed_dollar_delta(pos)
    gross = sum(abs(v) for v in by_underlying.values())

    candidates = []
    for spec in etf_specs:
        betas = spec.get("betas", {})
        broad = bool(spec.get("broad"))
        default_beta = spec.get("defaultBeta", 1.0 if broad else 0.0)
        net = 0.0
        covered_gross = 0.0
        covered_syms: list[str] = []
        for underlying, signed in by_underlying.items():
            # A broad-market ETF represents the whole book (every name carries
            # market beta), so it "covers" all underlyings; a sector ETF only
            # covers names that have an explicit beta entry (in its universe).
            if underlying in betas or broad:
                covered_gross += abs(signed)
                covered_syms.append(underlying)
            net += signed * betas.get(underlying, default_beta)
        candidates.append({
            "symbol": spec["symbol"],
            "label": spec.get("label", spec["symbol"]),
            "broad": broad,
            "netExposure": net,
            "leverage": net / nlv if nlv else 0.0,
            "coverage": covered_gross / gross if gross else 0.0,
            "coveredSymbols": sorted(covered_syms),
            "level": levels.get(spec["symbol"]),
        })

    # Recommend the most-concentrated good sector fit, else the broad market.
    sectors = [c for c in candidates if not c["broad"]]
    broad = next((c for c in candidates if c["broad"]), None)
    best_sector = max(sectors, key=lambda c: c["coverage"], default=None)
    if best_sector and best_sector["coverage"] >= concentration_threshold:
        recommended, reason = best_sector["symbol"], "concentrated"
    elif broad:
        recommended, reason = broad["symbol"], "broad"
    elif best_sector:
        recommended, reason = best_sector["symbol"], "fallback"
    else:
        recommended, reason = None, "none"

    candidates.sort(key=lambda c: c["coverage"], reverse=True)
    return {
        "candidates": candidates,
        "recommended": recommended,
        "recommendedReason": reason,
        "concentrationThreshold": concentration_threshold,
    }


def put_strike_for_delta(
    S: float, target_delta: float, T: float, r: float, q: float, sigma: float
) -> float:
    """Strike whose Black-Scholes *put* delta has magnitude ``target_delta`` — the
    closed-form inverse of ``delta = −e^{-qT}·N(−d1)``:

        N(−d1) = target_delta · e^{qT}   ⇒   d1 = −Φ⁻¹(target_delta · e^{qT})
        ln(K) = ln(S) + (r − q + σ²/2)·T − d1·σ·√T

    ``target_delta`` is the magnitude (a positive number in (0,1)). Higher
    magnitude ⇒ deeper ITM ⇒ higher strike. Used to pick a hedge-put strike near
    a target delta before snapping to a listed strike. Pure."""
    td = min(max(abs(target_delta), 1e-6), 1.0 - 1e-6)
    n_neg_d1 = min(max(td * math.exp(q * T), 1e-6), 1.0 - 1e-6)
    d1 = -norm.ppf(n_neg_d1)
    ln_k = math.log(S) + (r - q + 0.5 * sigma ** 2) * T - d1 * sigma * math.sqrt(T)
    return math.exp(ln_k)


def spx_put_hedge(
    *,
    net_exposure: float,
    spx_level: float,
    put_delta: float,
    put_price: float,
    hedge_fraction: float,
    nlv: float,
    target_leverage: float | None = None,
    contract_size: float = 100,
) -> dict:
    """Size an SPX-put hedge against the portfolio's net beta-weighted dollar
    exposure. Pure — an order-of-magnitude guide, not an order ticket.

    Two sizing modes:

    - **target-leverage** (``target_leverage`` set, the default driver): the
      *minimum* whole contracts that bring post-hedge leverage at/under
      ``target_leverage`` (e.g. 1.0× NLV). Solving ``residual ≤ target·nlv``:

          residual  = net_exposure − contracts·100·spx·|put_delta| ≤ target·nlv
          contracts = ceil( (net_exposure − target·nlv) / (spx·100·|put_delta|) )

      (0 contracts when exposure is already at/under the target.)
    - **fraction** (``target_leverage is None``): hedge a fraction of exposure:

          raw       = hedge_fraction · net_exposure / (spx_level · 100 · |put_delta|)
          contracts = round(raw)                       # options trade whole

    In both modes the reported figures come from the *rounded* contract count:

        offset    = contracts · 100 · spx_level · |put_delta|   # actual Δ-$ removed
        residual  = net_exposure − offset            # real remaining Δ exposure
        cost      = |contracts| · 100 · put_price

    Contracts are **whole** — you can't buy a fractional option — so
    ``netExposureAfter`` is the *actual* residual delta exposure from the rounded
    position (it won't be exactly 0, and can go slightly negative if rounding
    over-hedges), rather than a tautological ``net·(1−fraction)``. ``put_delta``
    is taken by magnitude (a hedge put has negative delta; we offset positive
    long exposure). Note these are delta-equivalent figures at the current spot —
    a long-put hedge protects the *downside* while retaining upside, it does not
    symmetrically null exposure. Before/after leverage are exposure / NLV."""
    pd = abs(put_delta)
    denom = spx_level * contract_size * pd
    if target_leverage is not None and nlv > 0 and denom:
        required_offset = net_exposure - target_leverage * nlv
        raw_contracts = required_offset / denom if required_offset > 0 else 0.0
        contracts = float(math.ceil(raw_contracts)) if raw_contracts > 0 else 0.0
    else:
        raw_contracts = (hedge_fraction * net_exposure) / denom if denom else 0.0
        contracts = float(round(raw_contracts))
    offset = contracts * contract_size * spx_level * pd
    residual = net_exposure - offset
    cost = abs(contracts) * contract_size * put_price
    return {
        "contracts": contracts,
        "rawContracts": raw_contracts,
        "cost": cost,
        "netExposureBefore": net_exposure,
        "netExposureAfter": residual,
        "deltaOffset": offset,
        "leverageBefore": net_exposure / nlv if nlv else 0.0,
        "leverageAfter": residual / nlv if nlv else 0.0,
        "hedgeFraction": hedge_fraction,
        "targetLeverage": target_leverage,
        "putDelta": put_delta,
        "putPrice": put_price,
        "spxLevel": spx_level,
    }


def _synthetic_strikes(spx_level: float, step: float = 5.0) -> list[float]:
    """A coarse strike grid around spot, used to snap model-fallback strikes when
    no live option chain is available (≈ 0.5×–1.3× spot on a 5-pt grid)."""
    lo = math.floor(spx_level * 0.5 / step) * step
    hi = math.ceil(spx_level * 1.3 / step) * step
    n = int(round((hi - lo) / step)) + 1
    return [lo + i * step for i in range(n)]


def _bs_leg(S, K, T, r, q, sigma, right, contracts, contract_size=100) -> dict:
    """One Black-Scholes option leg. ``contracts`` is signed (long +, short −).
    Reports the per-share ``price``/``delta`` plus the leg's whole-position
    ``cost`` (+debit / −credit) and signed ``dollarDelta`` (contracts·100·S·δ)."""
    price = bs_price(S, K, T, r, q, sigma, right)
    delta = bs_greeks(S, K, T, r, q, sigma, right)["delta"]
    return {
        "right": right,
        "strike": K,
        "contracts": contracts,
        "price": price,
        "delta": delta,
        "cost": contracts * contract_size * price,
        "dollarDelta": contracts * contract_size * S * delta,
    }


def spx_hedge_proposals(
    *,
    net_exposure: float,
    nlv: float,
    spx_level: float,
    dte: int,
    r: float,
    q: float,
    sigma: float,
    target_put_delta: float,
    floor_put_delta: float,
    hedge_fraction: float,
    target_leverage: float | None,
    strikes: list[float] | None = None,
    contract_size: float = 100,
) -> dict:
    """Build three SPX-put hedge proposals that share one contract count ``N`` —
    the long protective put sized (via :func:`spx_put_hedge`) to bring post-hedge
    leverage at/under ``target_leverage``:

      1. **long_put** — buy N puts at ``target_put_delta``. Full downside below
         the strike; most expensive.
      2. **vertical** — bear put spread: +N puts (``target_put_delta``) / −N puts
         (``floor_put_delta``, strictly lower strike). Cheaper net debit;
         protection is capped between the two strikes.
      3. **seagull** — +N put / −N put (as the vertical) / −N call, the call
         strike chosen so its credit ≈ the put-spread debit (**≈ zero-cost**);
         caps upside at the call strike.

    All legs are Black-Scholes priced off one flat IV (``sigma``) so the per-leg
    premiums — and therefore the net cost across legs — are coherent. The
    residual exposure of each proposal is the *real* one from the rounded N:
    ``net_exposure + Σ leg dollar-delta``. Pure — an order-of-magnitude guide."""
    T = max(dte, 1) / 365.0
    grid = sorted(strikes) if strikes else _synthetic_strikes(spx_level)
    snap = lambda k: min(grid, key=lambda s: abs(s - k))

    # Long protective put — drives the shared contract count N.
    long_k = snap(put_strike_for_delta(spx_level, target_put_delta, T, r, q, sigma))
    long_leg = _bs_leg(spx_level, long_k, T, r, q, sigma, "P", 0, contract_size)
    base = spx_put_hedge(
        net_exposure=net_exposure, spx_level=spx_level, put_delta=long_leg["delta"],
        put_price=long_leg["price"], hedge_fraction=hedge_fraction, nlv=nlv,
        target_leverage=target_leverage, contract_size=contract_size,
    )
    n = base["contracts"]  # whole, >= 0

    # Floor (short) put, snapped strictly below the long strike.
    floor_raw = snap(put_strike_for_delta(spx_level, floor_put_delta, T, r, q, sigma))
    below = [s for s in grid if s < long_k]
    floor_k = floor_raw if floor_raw < long_k else (max(below) if below else long_k)

    long_put = _bs_leg(spx_level, long_k, T, r, q, sigma, "P", n, contract_size)
    short_put = _bs_leg(spx_level, floor_k, T, r, q, sigma, "P", -n, contract_size)

    # Seagull short call: the strike whose credit ≈ the put-spread debit (per share).
    target_credit = max(long_put["price"] - short_put["price"], 0.0)
    calls = [s for s in grid if s > spx_level] or grid
    call_k = min(calls, key=lambda s: abs(bs_price(spx_level, s, T, r, q, sigma, "C") - target_credit))
    short_call = _bs_leg(spx_level, call_k, T, r, q, sigma, "C", -n, contract_size)

    lev_before = net_exposure / nlv if nlv else 0.0

    def proposal(kind: str, legs: list[dict], floor: float | None, cap: float | None) -> dict:
        cost = sum(l["cost"] for l in legs)
        offset = sum(l["dollarDelta"] for l in legs)
        residual = net_exposure + offset
        return {
            "kind": kind,
            "contracts": n,
            "legs": legs,
            "cost": cost,
            "deltaOffset": offset,
            "netExposureBefore": net_exposure,
            "netExposureAfter": residual,
            "leverageBefore": lev_before,
            "leverageAfter": residual / nlv if nlv else 0.0,
            "protectionFloor": floor,
            "upsideCap": cap,
            "maxProtection": n * contract_size * (long_k - floor_k) if floor is not None else None,
        }

    proposals = [
        proposal("long_put", [long_put], None, None),
        proposal("vertical", [long_put, short_put], floor_k, None),
        proposal("seagull", [long_put, short_put, short_call], floor_k, call_k),
    ]
    return {
        "contracts": n,
        "targetLeverage": target_leverage,
        "netExposureBefore": net_exposure,
        "leverageBefore": lev_before,
        "spxLevel": spx_level,
        "dte": dte,
        "iv": sigma * 100,
        "longPutStrike": long_k,
        "floorPutStrike": floor_k,
        "proposals": proposals,
    }


def greeks_card(option_positions: list[dict]) -> dict[str, float]:
    return {
        "net_delta": sum(p["delta_shares"] for p in option_positions),
        "net_theta": sum(p["theta"] for p in option_positions),
        "net_vega": sum(p["vega"] for p in option_positions),
    }
