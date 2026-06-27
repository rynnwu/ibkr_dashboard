import logging
import math
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from ib_insync import IB, Option, Position
from pydantic import BaseModel

from backend import cache, calc, config, ibkr_client, icons, spx_cache

app = FastAPI()
icons.CACHE_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/icons", StaticFiles(directory=str(icons.CACHE_DIR)), name="icons")
CONFIG_PATH = Path(__file__).parent / "config.json"
logger = logging.getLogger(__name__)


def build_portfolio_response(positions: list[dict], nlv: float, icon_lookup: dict, warnings: list[str], margin: dict | None = None, betas: dict | None = None, spx_level: float = 0.0, hedge_warning_leverage: float = 1.5) -> dict:
    """Assembles the full portfolio API payload (totals, leverage, greeks, per-underlying rows) from position records.

    ``margin`` is the optional calc.margin_summary() block; None when account
    margin values were unavailable (it then renders nothing on the frontend).

    ``betas`` maps an underlying to its beta vs SPX (missing → 1.0); together
    with ``spx_level`` it powers the SPX-hedge banner/panel (DESIGN §12) — the
    payload carries the net beta-weighted dollar exposure, the beta-weighted
    leverage, and per-underlying betas."""
    underlying_rows = calc.aggregate_by_underlying(positions)
    total_notional = sum(row["notional"] for row in underlying_rows)
    total_exposure = sum(row["exposure"] for row in underlying_rows)
    leverage = calc.portfolio_leverage(total_notional, total_exposure, nlv)

    bw = calc.beta_weighted_exposure(positions, betas or {})
    beta_by_underlying = {b["underlying"]: b["beta"] for b in bw["breakdown"]}

    option_positions = [
        {
            "delta_shares": p["quantity"] * 100 * p["delta"] if p.get("delta") is not None else 0.0,
            "theta": p["quantity"] * 100 * p.get("theta", 0.0),
            "vega": p["quantity"] * 100 * p.get("vega", 0.0),
        }
        for p in positions
        if p["type"] in ("COPT", "POPT")
    ]
    greeks = calc.greeks_card(option_positions) if option_positions else {"net_delta": 0.0, "net_theta": 0.0, "net_vega": 0.0}

    underlyings = []
    for row in underlying_rows:
        icon_path, color = icon_lookup.get(row["underlying"], (None, "#888888"))
        icon_url = f"/icons/{row['underlying']}.png" if icon_path is not None else None
        underlyings.append({
            "symbol": row["underlying"],
            "notional": row["notional"],
            "exposure": row["exposure"],
            "color": color,
            "iconUrl": icon_url,
            "beta": beta_by_underlying.get(row["underlying"]),
        })

    return {
        "nlv": nlv,
        "totalNotional": total_notional,
        "totalExposure": total_exposure,
        "notionalLeverage": leverage["notional_leverage"],
        "exposureLeverage": leverage["exposure_leverage"],
        "netDelta": greeks["net_delta"],
        "netTheta": greeks["net_theta"],
        "netVega": greeks["net_vega"],
        "netBetaWeightedExposure": bw["netBetaWeightedExposure"],
        "betaWeightedLeverage": bw["netBetaWeightedExposure"] / nlv if nlv else 0.0,
        "spxLevel": spx_level,
        "spxHedgeWarningLeverage": hedge_warning_leverage,
        "underlyings": underlyings,
        "positions": positions,
        "margin": margin,
        "warnings": warnings,
        "stale": False,
        "cachedAt": cache.now_iso(),
    }


@app.get("/api/portfolio")
def get_portfolio() -> dict:
    """Returns the full portfolio payload.

    Happy path: connect to IB Gateway, fetch live, cache the result, return it.
    If the gateway is unreachable or the fetch fails, fall back to the last
    cached snapshot (flagged `stale`) so the dashboard still shows something
    useful; only when there is *no* cache do we surface the 503."""
    cfg = config.load_config(CONFIG_PATH)
    try:
        payload = _fetch_live_portfolio(cfg)
    except Exception as exc:
        logger.warning("Live portfolio fetch failed, attempting cache fallback: %s", exc)
        cached = cache.load_portfolio()
        if cached is not None:
            return cached
        raise HTTPException(status_code=503, detail=f"無法連線到 IB Gateway，且沒有可用的快照資料: {exc}")

    cache.save_portfolio(payload)
    return payload


