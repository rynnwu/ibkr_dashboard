import math
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from backend import main
from backend import config as config_module


def test_portfolio_endpoint_returns_503_when_gateway_unreachable_and_no_cache(monkeypatch):
    def raise_connect(*a, **k):
        raise ConnectionRefusedError("no gateway")

    monkeypatch.setattr(main.ibkr_client, "connect", raise_connect)
    monkeypatch.setattr(main.cache, "load_portfolio", lambda *a, **k: None)
    client = TestClient(main.app)
    resp = client.get("/api/portfolio")
    assert resp.status_code == 503
    assert "IB Gateway" in resp.json()["detail"]


def test_portfolio_endpoint_serves_cached_snapshot_when_gateway_unreachable(monkeypatch):
    def raise_connect(*a, **k):
        raise ConnectionRefusedError("no gateway")

    cached_payload = {"nlv": 123.0, "positions": [], "underlyings": [], "warnings": [], "stale": True, "cachedAt": "2026-06-21T08:00:00+08:00"}
    monkeypatch.setattr(main.ibkr_client, "connect", raise_connect)
    monkeypatch.setattr(main.cache, "load_portfolio", lambda *a, **k: cached_payload)
    client = TestClient(main.app)
    resp = client.get("/api/portfolio")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stale"] is True
    assert body["nlv"] == 123.0
    assert body["cachedAt"] == "2026-06-21T08:00:00+08:00"


def test_build_portfolio_response_shape():
    raw_positions = [
        {
            "label": "TSLA", "underlying": "TSLA", "type": "STK",
            "notional": 39284.0, "exposure": 39284.0, "discount": 0.0,
            "delta": 1.0, "iv": None, "quantity": 100,
        },
        {
            "label": "TSLA 200C Oct16", "underlying": "TSLA", "type": "COPT",
            "notional": 39284.0, "exposure": 38117.0, "discount": 0.0297,
            "delta": 0.970, "iv": 71.8, "quantity": 2,
        },
    ]
    icon_lookup = {"TSLA": ("icon_cache/TSLA.png", "#e8703a")}
    result = main.build_portfolio_response(
        positions=raw_positions, nlv=417833.63, icon_lookup=icon_lookup, warnings=[],
    )
    assert result["nlv"] == 417833.63
    assert result["positions"][0]["label"] == "TSLA"
    underlyings = {u["symbol"]: u for u in result["underlyings"]}
    assert underlyings["TSLA"]["notional"] == 78568.0
    assert underlyings["TSLA"]["color"] == "#e8703a"
    assert result["totalNotional"] == 78568.0
    assert "netDelta" in result
    assert result["warnings"] == []


def test_build_portfolio_response_icon_url_is_a_servable_web_path():
    positions = [
        {"label": "AAPL", "underlying": "AAPL", "type": "STK", "notional": 1000.0,
         "exposure": 1000.0, "discount": 0.0, "delta": 1.0, "iv": None, "quantity": 10},
    ]
    icon_lookup = {"AAPL": ("/some/absolute/filesystem/path/icon_cache/AAPL.png", "#ff0000")}
    result = main.build_portfolio_response(positions=positions, nlv=50000.0, icon_lookup=icon_lookup, warnings=[])
    assert result["underlyings"][0]["iconUrl"] == "/icons/AAPL.png"


def test_build_portfolio_response_icon_url_is_none_when_no_icon_lookup_entry():
    positions = [
        {"label": "ZZZZ", "underlying": "ZZZZ", "type": "STK", "notional": 500.0,
         "exposure": 500.0, "discount": 0.0, "delta": 1.0, "iv": None, "quantity": 5},
    ]
    result = main.build_portfolio_response(positions=positions, nlv=50000.0, icon_lookup={}, warnings=[])
    assert result["underlyings"][0]["iconUrl"] is None


