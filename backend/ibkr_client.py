"""Thin wrapper around ib_insync. No business logic — see calc.py for that.

Requires a running, logged-in IB Gateway (IB API mode) reachable at the
configured host/port. Never calls any order-placement method.
"""
from ib_insync import IB, Stock, Option


def connect(host: str, port: int, client_id: int, timeout: float = 10.0) -> IB:
    ib = IB()
    ib.connect(host, port, clientId=client_id, timeout=timeout)
    return ib


def fetch_positions(ib: IB) -> list:
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
    ib.sleep(2.0)
    price = ticker.marketPrice()
    ib.cancelMktData(contract)
    return price


def fetch_option_market_data(ib: IB, option_contract: Option, timeout: float = 4.0):
    """Returns the ib_insync Ticker; ticker.modelGreeks may be None if there
    is no live options market-data subscription — caller must fall back to
    calc.implied_vol/calc.bs_greeks in that case."""
    ticker = ib.reqMktData(option_contract, genericTickList="106")
    ib.sleep(timeout)
    ib.cancelMktData(option_contract)
    return ticker