class RollWhatIfRequest(BaseModel):
    """Inputs for the roll what-if estimate. Current account figures
    (excessLiquidity/nlv/cash/availableFunds) come from the client, which
    already holds them from the latest /api/portfolio margin block — so this
    endpoint does *no* IBKR I/O and just runs the pure calc."""

    excessLiquidity: float
    nlv: float
    cash: float | None = None
    availableFunds: float | None = None
    loanValueOther: float = 0.0
    # Short put leg to close (used to derive D and the Reg T MM_SP fallback).
    spContracts: float
    spUnderlyingPrice: float
    spStrike: float
    spPutMark: float
    # When set, used verbatim instead of the Reg T approximation (TWS What-If).
    mmSpOverride: float | None = None
    # Replacement legs — either/both. Premium = call_mark * 100 * Q (client-side).
    openCallPremium: float = 0.0
    openEtfValue: float = 0.0
    etfMaintRate: float = 0.50


@app.post("/api/roll-what-if")
def compute_roll_what_if(req: RollWhatIfRequest) -> dict:
    """Pure roll what-if estimate (no gateway connection). See calc.roll_what_if
    and TODO.md for the math + limitations."""
    cfg = config.load_config(CONFIG_PATH)
    mm_sp = (
        req.mmSpOverride
        if req.mmSpOverride is not None
        else calc.regt_short_put_maint(req.spContracts, req.spUnderlyingPrice, req.spStrike, req.spPutMark)
    )
    close_sp_debit = abs(req.spContracts) * 100 * req.spPutMark
    result = calc.roll_what_if(
        excess_liquidity=req.excessLiquidity,
        nlv=req.nlv,
        mm_sp=mm_sp,
        close_sp_debit=close_sp_debit,
        open_call_premium=req.openCallPremium,
        open_etf_value=req.openEtfValue,
        etf_maint_rate=req.etfMaintRate,
        cash=req.cash,
        available_funds=req.availableFunds,
        loan_value_other=req.loanValueOther,
        warning_cushion=cfg.margin_warning_cushion,
        danger_cushion=cfg.margin_danger_cushion,
    )
    result["mmSpAuto"] = req.mmSpOverride is None
    return result


class PriceOptionRequest(BaseModel):
    """Inputs for a Black-Scholes model price of a single option leg. Used by the
    roll what-if to fill model defaults (the put's mark when the gateway gave no
    quote, and a suggested long-call premium) — see calc.bs_price/bs_greeks."""

    underlyingPrice: float
    strike: float
    daysToExpiry: int
    right: str  # "C" or "P"
    iv: float  # implied volatility in percent (e.g. 45.0 for 45%)
    dividendYield: float = 0.0


@app.post("/api/price-option")
def price_option(req: PriceOptionRequest) -> dict:
    """Black-Scholes model price + Greeks for one option leg (no IBKR I/O).
    The risk-free rate comes from config; IV is supplied by the caller (the
    roll what-if defaults it to the short put's own IV)."""
    cfg = config.load_config(CONFIG_PATH)
    T = max(req.daysToExpiry, 1) / 365.0
    sigma = req.iv / 100.0
    right = "C" if req.right == "C" else "P"
    mark = calc.bs_price(req.underlyingPrice, req.strike, T, cfg.risk_free_rate, req.dividendYield, sigma, right)
    greeks = calc.bs_greeks(req.underlyingPrice, req.strike, T, cfg.risk_free_rate, req.dividendYield, sigma, right)
    return {"mark": mark, "delta": greeks["delta"], "theta": greeks["theta"], "vega": greeks["vega"], "iv": req.iv}


class SuggestCallRequest(BaseModel):
    """Inputs for suggesting a replacement long-call strike. Picks the strike
    whose model call delta equals max(|short put delta|, minDelta) at the given
    DTE/IV, then prices it. No IBKR I/O."""

    underlyingPrice: float
    shortPutDelta: float  # the SP's delta (signed or magnitude; abs is used)
    iv: float  # implied volatility in percent
    daysToExpiry: int = 180
    minDelta: float = 0.85
    dividendYield: float = 0.0


