"""Thin wrapper around ib_insync. No business logic — see calc.py for that.

Requires a running, logged-in IB Gateway (IB API mode) reachable at the
configured host/port. Never calls any order-placement method.
"""
import asyncio
import math
import random

from collections.abc import Iterable

from ib_insync import IB, Stock, Option, Index, Position, Ticker


def mark_price(ticker: Ticker) -> float:
    """Best available mark from a ticker: the live/delayed market price when
    present, otherwise the previous close. `close` is often available for free
    even on accounts with no real-time quote subscription (notably options
    without an OPRA feed), so this keeps the dashboard usable end-of-day."""
    price = ticker.marketPrice()
    if not math.isnan(price):
        return price
    return ticker.close


def connect(host: str, port: int, client_id: int, timeout: float = 10.0, attempts: int = 4) -> IB:
    # ib_insync is asyncio-based and requires an event loop bound to the
    # current thread. FastAPI runs sync `def` routes in a worker thread
    # (via anyio's threadpool), which has no event loop by default.
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    # Each request opens its own connection, but a fixed clientId collides when
    # two connects overlap (React StrictMode double-fetch, rapid refresh) or a
    # previous connection lingers on the gateway: IB returns Error 326
    # "client id is already in use" and ib_insync then hangs until the connect
    # timeout, surfacing as a misleading "can't connect to gateway" 503. So try
    # the configured id first (the common single-request case), then fall back
    # to random ids until one is free.
    candidate_ids = [client_id] + [random.randint(1000, 9999) for _ in range(attempts - 1)]
    last_exc: Exception | None = None
    for cid in candidate_ids:
        ib = IB()
        try:
            ib.connect(host, port, clientId=cid, timeout=timeout, readonly=True)
            # Fall back to delayed market data when the account has no live-data
            # subscription for a symbol (type 3 = delayed); live data is still
            # used automatically wherever a subscription does exist.
            ib.reqMarketDataType(3)
            return ib
        except Exception as exc:  # noqa: BLE001 - retry on any connect failure
            last_exc = exc
            ib.disconnect()
    raise last_exc  # type: ignore[misc]


def fetch_positions(ib: IB) -> list[Position]:
    return ib.positions()


# Account-summary tags we read. NetLiquidation drives leverage; the rest feed
# the margin-buffer card. ib_insync's accountSummary() returns the full default
# tag set in one call, so all of these arrive together (no extra round-trips).
# All read-only — no order/account-modifying calls (DESIGN §6).
ACCOUNT_VALUE_TAGS = (
    "NetLiquidation",
    "MaintMarginReq",
    "ExcessLiquidity",
    "LookAheadMaintMarginReq",
    "LookAheadExcessLiquidity",
    # Funding axis (distinct from liquidation risk): can we still open/roll?
    # AvailableFunds = ELV - InitMargin (always <= ExcessLiquidity, so it goes
    # to zero first); TotalCashValue is the literal cash balance.
    "TotalCashValue",
    "AvailableFunds",
)


def fetch_account_values(ib: IB) -> dict[str, float]:
    """Returns the subset of account-summary values in ACCOUNT_VALUE_TAGS as
    floats (tags whose value won't parse as a number are skipped). One
    accountSummary() call covers both NLV and all margin fields."""
    values: dict[str, float] = {}
    for v in ib.accountSummary():
        if v.tag in ACCOUNT_VALUE_TAGS:
            try:
                values[v.tag] = float(v.value)
            except ValueError:
                pass
    return values


def fetch_nlv(ib: IB) -> float:
    values = fetch_account_values(ib)
    if "NetLiquidation" not in values:
        raise ValueError("NetLiquidation not found in account summary")
    return values["NetLiquidation"]


def fetch_market_data(
    ib: IB,
    underlying_symbols: Iterable[str],
    option_contracts: list[Option],
    timeout: float = 15.0,
    poll_interval: float = 0.5,
    exchange: str = "SMART",
    currency: str = "USD",
) -> tuple[dict[str, float], dict[int, Ticker]]:
    """Batch-fetch every underlying price and option ticker for the whole
    portfolio in a *single* bounded wait, and return:

      - ``price_map``: {underlying symbol -> mark price (float, NaN if none)}
      - ``option_ticker_map``: {option conId -> Ticker}

    Why batched: ib_insync is asyncio-based, so we can fire all snapshot
    `reqMktData` requests up front and then wait for replies to stream in
    concurrently. The old per-position approach paid a separate ~2-6s
    `ib.sleep` for each position serially (DESIGN §9); here the dominant cost
    collapses to one wait for the entire request. Underlyings are also
    deduplicated, so an option and its stock share one price fetch.

    A plain snapshot (no genericTickList="106" option-computation tick) avoids
    the live-OPRA-subscription requirement, so with delayed market data enabled
    it still yields a mark price for accounts without an options data feed
    (DESIGN G4). modelGreeks is therefore typically None on option tickers, and
    the caller falls back to calc.implied_vol/calc.bs_greeks off the mark.

    The wait is *polled* in small increments and exits as soon as every
    contract already has a usable mark (DESIGN §9 "known limitations"),
    instead of always sleeping the full window — so the common case (all data
    in within a couple seconds) is still fast, while a slow/just-warming-up
    line for one symbol (the intermittent "no valid option mark price" case)
    gets the rest of the budget instead of being dropped immediately. A
    polled `ib.sleep` is used instead of `ib.reqTickers`, because the latter
    waits on *every* snapshot with no timeout and would hang forever if one
    option's snapshot never ends (the common non-OPRA case)."""
    symbols = list(underlying_symbols)
    stock_contracts = [Stock(s, exchange, currency) for s in symbols]
    for c in option_contracts:
        # Option contracts from positions() carry no exchange; reqMktData needs
        # one or IB returns "Please enter exchange" (DESIGN G5).
        if not c.exchange:
            c.exchange = exchange

    all_contracts: list = [*stock_contracts, *option_contracts]
    if not all_contracts:
        return {}, {}

    # qualifyContracts only logs+skips unknown contracts (never raises), so a
    # bad symbol just ends up with a NaN price and is isolated downstream.
    ib.qualifyContracts(*all_contracts)
    tickers = [ib.reqMktData(c, "", snapshot=True) for c in all_contracts]
    try:
        elapsed = 0.0
        while elapsed < timeout:
            ib.sleep(poll_interval)
            elapsed += poll_interval
            if all(not math.isnan(mark_price(t)) for t in tickers):
                break
    finally:
        for c in all_contracts:
            ib.cancelMktData(c)

    n = len(stock_contracts)
    price_map = {sym: mark_price(t) for sym, t in zip(symbols, tickers[:n])}
    # Position contracts always carry a conId from IB, so keying by conId is
    # stable even before qualification.
    option_ticker_map = {c.conId: t for c, t in zip(option_contracts, tickers[n:])}
    return price_map, option_ticker_map


