"""Thin wrapper around ib_insync. No business logic — see calc.py for that.

Requires a running, logged-in IB Gateway (IB API mode) reachable at the
configured host/port. Never calls any order-placement method.
"""
import asyncio

from ib_insync import IB, Stock, Option, Position, Ticker


def connect(host: str, port: int, client_id: int, timeout: float = 10.0) -> IB:
    # ib_insync is asyncio-based and requires an event loop bound to the
    # current thread. FastAPI runs sync `def` routes in a worker thread
    # (via anyio's threadpool), which has no event loop by default.
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    ib = IB()
    ib.connect(host, port, clientId=client_id, timeout=timeout, readonly=True)
    # Fall back to delayed market data when the account has no live-data
    # subscription for a symbol (type 3 = delayed); live data is still used
    # automatically wherever a subscription does exist.
    ib.reqMarketDataType(3)
    return ib


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
        return ticker.marketPrice()
    finally:
        ib.cancelMktData(contract)


def fetch_option_market_data(ib: IB, option_contract: Option, timeout: float = 4.0) -> Ticker:
    """Returns the ib_insync Ticker; ticker.modelGreeks may be None if there
    is no live options market-data subscription — caller must fall back to
    calc.implied_vol/calc.bs_greeks in that case."""
    if not option_contract.exchange:
        option_contract.exchange = "SMART"
    ib.qualifyContracts(option_contract)
    ticker = ib.reqMktData(option_contract, genericTickList="106")
    try:
        ib.sleep(timeout)
        return ticker
    finally:
        ib.cancelMktData(option_contract)