@app.post("/api/suggest-call")
def suggest_call(req: SuggestCallRequest) -> dict:
    """Suggest a long-call strike replicating (or exceeding) the short put's
    delta — target = max(|SP delta|, minDelta), capped just under 1 — and price
    it via Black-Scholes. Strike is rounded to a whole dollar and re-priced so
    the returned mark/delta match the rounded strike."""
    cfg = config.load_config(CONFIG_PATH)
    T = max(req.daysToExpiry, 1) / 365.0
    sigma = req.iv / 100.0
    target = min(max(abs(req.shortPutDelta), req.minDelta), 0.99)
    raw_strike = calc.call_strike_for_delta(req.underlyingPrice, target, T, cfg.risk_free_rate, req.dividendYield, sigma)
    strike = max(round(raw_strike), 1.0)
    mark = calc.bs_price(req.underlyingPrice, strike, T, cfg.risk_free_rate, req.dividendYield, sigma, "C")
    greeks = calc.bs_greeks(req.underlyingPrice, strike, T, cfg.risk_free_rate, req.dividendYield, sigma, "C")
    return {
        "strike": strike,
        "daysToExpiry": req.daysToExpiry,
        "iv": req.iv,
        "targetDelta": target,
        "mark": mark,
        "delta": greeks["delta"],
    }


class SpxHedgeRequest(BaseModel):
    """Inputs for the SPX-put hedge sizing. ``netExposure``/``nlv`` come from the
    client (held from the latest /api/portfolio: netBetaWeightedExposure / nlv).
    The tunables default to config when omitted; ``spxLevel`` is a fallback used
    only if the live SPX quote is unavailable. ``assumedIv`` is in percent."""

    netExposure: float
    nlv: float
    hedgeFraction: float | None = None
    targetLeverage: float | None = None
    targetDelta: float | None = None
    floorDelta: float | None = None  # lower (short) put leg for vertical/seagull
    targetDte: int | None = None
    assumedIv: float | None = None  # percent (e.g. 20.0 for 20%)
    spxLevel: float | None = None


@app.post("/api/spx-hedge")
def compute_spx_hedge(req: SpxHedgeRequest) -> dict:
    """Build the three SPX-hedge proposals (long put / vertical / seagull) against
    the portfolio's net beta-weighted dollar exposure (DESIGN §12). **I/O-free:**
    the SPX market inputs (level + chain + IV) come from the cache populated by the
    last live portfolio refresh (``_cache_spx_market``); if no snapshot exists this
    session it degrades to model pricing off the client-supplied ``spxLevel``. So
    once the gateway has been up, hedge what-ifs recompute from cache with no new
    IBKR connection."""
    cfg = config.load_config(CONFIG_PATH)
    target_delta = req.targetDelta if req.targetDelta is not None else cfg.spx_target_put_delta
    floor_delta = req.floorDelta if req.floorDelta is not None else cfg.spx_floor_put_delta
    target_dte = req.targetDte if req.targetDte is not None else cfg.spx_target_dte
    iv_override = (req.assumedIv / 100.0) if req.assumedIv is not None else None
    # Sizing precedence: explicit targetLeverage → explicit hedgeFraction → config
    # default (target-leverage, i.e. the minimum hedge to get under target_leverage).
    if req.targetLeverage is not None:
        target_leverage, hedge_fraction = req.targetLeverage, cfg.spx_hedge_fraction
    elif req.hedgeFraction is not None:
        target_leverage, hedge_fraction = None, req.hedgeFraction
    else:
        target_leverage, hedge_fraction = cfg.spx_target_leverage, cfg.spx_hedge_fraction

    market = _resolve_spx_market(cfg, req.spxLevel, target_dte)
    sigma = iv_override if iv_override is not None else market["iv"]
    result = calc.spx_hedge_proposals(
        net_exposure=req.netExposure,
        nlv=req.nlv,
        spx_level=market["spxLevel"],
        dte=market["dte"],
        r=cfg.risk_free_rate,
        q=cfg.spx_dividend_yield,
        sigma=sigma,
        target_put_delta=target_delta,
        floor_put_delta=floor_delta,
        hedge_fraction=hedge_fraction,
        target_leverage=target_leverage,
        strikes=market["strikes"],
    )
    result.update({
        "source": market["source"],
        "cachedAt": market["cachedAt"],
        "targetDelta": target_delta,
        "floorPutDelta": floor_delta,
    })
    return result


