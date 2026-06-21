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


def test_aggregate_by_underlying_sums_notional_and_exposure():
    positions = [
        {"underlying": "TSLA", "notional": 1000.0, "exposure": 800.0},
        {"underlying": "TSLA", "notional": 500.0, "exposure": 200.0},
        {"underlying": "GOOG", "notional": 300.0, "exposure": 300.0},
    ]
    result = calc.aggregate_by_underlying(positions)
    by_symbol = {row["underlying"]: row for row in result}
    assert by_symbol["TSLA"]["notional"] == 1500.0
    assert by_symbol["TSLA"]["exposure"] == 1000.0
    assert by_symbol["GOOG"]["notional"] == 300.0


def test_portfolio_leverage_ratios():
    result = calc.portfolio_leverage(total_notional=200_000.0, total_exposure=100_000.0, nlv=50_000.0)
    assert result["notional_leverage"] == pytest.approx(4.0)
    assert result["exposure_leverage"] == pytest.approx(2.0)


def test_portfolio_leverage_returns_zero_when_nlv_is_zero():
    result = calc.portfolio_leverage(total_notional=100.0, total_exposure=50.0, nlv=0.0)
    assert result == {"notional_leverage": 0.0, "exposure_leverage": 0.0}


def test_greeks_card_sums_option_positions_only():
    option_positions = [
        {"delta_shares": 100.0, "theta": 5.0, "vega": -2.0},
        {"delta_shares": -30.0, "theta": 1.0, "vega": 3.0},
    ]
    result = calc.greeks_card(option_positions)
    assert result["net_delta"] == 70.0
    assert result["net_theta"] == 6.0
    assert result["net_vega"] == 1.0


def test_margin_summary_levels_and_ratios():
    # cushion = excess/nlv; buffer = excess/maint
    safe = calc.margin_summary(nlv=100000.0, maint_margin=40000.0, excess_liquidity=50000.0)
    assert safe["level"] == "safe"  # cushion 50% >= 20%
    assert safe["cushion"] == pytest.approx(0.5)
    assert safe["bufferRatio"] == pytest.approx(50000.0 / 40000.0)

    warning = calc.margin_summary(nlv=100000.0, maint_margin=60000.0, excess_liquidity=15000.0)
    assert warning["level"] == "warning"  # cushion 15% in [10%, 20%)

    danger = calc.margin_summary(nlv=100000.0, maint_margin=80000.0, excess_liquidity=5000.0)
    assert danger["level"] == "danger"  # cushion 5% < 10%


def test_margin_summary_respects_custom_thresholds():
    # With a 40% danger threshold, a 30% cushion is danger.
    result = calc.margin_summary(
        nlv=100000.0, maint_margin=50000.0, excess_liquidity=30000.0,
        warning_cushion=0.50, danger_cushion=0.40,
    )
    assert result["level"] == "danger"


def test_margin_summary_buffer_ratio_none_without_maint_margin():
    result = calc.margin_summary(nlv=100000.0, maint_margin=0.0, excess_liquidity=100000.0)
    assert result["bufferRatio"] is None
    assert result["level"] == "safe"


def test_margin_summary_omits_lookahead_when_not_provided():
    result = calc.margin_summary(nlv=100000.0, maint_margin=40000.0, excess_liquidity=50000.0)
    assert "lookAheadMaintMargin" not in result
    assert "lookAheadExcessLiquidity" not in result


def test_margin_summary_includes_lookahead_when_provided():
    result = calc.margin_summary(
        nlv=100000.0, maint_margin=40000.0, excess_liquidity=50000.0,
        lookahead_maint=45000.0, lookahead_excess=42000.0,
    )
    assert result["lookAheadMaintMargin"] == 45000.0
    assert result["lookAheadExcessLiquidity"] == 42000.0


def test_margin_summary_zero_nlv_is_safe_guard():
    result = calc.margin_summary(nlv=0.0, maint_margin=0.0, excess_liquidity=0.0)
    assert result["cushion"] == 0.0
    assert result["level"] == "danger"  # 0 cushion < danger threshold


def test_margin_summary_funding_axis_is_separate_from_level():
    # Liquidation level is driven only by cushion; cash/available_funds are
    # added as a distinct funding axis and must NOT change the level.
    result = calc.margin_summary(
        nlv=100000.0, maint_margin=40000.0, excess_liquidity=50000.0,  # cushion 50% -> safe
        cash=2000.0, available_funds=-500.0,
    )
    assert result["level"] == "safe"  # unaffected by negative available funds
    assert result["cash"] == 2000.0
    assert result["availableFunds"] == -500.0
    assert result["canOpenNew"] is False  # available_funds <= 0


def test_margin_summary_can_open_new_true_when_funds_positive():
    result = calc.margin_summary(
        nlv=100000.0, maint_margin=40000.0, excess_liquidity=50000.0,
        cash=10000.0, available_funds=8000.0,
    )
    assert result["canOpenNew"] is True


def test_margin_summary_omits_funding_fields_when_not_provided():
    result = calc.margin_summary(nlv=100000.0, maint_margin=40000.0, excess_liquidity=50000.0)
    assert "cash" not in result
    assert "availableFunds" not in result
    assert "canOpenNew" not in result
