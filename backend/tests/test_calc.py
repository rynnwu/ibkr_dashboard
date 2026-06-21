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


def test_cushion_level_bands():
    assert calc.cushion_level(0.50) == "safe"
    assert calc.cushion_level(0.15) == "warning"
    assert calc.cushion_level(0.05) == "danger"
    # custom thresholds
    assert calc.cushion_level(0.30, warning_cushion=0.50, danger_cushion=0.40) == "danger"


def test_regt_short_put_maint_otm_uses_20pct_minus_otm_amount():
    # S=200, K=180 (OTM put), put_mark=2 -> per share = max(0.20*200-(200-180),0.10*180)+2
    # = max(40-20, 18)+2 = 20+2 = 22 ; 2 contracts -> 2*100*22 = 4400
    assert calc.regt_short_put_maint(contracts=-2, S=200, K=180, put_mark=2) == pytest.approx(4400.0)


def test_regt_short_put_maint_deep_otm_floors_at_10pct_strike():
    # S=300 far above K=100 -> 0.20*300-(300-100)=60-200=-140 -> floored to 0.10*100=10
    # per share = 10 + put_mark(1) = 11 ; 1 contract -> 1100
    assert calc.regt_short_put_maint(contracts=1, S=300, K=100, put_mark=1) == pytest.approx(1100.0)


def test_call_strike_for_delta_round_trips_through_bs_greeks():
    # The strike produced for a target delta should, when priced, recover it.
    S, T, r, q, sigma = 250.0, 180 / 365.0, 0.0425, 0.0, 0.45
    for target in (0.60, 0.85, 0.95):
        K = calc.call_strike_for_delta(S, target, T, r, q, sigma)
        recovered = calc.bs_greeks(S, K, T, r, q, sigma, "C")["delta"]
        assert recovered == pytest.approx(target, abs=1e-3)


def test_call_strike_for_delta_higher_delta_is_deeper_itm():
    S, T, r, q, sigma = 250.0, 0.5, 0.0425, 0.0, 0.4
    k_low = calc.call_strike_for_delta(S, 0.60, T, r, q, sigma)
    k_high = calc.call_strike_for_delta(S, 0.90, T, r, q, sigma)
    # higher delta -> deeper ITM -> lower strike
    assert k_high < k_low < S * 2


def test_roll_what_if_close_sp_into_long_call_margin_and_funding():
    result = calc.roll_what_if(
        excess_liquidity=50000.0, nlv=200000.0,
        mm_sp=8000.0, close_sp_debit=2000.0,
        open_call_premium=3000.0,
        cash=10000.0, available_funds=20000.0,
    )
    # EL: 50000 + 8000 (release SP) - 3000 (call premium) = 55000
    assert result["excessLiquidityAfter"] == pytest.approx(55000.0)
    assert result["cushionAfter"] == pytest.approx(55000.0 / 200000.0)
    assert result["levelAfter"] == "safe"
    assert result["deltaExcessLiquidity"]["closeShortPut"] == 8000.0
    assert result["deltaExcessLiquidity"]["openLongCall"] == -3000.0
    # Funding outflow = D + premium = 2000 + 3000 = 5000; surplus = 10000 - 5000
    assert result["fundingOutflow"] == pytest.approx(5000.0)
    assert result["surplus"] == pytest.approx(5000.0)
    assert result["canExecute"] is True
    assert result["shortfall"] == 0.0
    assert result["availableFundsAfter"] == pytest.approx(28000.0)  # 20000 + 8000 released


def test_roll_what_if_funding_shortfall_when_cash_insufficient():
    result = calc.roll_what_if(
        excess_liquidity=50000.0, nlv=200000.0,
        mm_sp=8000.0, close_sp_debit=9000.0, open_call_premium=4000.0,
        cash=10000.0, loan_value_other=1000.0,
    )
    # outflow 13000, funds 11000 -> surplus -2000
    assert result["surplus"] == pytest.approx(-2000.0)
    assert result["canExecute"] is False
    assert result["shortfall"] == pytest.approx(2000.0)


def test_roll_what_if_buy_2x_etf_ties_up_maintenance_margin():
    result = calc.roll_what_if(
        excess_liquidity=50000.0, nlv=200000.0,
        mm_sp=8000.0, close_sp_debit=2000.0,
        open_etf_value=20000.0, etf_maint_rate=0.5,
        cash=30000.0,
    )
    # EL: 50000 + 8000 - (0.5*20000)=10000 -> 48000
    assert result["excessLiquidityAfter"] == pytest.approx(48000.0)
    assert result["deltaExcessLiquidity"]["buyLeveragedEtf"] == pytest.approx(-10000.0)
    # funding outflow = D + ETF value (cash-bought) = 2000 + 20000 = 22000
    assert result["fundingOutflow"] == pytest.approx(22000.0)
    assert result["surplus"] == pytest.approx(8000.0)


def test_roll_what_if_omits_funding_when_cash_not_supplied():
    result = calc.roll_what_if(
        excess_liquidity=50000.0, nlv=200000.0, mm_sp=8000.0, close_sp_debit=2000.0,
    )
    assert "surplus" not in result
    assert "canExecute" not in result
    assert "availableFundsAfter" not in result


def test_roll_what_if_level_can_flip_to_danger():
    result = calc.roll_what_if(
        excess_liquidity=30000.0, nlv=200000.0,
        mm_sp=0.0, close_sp_debit=0.0, open_call_premium=15000.0,
    )
    # 30000 - 15000 = 15000 -> cushion 7.5% < 10% danger
    assert result["levelBefore"] == "warning"  # 15% in [10,20)
    assert result["levelAfter"] == "danger"


def test_exposure_match_sizing_call_and_etf():
    # |contracts|=2, S=200, |delta_sp|=0.4 -> E_target = 2*100*200*0.4 = 16000
    result = calc.exposure_match_sizing(
        contracts=-2, underlying_price=200.0, delta_sp=-0.4,
        call_delta=0.5, etf_leverage=2.0, etf_price=20.0,
    )
    assert result["exposureTarget"] == pytest.approx(16000.0)
    assert result["callContracts"] == pytest.approx(16000.0 / (100 * 200 * 0.5))  # 1.6
    assert result["etfValue"] == pytest.approx(8000.0)
    assert result["etfShares"] == pytest.approx(400.0)


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
