import pytest
from backend import calc


def test_stock_notional_is_shares_times_price():
    assert calc.stock_notional(quantity=100, price=250.0) == 25000.0


def test_stock_notional_uses_absolute_quantity():
    assert calc.stock_notional(quantity=-100, price=250.0) == 25000.0


def test_leveraged_etf_notional_applies_multiplier():
    assert calc.leveraged_etf_notional(quantity=200, price=20.0, multiplier=2.0) == 8000.0


def test_option_notional_is_contracts_times_100_times_underlying():
    assert calc.option_notional(contracts=4, underlying_price=200.0) == 80000.0


def test_option_exposure_uses_absolute_delta():
    assert calc.option_exposure(notional=80000.0, delta=-0.45) == pytest.approx(36000.0)


def test_discount_formula():
    assert calc.discount(notional=80000.0, exposure=36000.0) == pytest.approx(0.55)


def test_discount_is_zero_when_notional_is_zero():
    assert calc.discount(notional=0.0, exposure=0.0) == 0.0


def test_bs_price_matches_known_textbook_value():
    # S=100, K=100, T=1y, r=5%, q=0%, sigma=20% -> classic textbook call price ~10.45
    price = calc.bs_price(S=100, K=100, T=1.0, r=0.05, q=0.0, sigma=0.20, right="C")
    assert price == pytest.approx(10.45, abs=0.01)


def test_bs_price_put_call_parity():
    call = calc.bs_price(S=100, K=100, T=1.0, r=0.05, q=0.0, sigma=0.20, right="C")
    put = calc.bs_price(S=100, K=100, T=1.0, r=0.05, q=0.0, sigma=0.20, right="P")
    # put-call parity: C - P = S*e^-qT - K*e^-rT
    import math
    rhs = 100 * math.exp(0) - 100 * math.exp(-0.05)
    assert (call - put) == pytest.approx(rhs, abs=0.01)


def test_implied_vol_recovers_known_sigma():
    true_sigma = 0.35
    mark = calc.bs_price(S=200, K=210, T=0.25, r=0.0425, q=0.0, sigma=true_sigma, right="P")
    recovered = calc.implied_vol(mark_price=mark, S=200, K=210, T=0.25, r=0.0425, q=0.0, right="P")
    assert recovered == pytest.approx(true_sigma, abs=1e-3)


def test_bs_greeks_call_delta_between_0_and_1():
    g = calc.bs_greeks(S=100, K=100, T=1.0, r=0.05, q=0.0, sigma=0.20, right="C")
    assert 0.0 < g["delta"] < 1.0
    assert g["delta"] == pytest.approx(0.6368, abs=0.001)


def test_bs_greeks_put_delta_between_minus1_and_0():
    g = calc.bs_greeks(S=100, K=100, T=1.0, r=0.05, q=0.0, sigma=0.20, right="P")
    assert -1.0 < g["delta"] < 0.0


def test_bs_greeks_vega_is_positive():
    g = calc.bs_greeks(S=100, K=100, T=1.0, r=0.05, q=0.0, sigma=0.20, right="C")
    assert g["vega"] > 0
