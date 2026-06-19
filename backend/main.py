import logging
import math
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from ib_insync import IB, Position

from backend import calc, config, ibkr_client, icons

app = FastAPI()
icons.CACHE_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/icons", StaticFiles(directory=str(icons.CACHE_DIR)), name="icons")
CONFIG_PATH = Path(__file__).parent / "config.json"
logger = logging.getLogger(__name__)


def build_portfolio_response(positions: list[dict], nlv: float, icon_lookup: dict, warnings: list[str]) -> dict:
    """Assembles the full portfolio API payload (totals, leverage, greeks, per-underlying rows) from position records."""
    underlying_rows = calc.aggregate_by_underlying(positions)
    total_notional = sum(row["notional"] for row in underlying_rows)
    total_exposure = sum(row["exposure"] for row in underlying_rows)
    leverage = calc.portfolio_leverage(total_notional, total_exposure, nlv)

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
        "underlyings": underlyings,
        "positions": positions,
        "warnings": warnings,
    }


@app.get("/api/portfolio")
def get_portfolio() -> dict:
    """Connects to IB Gateway and returns the full portfolio response payload."""
    cfg = config.load_config(CONFIG_PATH)
    try:
        ib = ibkr_client.connect(cfg.ib_gateway_host, cfg.ib_gateway_port, cfg.ib_gateway_client_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"無法連線到 IB Gateway，請確認已啟動並登入: {exc}")

    try:
        raw_positions, warnings = _collect_positions(ib, cfg)
        nlv = ibkr_client.fetch_nlv(ib)
    finally:
        ib.disconnect()

    underlyings = {p["underlying"] for p in raw_positions}
    icon_lookup = {
        symbol: icons.get_icon_and_color(symbol, cfg.logo_api_key)
        for symbol in underlyings
    }
    return build_portfolio_response(raw_positions, nlv, icon_lookup, warnings)


def _collect_positions(ib: IB, cfg: config.Config) -> tuple[list[dict], list[str]]:
    """Pulls raw ib_insync positions, resolves underlying prices/Greeks, and
    returns calc-ready position dicts plus any per-symbol warnings."""
    positions = []
    warnings: list[str] = []
    for pos in ibkr_client.fetch_positions(ib):
        try:
            positions.append(_position_to_record(ib, pos, cfg))
        except Exception as exc:
            logger.exception("Failed to convert position %s to record", pos.contract.symbol)
            warnings.append(f"{pos.contract.symbol}: {exc}")
    return positions, warnings


def _position_to_record(ib: IB, pos: Position, cfg: config.Config) -> dict:
    """Builds a calc-ready dict for one IB position, branching on option vs. leveraged-ETF vs. plain stock."""
    contract = pos.contract
    if contract.secType == "OPT":
        underlying_price = ibkr_client.fetch_underlying_price(ib, contract.symbol)
        if math.isnan(underlying_price):
            raise ValueError(f"no valid market price for {contract.symbol}")
        ticker = ibkr_client.fetch_option_market_data(ib, contract)
        notional = calc.option_notional(pos.position, underlying_price)
        if ticker.modelGreeks and ticker.modelGreeks.delta is not None:
            delta = ticker.modelGreeks.delta
            theta = ticker.modelGreeks.theta or 0.0
            vega = ticker.modelGreeks.vega or 0.0
            iv = (ticker.modelGreeks.impliedVol or 0.0) * 100
        else:
            mark = ibkr_client.mark_price(ticker)
            if math.isnan(mark):
                raise ValueError(f"no valid option mark price for {contract.localSymbol}")
            T = _years_to_expiry(contract.lastTradeDateOrContractMonth)
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
        }

    mapping = cfg.leveraged_etf_map.get(contract.symbol)
    price = ibkr_client.fetch_underlying_price(ib, contract.symbol)
    if math.isnan(price):
        raise ValueError(f"no valid market price for {contract.symbol}")
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
    }


def _years_to_expiry(expiry_str: str) -> float:
    """Converts an IB-format YYYYMMDD expiry string into a year fraction from today (floored at 1/365)."""
    expiry = date(int(expiry_str[:4]), int(expiry_str[4:6]), int(expiry_str[6:8]))
    days = max((expiry - date.today()).days, 1)
    return days / 365.0
