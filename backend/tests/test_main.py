from fastapi.testclient import TestClient
from backend import main


def test_portfolio_endpoint_returns_503_when_gateway_unreachable(monkeypatch):
    def raise_connect(*a, **k):
        raise ConnectionRefusedError("no gateway")

    monkeypatch.setattr(main.ibkr_client, "connect", raise_connect)
    client = TestClient(main.app)
    resp = client.get("/api/portfolio")
    assert resp.status_code == 503
    assert "IB Gateway" in resp.json()["detail"]


def test_build_portfolio_response_shape():
    raw_positions = [
        {
            "label": "TSLA", "underlying": "TSLA", "type": "STK",
            "notional": 39284.0, "exposure": 39284.0, "discount": 0.0,
            "delta": 1.0, "iv": None,
        },
        {
            "label": "TSLA 200C Oct16", "underlying": "TSLA", "type": "COPT",
            "notional": 39284.0, "exposure": 38117.0, "discount": 0.0297,
            "delta": 0.970, "iv": 71.8,
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
