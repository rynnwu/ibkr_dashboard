"""Thin wrapper around ib_insync. No business logic — see calc.py for that.

Requires a running, logged-in IB Gateway (IB API mode) reachable at the
configured host/port. Never calls any order-placement method.
"""
import asyncio
import math
import random

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


def fetch_underlying_price(ib: IB, symbol: str, exchange: str = "SMART", currency: str = "USD") -> float:
    contract = Stock(symbol, exchange, currency)
    ib.qualifyContracts(contract)
    ticker = ib.reqMktData(contract, "", snapshot=True)
    try:
        ib.sleep(2.0)
        return mark_price(ticker)
    finally:
        ib.cancelMktData(contract)


def fetch_option_market_data(ib: IB, option_contract: Option, timeout: float = 4.0) -> Ticker:
    """Returns the ib_insync Ticker via a one-time snapshot.

    A plain snapshot (no genericTickList="106" option-computation tick) avoids
    the live-OPRA-subscription requirement, so with delayed market data enabled
    it still yields a mark price for accounts without an options data feed.
    modelGreeks is therefore typically None here, and the caller falls back to
    calc.implied_vol/calc.bs_greeks computed from the snapshot mark price."""
    if not option_contract.exchange:
        option_contract.exchange = "SMART"
    ib.qualifyContracts(option_contract)
    ticker = ib.reqMktData(option_contract, "", snapshot=True)
    try:
        ib.sleep(timeout)
        return ticker
    finally:
        ib.cancelMktData(option_contract)