def test_build_portfolio_response_greeks_card_accounts_for_quantity_and_short_sign():
    positions = [
        {
            "label": "TSLA 200P short", "underlying": "TSLA", "type": "POPT",
            "notional": 20000.0, "exposure": 8000.0, "discount": 0.6,
            "delta": -0.40, "theta": -0.05, "vega": 0.10, "iv": 50.0,
            "underlying_price": 200.0, "quantity": -2,  # short 2 puts
        },
    ]
    result = main.build_portfolio_response(positions=positions, nlv=100000.0, icon_lookup={}, warnings=[])
    # quantity(-2) * 100 * delta(-0.40) = +80 -> short put is bullish (positive delta-equivalent)
    assert result["netDelta"] == pytest.approx(80.0)
    # quantity(-2) * 100 * theta(-0.05) = +10 -> short option collects theta (positive)
    assert result["netTheta"] == pytest.approx(10.0)
    # quantity(-2) * 100 * vega(0.10) = -20 -> short option has negative vega exposure
    assert result["netVega"] == pytest.approx(-20.0)


def _fake_cfg(leveraged_etf_map=None, dividend_yield=None, risk_free_rate=0.0425):
    return config_module.Config(
        leveraged_etf_map=leveraged_etf_map or {},
        risk_free_rate=risk_free_rate,
        ib_gateway_host="127.0.0.1", ib_gateway_port=4001, ib_gateway_client_id=7,
        logo_api_provider="", logo_api_key="",
        _dividend_yield=dividend_yield or {},
    )


def test_position_to_record_plain_stock():
    contract = SimpleNamespace(secType="STK", symbol="AAPL")
    pos = SimpleNamespace(contract=contract, position=10)
    record = main._position_to_record(pos, _fake_cfg(), {"AAPL": 200.0}, {})
    assert record["type"] == "STK"
    assert record["underlying"] == "AAPL"
    assert record["notional"] == 2000.0
    assert record["exposure"] == 2000.0
    assert record["discount"] == 0.0
    assert record["delta"] == 1.0
    assert record["iv"] is None
    assert record["quantity"] == 10


def test_position_to_record_raises_on_nan_underlying_price():
    contract = SimpleNamespace(secType="STK", symbol="AAPL")
    pos = SimpleNamespace(contract=contract, position=10)
    with pytest.raises(ValueError):
        main._position_to_record(pos, _fake_cfg(), {"AAPL": math.nan}, {})


def test_position_to_record_option_raises_on_nan_underlying_price():
    contract = SimpleNamespace(
        secType="OPT", symbol="TSLA", strike=200.0, right="C",
        lastTradeDateOrContractMonth="20261016", conId=1,
    )
    pos = SimpleNamespace(contract=contract, position=1)
    with pytest.raises(ValueError):
        main._position_to_record(pos, _fake_cfg(), {"TSLA": math.nan}, {})


def test_position_to_record_leveraged_etf():
    contract = SimpleNamespace(secType="STK", symbol="TSLL")
    pos = SimpleNamespace(contract=contract, position=100)
    cfg = _fake_cfg(leveraged_etf_map={"TSLL": {"underlying": "TSLA", "multiplier": 2}})
    record = main._position_to_record(pos, cfg, {"TSLL": 20.0}, {})
    assert record["underlying"] == "TSLA"
    assert record["notional"] == 4000.0  # 100 * 20.0 * 2
    assert record["exposure"] == 4000.0
    assert record["discount"] == 0.0
    assert record["delta"] == 2.0
    assert record["quantity"] == 100


def test_position_to_record_option_uses_model_greeks_when_available():
    contract = SimpleNamespace(
        secType="OPT", symbol="TSLA", strike=200.0, right="C",
        lastTradeDateOrContractMonth="20261016", conId=1,
    )
    pos = SimpleNamespace(contract=contract, position=1)
    fake_ticker = SimpleNamespace(
        modelGreeks=SimpleNamespace(delta=0.6, theta=-0.5, vega=0.3, impliedVol=0.45),
        marketPrice=lambda: 10.0,
    )
    record = main._position_to_record(pos, _fake_cfg(), {"TSLA": 210.0}, {1: fake_ticker})
    assert record["type"] == "COPT"
    assert record["delta"] == 0.6
    assert record["theta"] == -0.5
    assert record["vega"] == 0.3
    assert record["iv"] == 45.0
    assert record["notional"] == 21000.0  # 1 * 100 * 210.0
    assert record["exposure"] == 21000.0 * 0.6
    assert record["quantity"] == 1


