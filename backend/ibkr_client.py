"""Thin wrapper around ib_insync. No business logic — see calc.py for that.

Requires a running, logged-in IB Gateway (IB API mode) reachable at the
configured host/port. Never calls any order-placement method.
"""
import asyncio
import math
import random

from collections.abc import Iterable

from ib_insync import IB, Stock, Option, Position, Ticker


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


def fetch_nlv(ib: IB) -> float:
    for v in ib.accountSummary():
        if v.tag == "NetLiquidation":
            return float(v.value)
    raise ValueError("NetLiquidation not found in account summary")


def fetch_market_data(
    ib: IB,
    underlying_symbols: Iterable[str],
    option_contracts: list[Option],
    timeout: float = 8.0,
    exchange: str = "SMART",
    currency: str = "USD",
) -> tuple[dict[str, float], dict[int, Ticker]]:
    """Batch-fetch every underlying price and option ticker for the whole
    portfolio in a *single* bounded wait, and return:

      - ``price_map``: {underlying symbol -> mark price (float, NaN if none)}
      - ``option_ticker_map``: {option conId -> Ticker}

    Why batched: ib_insync is asyncio-based, so we can fire all snapshot
    `reqMktData` requests up front and then wait *once* for replies to stream
    in concurrently. The old per-position approach paid a separate ~2-6s
    `ib.sleep` for each position serially (DESIGN §9); here the dominant cost
    collapses to one `timeout` for the entire request. Underlyings are also
    deduplicated, so an option and its stock share one price fetch.

    A plain snapshot (no genericTickList="106" option-computation tick) avoids
    the live-OPRA-subscription requirement, so with delayed market data enabled
    it still yields a mark price for accounts without an options data feed
    (DESIGN G4). modelGreeks is therefore typically None on option tickers, and
    the caller falls back to calc.implied_vol/calc.bs_greeks off the mark.

    A single bounded `ib.sleep` is used instead of `ib.reqTickers`, because the
    latter waits on *every* snapshot with no timeout and would hang forever if
    one option's snapshot never ends (the common non-OPRA case)."""
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
        ib.sleep(timeout)
    finally:
        for c in all_contracts:
            ib.cancelMktData(c)

    n = len(stock_contracts)
    price_map = {sym: mark_price(t) for sym, t in zip(symbols, tickers[:n])}
    # Position contracts always carry a conId from IB, so keying by conId is
    # stable even before qualification.
    option_ticker_map = {c.conId: t for c, t in zip(option_contracts, tickers[n:])}
    return price_map, option_ticker_map
