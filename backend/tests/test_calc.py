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