def _beta_of(ticker: Ticker) -> float | None:
    """Pull the beta out of a ticker's fundamental ratios (generic tick 258), or
    None when absent/unparseable. ib_insync exposes it as
    ``ticker.fundamentalRatios.BETA``."""
    fr = getattr(ticker, "fundamentalRatios", None)
    beta = getattr(fr, "BETA", None) if fr is not None else None
    if beta is None:
        return None
    try:
        b = float(beta)
    except (ValueError, TypeError):
        return None
    return None if math.isnan(b) else b


def fetch_betas(
    ib: IB,
    symbols: Iterable[str],
    timeout: float = 8.0,
    poll_interval: float = 0.5,
    exchange: str = "SMART",
    currency: str = "USD",
) -> dict[str, float | None]:
    """Per-symbol beta vs the S&P 500 from IBKR fundamental ratios (generic tick
    258). Returns {symbol -> beta or None}; None means IBKR didn't supply it
    (no Reuters-fundamentals entitlement, or an index/ETF with no beta) and the
    caller should fall back to a config override or 1.0.

    Kept separate from ``fetch_market_data`` so the proven price-snapshot path is
    untouched: this uses a *streaming* (non-snapshot) request because the
    fundamental-ratios tick isn't delivered on plain snapshots, with the same
    bounded/polled wait + cancel discipline (DESIGN §G9). Read-only."""
    symbols = list(symbols)
    if not symbols:
        return {}
    contracts = [Stock(s, exchange, currency) for s in symbols]
    ib.qualifyContracts(*contracts)
    tickers = [ib.reqMktData(c, "258", snapshot=False) for c in contracts]
    try:
        elapsed = 0.0
        while elapsed < timeout:
            ib.sleep(poll_interval)
            elapsed += poll_interval
            if all(_beta_of(t) is not None for t in tickers):
                break
    finally:
        for c in contracts:
            ib.cancelMktData(c)
    return {sym: _beta_of(t) for sym, t in zip(symbols, tickers)}


def fetch_spx_level(ib: IB, timeout: float = 10.0, poll_interval: float = 0.5) -> float:
    """Snapshot mark for the SPX cash index (NaN if it never priced). Read-only."""
    spx = Index("SPX", "CBOE", "USD")
    ib.qualifyContracts(spx)
    ticker = ib.reqMktData(spx, "", snapshot=True)
    try:
        elapsed = 0.0
        while elapsed < timeout:
            ib.sleep(poll_interval)
            elapsed += poll_interval
            if not math.isnan(mark_price(ticker)):
                break
    finally:
        ib.cancelMktData(spx)
    return mark_price(ticker)


def fetch_spx_option_params(ib: IB) -> tuple[list[str], list[float]]:
    """SPX option-chain expirations + strikes via reqSecDefOptParams. Returns
    (sorted YYYYMMDD expirations, sorted strikes). Prefers the SMART/SPX chain,
    unioning across returned chains as a fallback. Read-only."""
    spx = Index("SPX", "CBOE", "USD")
    ib.qualifyContracts(spx)
    chains = ib.reqSecDefOptParams(spx.symbol, "", spx.secType, spx.conId)
    if not chains:
        return [], []
    preferred = [c for c in chains if c.exchange == "SMART" and c.tradingClass == "SPX"]
    selected = preferred or chains
    expirations: set[str] = set()
    strikes: set[float] = set()
    for c in selected:
        expirations.update(c.expirations)
        strikes.update(c.strikes)
    return sorted(expirations), sorted(strikes)


def fetch_option_quote(
    ib: IB, option: Option, timeout: float = 10.0, poll_interval: float = 0.5
) -> dict:
    """Snapshot quote + model greeks for a single option (generic tick 106 for
    the option-computation/greeks). Returns {price, delta, iv} with None/NaN when
    the account has no options data feed (caller then model-prices). Read-only —
    no order methods."""
    if not option.exchange:
        option.exchange = "SMART"
    ib.qualifyContracts(option)
    ticker = ib.reqMktData(option, "106", snapshot=True)
    try:
        elapsed = 0.0
        while elapsed < timeout:
            ib.sleep(poll_interval)
            elapsed += poll_interval
            if not math.isnan(mark_price(ticker)) and ticker.modelGreeks:
                break
    finally:
        ib.cancelMktData(option)
    price = mark_price(ticker)
    greeks = ticker.modelGreeks
    return {
        "price": None if math.isnan(price) else price,
        "delta": greeks.delta if greeks and greeks.delta is not None else None,
        "iv": (greeks.impliedVol * 100) if greeks and greeks.impliedVol is not None else None,
    }