def test_position_to_record_option_falls_back_to_black_scholes_when_no_model_greeks():
    from datetime import date, timedelta
    expiry_str = (date.today() + timedelta(days=30)).strftime("%Y%m%d")
    contract = SimpleNamespace(
        secType="OPT", symbol="TSLA", strike=200.0, right="C",
        lastTradeDateOrContractMonth=expiry_str, conId=1,
    )
    pos = SimpleNamespace(contract=contract, position=1)
    fake_ticker = SimpleNamespace(modelGreeks=None, marketPrice=lambda: 15.0)
    record = main._position_to_record(pos, _fake_cfg(), {"TSLA": 210.0}, {1: fake_ticker})
    assert record["type"] == "COPT"
    assert record["iv"] is not None
    assert 0.0 < record["delta"] < 1.0
    assert record["quantity"] == 1


def test_position_to_record_raises_on_nan_option_mark_price():
    contract = SimpleNamespace(
        secType="OPT", symbol="TSLA", strike=200.0, right="C",
        lastTradeDateOrContractMonth="20261016", localSymbol="TSLA  261016C00200000", conId=1,
    )
    pos = SimpleNamespace(contract=contract, position=1)
    # Neither a live/delayed mark nor a previous close is available.
    fake_ticker = SimpleNamespace(modelGreeks=None, marketPrice=lambda: math.nan, close=math.nan)
    with pytest.raises(ValueError):
        main._position_to_record(pos, _fake_cfg(), {"TSLA": 210.0}, {1: fake_ticker})


def test_position_to_record_option_falls_back_to_previous_close_for_mark():
    # No live/delayed quote (marketPrice NaN), but the previous close is
    # available — the option should still be priced off that close via the
    # Black-Scholes fallback rather than being dropped.
    from datetime import date, timedelta
    expiry_str = (date.today() + timedelta(days=30)).strftime("%Y%m%d")
    contract = SimpleNamespace(
        secType="OPT", symbol="TSLA", strike=200.0, right="C",
        lastTradeDateOrContractMonth=expiry_str, localSymbol="TSLA  fake", conId=1,
    )
    pos = SimpleNamespace(contract=contract, position=1)
    fake_ticker = SimpleNamespace(modelGreeks=None, marketPrice=lambda: math.nan, close=15.0)
    record = main._position_to_record(pos, _fake_cfg(), {"TSLA": 210.0}, {1: fake_ticker})
    assert record["type"] == "COPT"
    assert record["iv"] is not None
    assert 0.0 < record["delta"] < 1.0


def test_position_to_record_put_option_type_is_popt():
    contract = SimpleNamespace(
        secType="OPT", symbol="TSLA", strike=200.0, right="P",
        lastTradeDateOrContractMonth="20261016", conId=1,
    )
    pos = SimpleNamespace(contract=contract, position=1)
    fake_ticker = SimpleNamespace(
        modelGreeks=SimpleNamespace(delta=-0.4, theta=-0.3, vega=0.2, impliedVol=0.5),
        marketPrice=lambda: 8.0,
    )
    record = main._position_to_record(pos, _fake_cfg(), {"TSLA": 210.0}, {1: fake_ticker})
    assert record["type"] == "POPT"
    assert record["delta"] == -0.4
    assert record["quantity"] == 1


def test_years_to_expiry_future_date_is_roughly_expected_fraction():
    from datetime import date, timedelta
    future = date.today() + timedelta(days=365)
    expiry_str = future.strftime("%Y%m%d")
    fraction = main._years_to_expiry(expiry_str)
    assert 0.99 <= fraction <= 1.01


def test_years_to_expiry_past_or_today_is_floored_to_one_day():
    from datetime import date
    today_str = date.today().strftime("%Y%m%d")
    fraction = main._years_to_expiry(today_str)
    assert fraction == 1 / 365.0