def _resolve_spx_market(cfg: config.Config, spx_level_fallback: float | None, target_dte: int) -> dict:
    """Resolve the SPX market inputs for the hedge proposals **without IBKR I/O**:
    prefer the cache populated by the last live portfolio refresh
    (``_cache_spx_market``), re-picking the expiry for the requested ``target_dte``
    cap from the cached chain. With no cache this session, fall back to the
    client-supplied SPX level + config assumed IV (model pricing, no chain → a
    synthetic strike grid in ``calc``). Raises 503 only when there's neither."""
    cached = spx_cache.load_spx()
    if cached and cached.get("spxLevel"):
        expirations = cached.get("expirations") or []
        dte = _days_to_expiry(_pick_expiry(expirations, target_dte)) if expirations else target_dte
        return {
            "spxLevel": cached["spxLevel"],
            "dte": dte,
            "strikes": cached.get("strikes") or None,
            "iv": cached.get("iv") or cfg.spx_assumed_iv,
            "source": cached.get("source", "live"),
            "cachedAt": cached.get("cachedAt"),
        }
    if not spx_level_fallback or spx_level_fallback <= 0:
        raise HTTPException(status_code=503, detail="無法取得 SPX 指數價格,且無快照可用")
    return {
        "spxLevel": spx_level_fallback,
        "dte": target_dte,
        "strikes": None,
        "iv": cfg.spx_assumed_iv,
        "source": "model",
        "cachedAt": None,
    }


def _cache_spx_market(ib: IB, cfg: config.Config) -> float:
    """Snapshot the live SPX market inputs (index level + option chain + a
    calibrated IV) into ``spx_cache`` for the I/O-free hedge endpoint, and return
    the SPX level for the portfolio banner. IV is implied from a near-target live
    put quote when the account has an options feed, else the config assumed IV
    (still a live spot/chain, tagged 'model'). Best-effort: any failure leaves the
    previous cache intact and is swallowed by the caller's try/except."""
    level = ibkr_client.fetch_spx_level(ib)
    if math.isnan(level):
        return math.nan
    iv, source = cfg.spx_assumed_iv, "model"
    try:
        expirations, strikes = ibkr_client.fetch_spx_option_params(ib)
    except Exception:
        logger.exception("SPX option-chain fetch failed; caching level only")
        expirations, strikes = [], []
    if expirations and strikes:
        try:
            chosen = _pick_expiry(expirations, cfg.spx_target_dte)
            T = _days_to_expiry(chosen) / 365.0
            raw_k = calc.put_strike_for_delta(level, cfg.spx_target_put_delta, T, cfg.risk_free_rate, cfg.spx_dividend_yield, cfg.spx_assumed_iv)
            strike = min(strikes, key=lambda s: abs(s - raw_k))
            quote = ibkr_client.fetch_option_quote(ib, Option("SPX", chosen, strike, "P", "SMART", tradingClass="SPX"))
            if quote.get("iv") is not None:
                iv, source = quote["iv"] / 100.0, "live"
            elif quote.get("price") is not None:
                iv = calc.implied_vol(quote["price"], level, strike, T, cfg.risk_free_rate, cfg.spx_dividend_yield, "P")
                source = "live"
        except Exception:
            logger.exception("SPX IV calibration failed; using assumed IV")
    spx_cache.save_spx({
        "spxLevel": level,
        "expirations": expirations,
        "strikes": strikes,
        "iv": iv,
        "source": source,
        "cachedAt": cache.now_iso(),
    })
    return level


def _pick_expiry(expirations: list[str], target_dte: int) -> str:
    """The YYYYMMDD expiry to hedge with, treating ``target_dte`` as a **cap**: the
    longest-dated expiry that is still ≤ ``target_dte`` (so ``target_dte`` = 30
    yields ≤ 30 DTE). Falls back to the nearest-dated expiry when every listed
    expiry is beyond the cap."""
    future = [e for e in expirations if _days_to_expiry(e) > 0]
    pool = future or expirations
    capped = [e for e in pool if _days_to_expiry(e) <= target_dte]
    if capped:
        return max(capped, key=_days_to_expiry)
    return min(pool, key=_days_to_expiry)


