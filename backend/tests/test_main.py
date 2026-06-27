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


def test_roll_what_if_endpoint_uses_regt_fallback_and_returns_estimate():
    client = TestClient(main.app)
    resp = client.post("/api/roll-what-if", json={
        "excessLiquidity": 50000.0, "nlv": 200000.0,
        "cash": 10000.0, "availableFunds": 20000.0,
        "spContracts": 2, "spUnderlyingPrice": 200.0, "spStrike": 180.0, "spPutMark": 2.0,
        "openCallPremium": 3000.0,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["mmSpAuto"] is True
    # Reg T MM_SP = 2*100*(max(40-20,18)+2) = 4400; D = 2*100*2 = 400
    assert body["mmSp"] == pytest.approx(4400.0)
    assert body["closeSpDebit"] == pytest.approx(400.0)
    assert body["excessLiquidityAfter"] == pytest.approx(50000.0 + 4400.0 - 3000.0)
    # surplus = cash - (D + premium) = 10000 - (400 + 3000)
    assert body["surplus"] == pytest.approx(6600.0)
    assert body["canExecute"] is True


def test_roll_what_if_endpoint_honors_mm_sp_override():
    client = TestClient(main.app)
    resp = client.post("/api/roll-what-if", json={
        "excessLiquidity": 50000.0, "nlv": 200000.0,
        "spContracts": 1, "spUnderlyingPrice": 200.0, "spStrike": 180.0, "spPutMark": 2.0,
        "mmSpOverride": 12345.0,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["mmSpAuto"] is False
    assert body["mmSp"] == 12345.0


def test_price_option_endpoint_matches_black_scholes():
    client = TestClient(main.app)
    resp = client.post("/api/price-option", json={
        "underlyingPrice": 100.0, "strike": 100.0, "daysToExpiry": 365,
        "right": "C", "iv": 20.0,
    })
    assert resp.status_code == 200
    body = resp.json()
    # S=K=100, T=1y, r=config 4.25%, q=0, sigma=20% -> BS call ~10.06
    assert body["mark"] == pytest.approx(10.06, abs=0.05)
    assert 0.0 < body["delta"] < 1.0
    assert body["iv"] == 20.0


def test_price_option_endpoint_put_delta_is_negative():
    client = TestClient(main.app)
    resp = client.post("/api/price-option", json={
        "underlyingPrice": 200.0, "strike": 180.0, "daysToExpiry": 30,
        "right": "P", "iv": 45.0,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["mark"] > 0.0
    assert -1.0 < body["delta"] < 0.0


def test_suggest_call_endpoint_floors_delta_at_min_and_prices_strike():
    client = TestClient(main.app)
    # SP delta 0.70 magnitude but minDelta 0.85 -> target 0.85
    resp = client.post("/api/suggest-call", json={
        "underlyingPrice": 250.0, "shortPutDelta": -0.70, "iv": 45.0,
        "daysToExpiry": 180, "minDelta": 0.85,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["targetDelta"] == pytest.approx(0.85)
    assert body["daysToExpiry"] == 180
    assert body["strike"] < 250.0  # ITM call
    assert body["mark"] > 0.0
    # strike is rounded to a whole dollar, so the priced delta is near (not exactly) target
    assert body["delta"] == pytest.approx(0.85, abs=0.02)


def test_suggest_call_endpoint_uses_sp_delta_when_above_min():
    client = TestClient(main.app)
    resp = client.post("/api/suggest-call", json={
        "underlyingPrice": 100.0, "shortPutDelta": -0.92, "iv": 50.0,
    })
    assert resp.status_code == 200
    assert resp.json()["targetDelta"] == pytest.approx(0.92)


def test_position_to_record_option_carries_days_to_expiry():
    from datetime import date, timedelta
    expiry_str = (date.today() + timedelta(days=30)).strftime("%Y%m%d")
    contract = SimpleNamespace(
        secType="OPT", symbol="TSLA", strike=200.0, right="P",
        lastTradeDateOrContractMonth=expiry_str, conId=1,
    )
    pos = SimpleNamespace(contract=contract, position=-2)
    fake_ticker = SimpleNamespace(
        modelGreeks=SimpleNamespace(delta=-0.4, theta=-0.3, vega=0.2, impliedVol=0.5),
        marketPrice=lambda: 8.0,
    )
    record = main._position_to_record(pos, _fake_cfg(), {"TSLA": 210.0}, {1: fake_ticker})
    assert record["strike"] == 200.0
    assert record["mark"] == 8.0
    assert record["daysToExpiry"] == 30


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
    assert result["margin"] is None  # no margin block passed


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


def test_build_margin_returns_none_without_maint_margin():
    # A summary missing MaintMarginReq (e.g. cash account) yields no margin block.
    assert main._build_margin({"NetLiquidation": 100000.0}, 100000.0, _fake_cfg()) is None


def test_build_margin_uses_config_thresholds_and_carries_lookahead():
    account_values = {
        "NetLiquidation": 100000.0,
        "MaintMarginReq": 60000.0,
        "ExcessLiquidity": 8000.0,  # cushion 8% -> below default 10% danger
        "LookAheadMaintMarginReq": 65000.0,
        "LookAheadExcessLiquidity": 3000.0,
        "TotalCashValue": 5000.0,
        "AvailableFunds": -2000.0,
    }
    margin = main._build_margin(account_values, 100000.0, _fake_cfg())
    assert margin["level"] == "danger"
    assert margin["excessLiquidity"] == 8000.0
    assert margin["cushion"] == pytest.approx(0.08)
    assert margin["lookAheadExcessLiquidity"] == 3000.0
    assert margin["cash"] == 5000.0
    assert margin["availableFunds"] == -2000.0
    assert margin["canOpenNew"] is False  # funding axis, separate from level


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


def test_spx_hedge_endpoint_model_fallback_when_no_cache(monkeypatch):
    # No SPX cache this session -> resolve off the client-supplied spxLevel and
    # model-price the three proposals (no IBKR I/O in this endpoint).
    monkeypatch.setattr(main.spx_cache, "load_spx", lambda *a, **k: None)
    client = TestClient(main.app)
    resp = client.post("/api/spx-hedge", json={
        "netExposure": 1_000_000.0, "nlv": 500_000.0, "spxLevel": 5000.0,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "model"
    assert body["spxLevel"] == 5000.0
    assert body["targetLeverage"] == 1.0
    assert body["contracts"] > 0 and body["contracts"] == round(body["contracts"])
    assert body["leverageBefore"] == pytest.approx(2.0)

    kinds = [p["kind"] for p in body["proposals"]]
    assert kinds == ["long_put", "vertical", "seagull"]
    by_kind = {p["kind"]: p for p in body["proposals"]}
    # long put sized to bring leverage under the 1.0x target
    assert by_kind["long_put"]["leverageAfter"] < 1.0
    # vertical (a debit spread) is cheaper than the outright long put...
    assert by_kind["vertical"]["cost"] < by_kind["long_put"]["cost"]
    # ...and the seagull's short call credit makes it cheaper still (≈ zero-cost)
    assert abs(by_kind["seagull"]["cost"]) < by_kind["vertical"]["cost"]
    # seagull legs: long put / short put / short call
    sea_legs = by_kind["seagull"]["legs"]
    assert [(l["right"], l["contracts"] > 0) for l in sea_legs] == [("P", True), ("P", False), ("C", False)]
    assert by_kind["seagull"]["upsideCap"] > body["spxLevel"]


def test_spx_hedge_endpoint_uses_cached_spx_market(monkeypatch):
    # A populated SPX cache (from the last live portfolio refresh) is used without
    # any IBKR connection: level/strikes/iv come straight from it.
    fake_cache = {
        "spxLevel": 5200.0,
        "expirations": ["20260710", "20260717", "20260814"],
        "strikes": [float(k) for k in range(4000, 6001, 25)],
        "iv": 0.18,
        "source": "live",
        "cachedAt": "2026-06-27T09:30:00+08:00",
    }
    monkeypatch.setattr(main.spx_cache, "load_spx", lambda *a, **k: fake_cache)
    client = TestClient(main.app)
    resp = client.post("/api/spx-hedge", json={"netExposure": 1_000_000.0, "nlv": 500_000.0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "live"
    assert body["spxLevel"] == 5200.0
    assert body["cachedAt"] == "2026-06-27T09:30:00+08:00"
    assert body["iv"] == pytest.approx(18.0)  # cached 0.18 -> percent
    # strikes snapped to the cached 25-pt chain grid
    assert body["longPutStrike"] % 25 == 0


def test_spx_hedge_endpoint_503_when_no_cache_and_no_fallback(monkeypatch):
    monkeypatch.setattr(main.spx_cache, "load_spx", lambda *a, **k: None)
    client = TestClient(main.app)
    resp = client.post("/api/spx-hedge", json={"netExposure": 1_000_000.0, "nlv": 500_000.0})
    assert resp.status_code == 503
    assert "SPX" in resp.json()["detail"]


def test_spx_hedge_endpoint_echoes_spx_symbol_by_default(monkeypatch):
    # Absent `symbol` behaves as "SPX" and is echoed back.
    monkeypatch.setattr(main.spx_cache, "load_spx", lambda *a, **k: None)
    client = TestClient(main.app)
    resp = client.post("/api/spx-hedge", json={
        "netExposure": 1_000_000.0, "nlv": 500_000.0, "spxLevel": 5000.0,
    })
    assert resp.status_code == 200
    assert resp.json()["symbol"] == "SPX"


def test_spx_hedge_endpoint_explicit_spx_symbol_uses_cache(monkeypatch):
    # symbol="SPX" keeps the exact SPX behavior (resolve from cache, ignore `level`).
    fake_cache = {
        "spxLevel": 5200.0, "expirations": [], "strikes": [],
        "iv": 0.18, "source": "live", "cachedAt": "2026-06-27T09:30:00+08:00",
    }
    monkeypatch.setattr(main.spx_cache, "load_spx", lambda *a, **k: fake_cache)
    client = TestClient(main.app)
    resp = client.post("/api/spx-hedge", json={
        "netExposure": 1_000_000.0, "nlv": 500_000.0, "symbol": "SPX",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "SPX"
    assert body["source"] == "live"
    assert body["spxLevel"] == 5200.0


def test_spx_hedge_endpoint_etf_symbol_model_prices_off_request_level(monkeypatch):
    # A non-SPX ETF builds the market straight from the request (model pricing) and
    # does NOT touch the SPX cache; `level` becomes the spot, `dividendYield` the q.
    def _no_cache(*a, **k):
        raise AssertionError("ETF hedge must not read the SPX cache")

    monkeypatch.setattr(main.spx_cache, "load_spx", _no_cache)
    client = TestClient(main.app)
    resp = client.post("/api/spx-hedge", json={
        "netExposure": 600_000.0, "nlv": 300_000.0,
        "symbol": "SMH", "level": 250.0, "dividendYield": 0.0,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "SMH"
    assert body["source"] == "model"
    assert body["cachedAt"] is None
    assert body["spxLevel"] == 250.0  # the ETF spot is the underlying level
    assert body["leverageBefore"] == pytest.approx(2.0)
    assert body["contracts"] > 0
    assert [p["kind"] for p in body["proposals"]] == ["long_put", "vertical", "seagull"]


def test_spx_hedge_endpoint_etf_symbol_503_without_level():
    # A non-SPX ETF needs a spot price; missing/≤0 level → friendly 503 (model mode).
    client = TestClient(main.app)
    resp = client.post("/api/spx-hedge", json={
        "netExposure": 600_000.0, "nlv": 300_000.0, "symbol": "SMH",
    })
    assert resp.status_code == 503
    assert "現價" in resp.json()["detail"]


def test_build_portfolio_response_carries_beta_weighted_fields():
    positions = [
        {"label": "NVDA", "underlying": "NVDA", "type": "STK", "notional": 50000.0,
         "exposure": 50000.0, "discount": 0.0, "delta": 1.0, "iv": None, "quantity": 100},
    ]
    result = main.build_portfolio_response(
        positions=positions, nlv=200000.0, icon_lookup={}, warnings=[],
        betas={"NVDA": 2.0}, spx_level=5000.0, hedge_warning_leverage=1.5,
    )
    assert result["netBetaWeightedExposure"] == pytest.approx(100000.0)  # 50000 * 2.0
    assert result["betaWeightedLeverage"] == pytest.approx(0.5)
    assert result["spxLevel"] == 5000.0
    assert result["spxHedgeWarningLeverage"] == 1.5
    assert result["underlyings"][0]["beta"] == 2.0


def test_resolve_betas_prefers_config_override_then_ibkr_then_default():
    cfg = _fake_cfg()
    cfg._beta_overrides = {"AAA": 1.5}
    betas, defaulted = main._resolve_betas({"AAA", "BBB", "CCC"}, {"BBB": 1.2}, cfg)
    assert betas["AAA"] == 1.5   # config override wins
    assert betas["BBB"] == 1.2   # IBKR fundamental
    assert "CCC" not in betas    # nothing -> default later
    assert defaulted == ["CCC"]