def _fetch_live_portfolio(cfg: config.Config) -> dict:
    """Connects to IB Gateway and builds a fresh portfolio payload. Raises on
    any connection/fetch failure (the caller decides whether to fall back to
    the cache)."""
    ib = ibkr_client.connect(cfg.ib_gateway_host, cfg.ib_gateway_port, cfg.ib_gateway_client_id)
    try:
        raw_positions, warnings = _collect_positions(ib, cfg)
        account_values = ibkr_client.fetch_account_values(ib)
        underlyings = {p["underlying"] for p in raw_positions}
        # Beta + SPX level feed the hedge banner/panel; a failure here must not
        # sink the whole portfolio fetch (it still falls back to cache otherwise),
        # so each degrades gracefully (betas → 1.0 default, spx_level → 0).
        try:
            ibkr_betas = ibkr_client.fetch_betas(ib, underlyings)
        except Exception:
            logger.exception("Beta fetch failed; defaulting all betas")
            ibkr_betas = {}
        try:
            # Also caches the SPX option chain + calibrated IV so the (I/O-free)
            # hedge endpoint can recompute proposals from cache (DESIGN §12).
            spx_level = _cache_spx_market(ib, cfg)
        except Exception:
            logger.exception("SPX market fetch failed")
            spx_level = math.nan
    finally:
        ib.disconnect()

    nlv = account_values.get("NetLiquidation")
    if nlv is None:
        raise ValueError("NetLiquidation not found in account summary")
    margin = _build_margin(account_values, nlv, cfg)

    betas, defaulted = _resolve_betas(underlyings, ibkr_betas, cfg)
    if defaulted:
        warnings.append(f"Beta 預設為 1.0(IBKR 未提供且無 config 覆寫):{', '.join(sorted(defaulted))}")
    if math.isnan(spx_level):
        spx_level = 0.0

    icon_lookup = {
        symbol: icons.get_icon_and_color(symbol, cfg.logo_api_key)
        for symbol in underlyings
    }
    return build_portfolio_response(raw_positions, nlv, icon_lookup, warnings, margin, betas, spx_level, cfg.spx_warning_leverage)


def _resolve_betas(underlyings: set[str], ibkr_betas: dict, cfg: config.Config) -> tuple[dict[str, float], list[str]]:
    """Effective beta per underlying: config override first, then IBKR's
    fundamental beta, else left out (the pure calc then defaults it to 1.0).
    Returns (betas, symbols that fell through to the 1.0 default). Pure."""
    betas: dict[str, float] = {}
    defaulted: list[str] = []
    for sym in underlyings:
        b = cfg.beta_for(sym)
        if b is None:
            b = ibkr_betas.get(sym)
        if b is None:
            defaulted.append(sym)
        else:
            betas[sym] = b
    return betas, defaulted


def _build_margin(account_values: dict, nlv: float, cfg: config.Config) -> dict | None:
    """Builds the margin-buffer block from account-summary values, or None when
    the gateway didn't report a maintenance-margin figure (e.g. a cash account
    or a summary that hasn't populated those tags yet)."""
    if "MaintMarginReq" not in account_values:
        return None
    return calc.margin_summary(
        nlv=nlv,
        maint_margin=account_values["MaintMarginReq"],
        excess_liquidity=account_values.get("ExcessLiquidity", 0.0),
        lookahead_maint=account_values.get("LookAheadMaintMarginReq"),
        lookahead_excess=account_values.get("LookAheadExcessLiquidity"),
        cash=account_values.get("TotalCashValue"),
        available_funds=account_values.get("AvailableFunds"),
        warning_cushion=cfg.margin_warning_cushion,
        danger_cushion=cfg.margin_danger_cushion,
    )


def _collect_positions(ib: IB, cfg: config.Config) -> tuple[list[dict], list[str]]:
    """Pulls raw ib_insync positions, resolves underlying prices/Greeks, and
    returns calc-ready position dicts plus any per-symbol warnings.

    Market data for the *whole* portfolio is fetched in one batched call
    (ibkr_client.fetch_market_data) before the per-position loop, so the loop
    itself is pure CPU work — no serial per-position network waits (DESIGN §9)."""
    raw_positions = list(ibkr_client.fetch_positions(ib))
    underlying_symbols = {p.contract.symbol for p in raw_positions}
    option_contracts = [p.contract for p in raw_positions if p.contract.secType == "OPT"]
    price_map, option_ticker_map = ibkr_client.fetch_market_data(
        ib, underlying_symbols, option_contracts
    )

    positions = []
    warnings: list[str] = []
    for pos in raw_positions:
        try:
            positions.append(_position_to_record(pos, cfg, price_map, option_ticker_map))
        except Exception as exc:
            logger.exception("Failed to convert position %s to record", pos.contract.symbol)
            warnings.append(f"{pos.contract.symbol}: {exc}")
    return positions, warnings


def _position_to_record(
    pos: Position, cfg: config.Config, price_map: dict, option_ticker_map: dict
) -> dict:
    """Builds a calc-ready dict for one IB position from pre-fetched market data,
    branching on option vs. leveraged-ETF vs. plain stock. Pure: no I/O."""
    contract = pos.contract
    underlying_price = price_map.get(contract.symbol, math.nan)
    if math.isnan(underlying_price):
        raise ValueError(f"no valid market price for {contract.symbol}")
    if contract.secType == "OPT":
        ticker = option_ticker_map.get(contract.conId)
        if ticker is None:
            raise ValueError(f"no option market data for {contract.localSymbol}")
        notional = calc.option_notional(pos.position, underlying_price)
        mark = ibkr_client.mark_price(ticker)
        days = _days_to_expiry(contract.lastTradeDateOrContractMonth)
        if ticker.modelGreeks and ticker.modelGreeks.delta is not None:
            delta = ticker.modelGreeks.delta
            theta = ticker.modelGreeks.theta or 0.0
            vega = ticker.modelGreeks.vega or 0.0
            iv = (ticker.modelGreeks.impliedVol or 0.0) * 100
        else:
            if math.isnan(mark):
                raise ValueError(f"no valid option mark price for {contract.localSymbol}")
            T = days / 365.0
            q = cfg.dividend_yield_for(contract.symbol)
            right = "C" if contract.right == "C" else "P"
            sigma = calc.implied_vol(mark, underlying_price, contract.strike, T, cfg.risk_free_rate, q, right)
            greeks = calc.bs_greeks(underlying_price, contract.strike, T, cfg.risk_free_rate, q, sigma, right)
            delta, theta, vega, iv = greeks["delta"], greeks["theta"], greeks["vega"], sigma * 100
        exposure = calc.option_exposure(notional, delta)
        return {
            "label": f"{contract.symbol} {contract.strike:g}{contract.right} {contract.lastTradeDateOrContractMonth}",
            "underlying": cfg.leveraged_etf_map.get(contract.symbol, {}).get("underlying", contract.symbol),
            "type": "COPT" if contract.right == "C" else "POPT",
            "notional": notional, "exposure": exposure, "discount": calc.discount(notional, exposure),
            "delta": delta, "theta": theta, "vega": vega, "iv": iv, "underlying_price": underlying_price,
            "quantity": pos.position,
            # Surfaced for the roll what-if SP picker (strike, per-share mark,
            # days-to-expiry). `mark` is None when no live/close price priced the
            # leg; the picker then model-prices it off `iv` via /api/price-option.
            "strike": contract.strike, "mark": None if math.isnan(mark) else mark,
            "daysToExpiry": days,
        }

    mapping = cfg.leveraged_etf_map.get(contract.symbol)
    price = underlying_price
    if mapping:
        notional = calc.leveraged_etf_notional(pos.position, price, mapping["multiplier"])
        underlying = mapping["underlying"]
        delta = mapping["multiplier"] if pos.position >= 0 else -mapping["multiplier"]
    else:
        notional = calc.stock_notional(pos.position, price)
        underlying = contract.symbol
        delta = 1.0 if pos.position >= 0 else -1.0
    return {
        "label": f"{contract.symbol}→{underlying}" if mapping else contract.symbol,
        "underlying": underlying, "type": "STK",
        "notional": notional, "exposure": notional, "discount": 0.0,
        "delta": delta, "theta": 0.0, "vega": 0.0, "iv": None, "underlying_price": price,
        "quantity": pos.position,
        "strike": None, "mark": None, "daysToExpiry": None,
    }


def _days_to_expiry(expiry_str: str) -> int:
    """Calendar days from today to an IB-format YYYYMMDD expiry (floored at 1)."""
    expiry = date(int(expiry_str[:4]), int(expiry_str[4:6]), int(expiry_str[6:8]))
    return max((expiry - date.today()).days, 1)


def _years_to_expiry(expiry_str: str) -> float:
    """Converts an IB-format YYYYMMDD expiry string into a year fraction from today (floored at 1/365)."""
    return _days_to_expiry(expiry_str) / 365.0
