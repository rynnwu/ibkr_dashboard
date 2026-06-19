# IBKR 持倉名義／曝險圓餅圖儀表板 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the manual LLM-driven workflow (`examples/Prompt of notional pie chart.md`) with a standalone Python backend + React frontend that reads live IBKR positions/prices via `ib_insync` and renders the existing `examples/portfolio pie.tsx` dashboard with real data, icons, and color-synced charts.

**Architecture:** Python `FastAPI` backend connects to a locally-running IB Gateway (`ib_insync`, port 4001, IB API mode), computes notional/exposure/discount/Greeks per position (native `modelGreeks` first, Black-Scholes fallback), fetches/caches per-symbol icons + dominant colors, and exposes one `GET /api/portfolio` endpoint. A Vite + React + TypeScript frontend (ported from `examples/portfolio pie.tsx`) fetches that endpoint on load and on a manual "refresh" click — no realtime streaming.

**Tech Stack:** Python 3.11+, `ib_insync`, `FastAPI`, `scipy`, `Pillow`, `requests`, `pytest`; Node 20+, Vite, React, TypeScript.

**Reference spec:** `docs/superpowers/specs/2026-06-19-ibkr-portfolio-pie-design.md`

---

## File Structure

```
backend/
  requirements.txt
  config.json
  config.py          # load/validate config.json
  calc.py            # notional/exposure/discount, Black-Scholes, aggregation — pure functions
  icons.py           # logo fetch/cache/dominant-color/text-fallback
  ibkr_client.py     # thin ib_insync wrapper (connect, positions, NLV, market data)
  main.py            # FastAPI app, GET /api/portfolio
  icon_cache/         # created at runtime, gitignored
  tests/
    test_calc.py
    test_config.py
    test_icons.py
    test_main.py
frontend/
  package.json, vite.config.ts, tsconfig.json (scaffolded)
  src/
    types.ts
    api.ts
    components/DonutChart.tsx
    App.tsx
    main.tsx
README.md            # setup + run instructions
```

---

## Task 1: Backend scaffold

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/__init__.py` (empty, makes it a package for pytest imports)

- [ ] **Step 1: Create the backend directory and dependency list**

```
ib_insync==0.9.86
fastapi==0.115.0
uvicorn==0.30.6
scipy==1.14.1
Pillow==10.4.0
requests==2.32.3
pytest==8.3.3
httpx==0.27.2
```

Write this to `backend/requirements.txt`.

- [ ] **Step 2: Create empty `backend/__init__.py`**

- [ ] **Step 3: Set up a virtualenv and install**

Run:
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
Expected: all packages install with no errors.

- [ ] **Step 4: Commit**

```bash
git add backend/requirements.txt backend/__init__.py
git commit -m "Scaffold backend package and dependencies"
```

---

## Task 2: calc.py — position-level notional/exposure/discount

**Files:**
- Create: `backend/calc.py`
- Test: `backend/tests/test_calc.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_calc.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_calc.py -v`
Expected: FAIL with `ModuleNotFoundError` or `AttributeError: module 'calc' has no attribute 'stock_notional'`

- [ ] **Step 3: Implement**

```python
# backend/calc.py
"""Pure functions for position-level and portfolio-level risk math.

No I/O here — everything takes plain numbers/dicts so it can be unit
tested without a live IB Gateway connection.
"""


def stock_notional(quantity: float, price: float) -> float:
    return abs(quantity) * price


def leveraged_etf_notional(quantity: float, price: float, multiplier: float) -> float:
    return abs(quantity) * price * multiplier


def option_notional(contracts: float, underlying_price: float, contract_size: float = 100) -> float:
    return abs(contracts) * contract_size * underlying_price


def option_exposure(notional: float, delta: float) -> float:
    return notional * abs(delta)


def discount(notional: float, exposure: float) -> float:
    if notional == 0:
        return 0.0
    return 1.0 - exposure / notional
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_calc.py -v`
Expected: all 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/calc.py backend/tests/test_calc.py
git commit -m "Add position-level notional/exposure/discount math"
```

---

## Task 3: calc.py — Black-Scholes pricing, implied vol, Greeks

**Files:**
- Modify: `backend/calc.py`
- Test: `backend/tests/test_calc.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_calc.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_calc.py -v -k "bs_ or implied_vol"`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Implement**

Append to `backend/calc.py`:

```python
import math
from scipy.stats import norm


def _d1_d2(S: float, K: float, T: float, r: float, q: float, sigma: float) -> tuple[float, float]:
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return d1, d2


def bs_price(S: float, K: float, T: float, r: float, q: float, sigma: float, right: str) -> float:
    d1, d2 = _d1_d2(S, K, T, r, q, sigma)
    if right == "C":
        return S * math.exp(-q * T) * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * math.exp(-q * T) * norm.cdf(-d1)


def implied_vol(
    mark_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    q: float,
    right: str,
    lo: float = 1e-4,
    hi: float = 5.0,
    tol: float = 1e-6,
    max_iter: int = 100,
) -> float:
    mid = (lo + hi) / 2
    for _ in range(max_iter):
        mid = (lo + hi) / 2
        price = bs_price(S, K, T, r, q, mid, right)
        if abs(price - mark_price) < tol:
            break
        if price > mark_price:
            hi = mid
        else:
            lo = mid
    return mid


def bs_greeks(S: float, K: float, T: float, r: float, q: float, sigma: float, right: str) -> dict:
    d1, d2 = _d1_d2(S, K, T, r, q, sigma)
    pdf_d1 = norm.pdf(d1)
    if right == "C":
        delta = math.exp(-q * T) * norm.cdf(d1)
        theta_annual = (
            -S * math.exp(-q * T) * pdf_d1 * sigma / (2 * math.sqrt(T))
            - r * K * math.exp(-r * T) * norm.cdf(d2)
            + q * S * math.exp(-q * T) * norm.cdf(d1)
        )
    else:
        delta = -math.exp(-q * T) * norm.cdf(-d1)
        theta_annual = (
            -S * math.exp(-q * T) * pdf_d1 * sigma / (2 * math.sqrt(T))
            + r * K * math.exp(-r * T) * norm.cdf(-d2)
            - q * S * math.exp(-q * T) * norm.cdf(-d1)
        )
    vega_full = S * math.exp(-q * T) * pdf_d1 * math.sqrt(T)
    return {
        "delta": delta,
        "theta": theta_annual / 365.0,  # per calendar day
        "vega": vega_full / 100.0,      # per 1 vol point (1%)
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_calc.py -v`
Expected: all tests PASS (13 total so far)

- [ ] **Step 5: Commit**

```bash
git add backend/calc.py backend/tests/test_calc.py
git commit -m "Add Black-Scholes pricing, implied-vol bisection, and Greeks"
```

---

## Task 4: calc.py — aggregation by underlying and portfolio metrics

**Files:**
- Modify: `backend/calc.py`
- Test: `backend/tests/test_calc.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_calc.py`:

```python
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


def test_greeks_card_sums_option_positions_only():
    option_positions = [
        {"delta_shares": 100.0, "theta": 5.0, "vega": -2.0},
        {"delta_shares": -30.0, "theta": 1.0, "vega": 3.0},
    ]
    result = calc.greeks_card(option_positions)
    assert result["net_delta"] == 70.0
    assert result["net_theta"] == 6.0
    assert result["net_vega"] == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_calc.py -v -k "aggregate or leverage or greeks_card"`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Implement**

Append to `backend/calc.py`:

```python
def aggregate_by_underlying(positions: list[dict]) -> list[dict]:
    totals: dict[str, dict] = {}
    for pos in positions:
        row = totals.setdefault(pos["underlying"], {"underlying": pos["underlying"], "notional": 0.0, "exposure": 0.0})
        row["notional"] += pos["notional"]
        row["exposure"] += pos["exposure"]
    return list(totals.values())


def portfolio_leverage(total_notional: float, total_exposure: float, nlv: float) -> dict:
    return {
        "notional_leverage": total_notional / nlv,
        "exposure_leverage": total_exposure / nlv,
    }


def greeks_card(option_positions: list[dict]) -> dict:
    return {
        "net_delta": sum(p["delta_shares"] for p in option_positions),
        "net_theta": sum(p["theta"] for p in option_positions),
        "net_vega": sum(p["vega"] for p in option_positions),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_calc.py -v`
Expected: all tests PASS (16 total so far)

- [ ] **Step 5: Commit**

```bash
git add backend/calc.py backend/tests/test_calc.py
git commit -m "Add underlying aggregation and portfolio-level leverage/Greeks metrics"
```

---

## Task 5: config.py — load and validate config.json

**Files:**
- Create: `backend/config.json`
- Create: `backend/config.py`
- Test: `backend/tests/test_config.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_config.py
import json
import pytest
from backend import config


def test_load_config_reads_known_keys(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "leveraged_etf_map": {"TSLL": {"underlying": "TSLA", "multiplier": 2}},
        "dividend_yield": {"GOOG": 0.005},
        "risk_free_rate": 0.0425,
        "ib_gateway": {"host": "127.0.0.1", "port": 4001, "client_id": 7},
        "logo_api": {"provider": "eodhd", "api_key": "abc"},
    }))
    cfg = config.load_config(cfg_path)
    assert cfg.risk_free_rate == 0.0425
    assert cfg.ib_gateway_host == "127.0.0.1"
    assert cfg.ib_gateway_port == 4001
    assert cfg.ib_gateway_client_id == 7
    assert cfg.leveraged_etf_map["TSLL"] == {"underlying": "TSLA", "multiplier": 2}
    assert cfg.logo_api_key == "abc"


def test_dividend_yield_defaults_to_zero_for_unknown_symbol(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "leveraged_etf_map": {},
        "dividend_yield": {"GOOG": 0.005},
        "risk_free_rate": 0.0425,
        "ib_gateway": {"host": "127.0.0.1", "port": 4001, "client_id": 7},
        "logo_api": {"provider": "eodhd", "api_key": ""},
    }))
    cfg = config.load_config(cfg_path)
    assert cfg.dividend_yield_for("GOOG") == 0.005
    assert cfg.dividend_yield_for("AAPL") == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# backend/config.py
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    leveraged_etf_map: dict
    risk_free_rate: float
    ib_gateway_host: str
    ib_gateway_port: int
    ib_gateway_client_id: int
    logo_api_provider: str
    logo_api_key: str
    _dividend_yield: dict = field(default_factory=dict)

    def dividend_yield_for(self, symbol: str) -> float:
        return self._dividend_yield.get(symbol, 0.0)


def load_config(path: Path) -> Config:
    raw = json.loads(Path(path).read_text())
    gateway = raw["ib_gateway"]
    logo = raw["logo_api"]
    return Config(
        leveraged_etf_map=raw.get("leveraged_etf_map", {}),
        risk_free_rate=raw["risk_free_rate"],
        ib_gateway_host=gateway["host"],
        ib_gateway_port=gateway["port"],
        ib_gateway_client_id=gateway["client_id"],
        logo_api_provider=logo.get("provider", ""),
        logo_api_key=logo.get("api_key", ""),
        _dividend_yield=raw.get("dividend_yield", {}),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_config.py -v`
Expected: both tests PASS

- [ ] **Step 5: Create the real `backend/config.json`**

```json
{
  "leveraged_etf_map": {
    "TSLL": {"underlying": "TSLA", "multiplier": 2},
    "NVDL": {"underlying": "NVDA", "multiplier": 2},
    "MSFU": {"underlying": "MSFT", "multiplier": 2},
    "METU": {"underlying": "META", "multiplier": 2}
  },
  "dividend_yield": {
    "GOOG": 0.005,
    "MU": 0.004,
    "TSM": 0.012
  },
  "risk_free_rate": 0.0425,
  "ib_gateway": {"host": "127.0.0.1", "port": 4001, "client_id": 7},
  "logo_api": {"provider": "eodhd", "api_key": ""}
}
```

- [ ] **Step 6: Commit**

```bash
git add backend/config.py backend/config.json backend/tests/test_config.py
git commit -m "Add config.json loading with dividend-yield default fallback"
```

---

## Task 6: icons.py — color helpers (no network)

**Files:**
- Create: `backend/icons.py`
- Test: `backend/tests/test_icons.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_icons.py
import io
import re
from PIL import Image
from backend import icons


def test_hash_color_is_deterministic():
    assert icons.hash_color("TSLA") == icons.hash_color("TSLA")


def test_hash_color_format_is_hex():
    assert re.fullmatch(r"#[0-9a-f]{6}", icons.hash_color("TSLA"))


def test_hash_color_differs_for_different_symbols():
    assert icons.hash_color("TSLA") != icons.hash_color("GOOG")


def test_extract_dominant_color_on_solid_red_image():
    img = Image.new("RGB", (32, 32), (255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    color = icons.extract_dominant_color(buf.getvalue())
    assert color == "#ff0000"


def test_generate_text_fallback_icon_is_valid_png():
    png_bytes = icons.generate_text_fallback_icon("TSLA", "#336699")
    img = Image.open(io.BytesIO(png_bytes))
    assert img.format == "PNG"
    assert img.size == (64, 64)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_icons.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# backend/icons.py
"""Per-symbol icon fetch/cache and color derivation.

Network calls go through an injectable `getter` so tests never hit the
real logo API. See get_icon_and_color() for the orchestration entrypoint
used by main.py.
"""
import hashlib
import io
import json
from pathlib import Path

import requests
from PIL import Image, ImageDraw

CACHE_DIR = Path(__file__).parent / "icon_cache"
LOGO_URL_TEMPLATE = "https://eodhd.com/img/logos/US/{symbol}.png"


def hash_color(symbol: str) -> str:
    digest = hashlib.sha256(symbol.encode()).hexdigest()
    return f"#{digest[:6]}"


def extract_dominant_color(image_bytes: bytes) -> str:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    r, g, b = img.resize((1, 1)).getpixel((0, 0))
    return f"#{r:02x}{g:02x}{b:02x}"


def generate_text_fallback_icon(symbol: str, color: str) -> bytes:
    size = 64
    img = Image.new("RGB", (size, size), color)
    draw = ImageDraw.Draw(img)
    text = symbol[:4].upper()
    bbox = draw.textbbox((0, 0), text)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - text_w) / 2, (size - text_h) / 2), text, fill="#ffffff")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_icons.py -v`
Expected: all 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/icons.py backend/tests/test_icons.py
git commit -m "Add deterministic fallback color and dominant-color extraction"
```

---

## Task 7: icons.py — fetch + cache orchestration (network, injectable)

**Files:**
- Modify: `backend/icons.py`
- Test: `backend/tests/test_icons.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_icons.py`:

```python
class _FakeResponse:
    def __init__(self, status_code, content=b"", content_type="image/png"):
        self.status_code = status_code
        self.content = content
        self.headers = {"content-type": content_type}


def _solid_png(color=(0, 255, 0)):
    img = Image.new("RGB", (8, 8), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_fetch_logo_bytes_returns_none_without_api_key():
    assert icons.fetch_logo_bytes("TSLA", api_key="", getter=lambda *a, **k: _FakeResponse(200)) is None


def test_fetch_logo_bytes_returns_image_on_200(monkeypatch):
    png = _solid_png()
    result = icons.fetch_logo_bytes("TSLA", api_key="key", getter=lambda *a, **k: _FakeResponse(200, png))
    assert result == png


def test_fetch_logo_bytes_returns_none_on_404():
    result = icons.fetch_logo_bytes("ZZZZ", api_key="key", getter=lambda *a, **k: _FakeResponse(404))
    assert result is None


def test_get_icon_and_color_uses_fetched_logo_when_available(tmp_path):
    png = _solid_png((0, 255, 0))
    calls = {"n": 0}

    def fake_getter(*a, **k):
        calls["n"] += 1
        return _FakeResponse(200, png)

    path, color = icons.get_icon_and_color("NVDA", api_key="key", cache_dir=tmp_path, getter=fake_getter)
    assert color == "#00ff00"
    assert Path(path).exists()
    assert calls["n"] == 1


def test_get_icon_and_color_caches_and_does_not_refetch(tmp_path):
    png = _solid_png((0, 0, 255))
    calls = {"n": 0}

    def fake_getter(*a, **k):
        calls["n"] += 1
        return _FakeResponse(200, png)

    icons.get_icon_and_color("META", api_key="key", cache_dir=tmp_path, getter=fake_getter)
    icons.get_icon_and_color("META", api_key="key", cache_dir=tmp_path, getter=fake_getter)
    assert calls["n"] == 1


def test_get_icon_and_color_falls_back_to_text_icon_when_fetch_fails(tmp_path):
    path, color = icons.get_icon_and_color(
        "ZZZZ", api_key="key", cache_dir=tmp_path, getter=lambda *a, **k: _FakeResponse(404)
    )
    assert color == icons.hash_color("ZZZZ")
    assert Path(path).exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_icons.py -v -k "fetch_logo or get_icon_and_color"`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Implement**

Append to `backend/icons.py`:

```python
def fetch_logo_bytes(symbol: str, api_key: str, getter=requests.get) -> bytes | None:
    if not api_key:
        return None
    try:
        resp = getter(LOGO_URL_TEMPLATE.format(symbol=symbol), params={"api_token": api_key}, timeout=5)
    except requests.RequestException:
        return None
    if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image"):
        return resp.content
    return None


def get_icon_and_color(
    symbol: str,
    api_key: str,
    cache_dir: Path = CACHE_DIR,
    getter=requests.get,
) -> tuple[str, str]:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    icon_path = cache_dir / f"{symbol}.png"
    colors_path = cache_dir / "colors.json"
    colors = json.loads(colors_path.read_text()) if colors_path.exists() else {}

    if icon_path.exists() and symbol in colors:
        return str(icon_path), colors[symbol]

    logo_bytes = fetch_logo_bytes(symbol, api_key, getter)
    if logo_bytes:
        color = extract_dominant_color(logo_bytes)
        icon_path.write_bytes(logo_bytes)
    else:
        color = hash_color(symbol)
        icon_path.write_bytes(generate_text_fallback_icon(symbol, color))

    colors[symbol] = color
    colors_path.write_text(json.dumps(colors))
    return str(icon_path), color
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_icons.py -v`
Expected: all 11 tests PASS

- [ ] **Step 5: Note on the logo provider**

`LOGO_URL_TEMPLATE` points at `eodhd.com`'s public logo path. Verify it still
returns images for a couple of real tickers (`curl -I https://eodhd.com/img/logos/US/AAPL.png`)
before relying on it end-to-end; if it has changed or requires a different
auth scheme, update `LOGO_URL_TEMPLATE` and the `params` in `fetch_logo_bytes`
accordingly — the rest of the pipeline (cache, color extraction, fallback)
does not need to change.

- [ ] **Step 6: Commit**

```bash
git add backend/icons.py backend/tests/test_icons.py
git commit -m "Add logo fetch-and-cache orchestration with text-icon fallback"
```

---

## Task 8: ibkr_client.py — thin ib_insync wrapper

**Files:**
- Create: `backend/ibkr_client.py`

No automated tests — this module only wraps `ib_insync` calls against a live
IB Gateway and is verified manually in Task 11. Keep it minimal so there is
little logic here to get wrong.

- [ ] **Step 1: Implement**

```python
# backend/ibkr_client.py
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
```

- [ ] **Step 2: Commit**

```bash
git add backend/ibkr_client.py
git commit -m "Add thin ib_insync wrapper for positions, NLV, and market data"
```

---

## Task 9: main.py — FastAPI app and GET /api/portfolio

**Files:**
- Create: `backend/main.py`
- Test: `backend/tests/test_main.py`

This task wires `ibkr_client` + `calc` + `icons` + `config` together. The
endpoint logic itself (`build_portfolio_response`) is a separate, testable
function that takes already-fetched raw data — `main.py`'s route handler is
the only piece that touches `ibkr_client` directly, so tests can monkeypatch
just that boundary.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_main.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# backend/main.py
from pathlib import Path

from fastapi import FastAPI, HTTPException

from backend import calc, config, ibkr_client, icons

app = FastAPI()
CONFIG_PATH = Path(__file__).parent / "config.json"


def build_portfolio_response(positions: list[dict], nlv: float, icon_lookup: dict, warnings: list[str]) -> dict:
    underlying_rows = calc.aggregate_by_underlying(positions)
    total_notional = sum(row["notional"] for row in underlying_rows)
    total_exposure = sum(row["exposure"] for row in underlying_rows)
    leverage = calc.portfolio_leverage(total_notional, total_exposure, nlv)

    option_positions = [
        {
            "delta_shares": p["notional"] * p["delta"] / p["underlying_price"] if p.get("underlying_price") else 0.0,
            "theta": p.get("theta", 0.0),
            "vega": p.get("vega", 0.0),
        }
        for p in positions
        if p["type"] in ("COPT", "POPT")
    ]
    greeks = calc.greeks_card(option_positions) if option_positions else {"net_delta": 0.0, "net_theta": 0.0, "net_vega": 0.0}

    underlyings = []
    for row in underlying_rows:
        icon_path, color = icon_lookup.get(row["underlying"], (None, "#888888"))
        underlyings.append({
            "symbol": row["underlying"],
            "notional": row["notional"],
            "exposure": row["exposure"],
            "color": color,
            "iconUrl": icon_path,
        })

    return {
        "nlv": nlv,
        "totalNotional": total_notional,
        "totalExposure": total_exposure,
        "notionalLeverage": leverage["notional_leverage"],
        "exposureLeverage": leverage["exposure_leverage"],
        "netDelta": greeks["net_delta"],
        "netTheta": greeks["net_theta"],
        "netVega": greeks["net_vega"],
        "underlyings": underlyings,
        "positions": positions,
        "warnings": warnings,
    }


@app.get("/api/portfolio")
def get_portfolio():
    cfg = config.load_config(CONFIG_PATH)
    try:
        ib = ibkr_client.connect(cfg.ib_gateway_host, cfg.ib_gateway_port, cfg.ib_gateway_client_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"無法連線到 IB Gateway，請確認已啟動並登入: {exc}")

    try:
        raw_positions, warnings = _collect_positions(ib, cfg)
        nlv = ibkr_client.fetch_nlv(ib)
    finally:
        ib.disconnect()

    underlyings = {p["underlying"] for p in raw_positions}
    icon_lookup = {
        symbol: icons.get_icon_and_color(symbol, cfg.logo_api_key)
        for symbol in underlyings
    }
    return build_portfolio_response(raw_positions, nlv, icon_lookup, warnings)


def _collect_positions(ib, cfg) -> tuple[list[dict], list[str]]:
    """Pulls raw ib_insync positions, resolves underlying prices/Greeks, and
    returns calc-ready position dicts plus any per-symbol warnings."""
    positions = []
    warnings: list[str] = []
    for pos in ibkr_client.fetch_positions(ib):
        try:
            positions.append(_position_to_record(ib, pos, cfg))
        except Exception as exc:
            warnings.append(f"{pos.contract.symbol}: {exc}")
    return positions, warnings


def _position_to_record(ib, pos, cfg) -> dict:
    contract = pos.contract
    if contract.secType == "OPT":
        underlying_price = ibkr_client.fetch_underlying_price(ib, contract.symbol)
        ticker = ibkr_client.fetch_option_market_data(ib, contract)
        notional = calc.option_notional(pos.position, underlying_price)
        if ticker.modelGreeks and ticker.modelGreeks.delta is not None:
            delta = ticker.modelGreeks.delta
            theta = ticker.modelGreeks.theta or 0.0
            vega = ticker.modelGreeks.vega or 0.0
            iv = (ticker.modelGreeks.impliedVol or 0.0) * 100
        else:
            T = _years_to_expiry(contract.lastTradeDateOrContractMonth)
            q = cfg.dividend_yield_for(contract.symbol)
            right = "C" if contract.right == "C" else "P"
            sigma = calc.implied_vol(ticker.marketPrice(), underlying_price, contract.strike, T, cfg.risk_free_rate, q, right)
            greeks = calc.bs_greeks(underlying_price, contract.strike, T, cfg.risk_free_rate, q, sigma, right)
            delta, theta, vega, iv = greeks["delta"], greeks["theta"], greeks["vega"], sigma * 100
        exposure = calc.option_exposure(notional, delta)
        return {
            "label": f"{contract.symbol} {contract.strike:g}{contract.right} {contract.lastTradeDateOrContractMonth}",
            "underlying": cfg.leveraged_etf_map.get(contract.symbol, {}).get("underlying", contract.symbol),
            "type": "COPT" if contract.right == "C" else "POPT",
            "notional": notional, "exposure": exposure, "discount": calc.discount(notional, exposure),
            "delta": delta, "theta": theta, "vega": vega, "iv": iv, "underlying_price": underlying_price,
        }

    mapping = cfg.leveraged_etf_map.get(contract.symbol)
    price = ibkr_client.fetch_underlying_price(ib, contract.symbol)
    if mapping:
        notional = calc.leveraged_etf_notional(pos.position, price, mapping["multiplier"])
        underlying = mapping["underlying"]
        delta = mapping["multiplier"] if pos.position >= 0 else -mapping["multiplier"]
    else:
        notional = calc.stock_notional(pos.position, price)
        underlying = contract.symbol
        delta = 1.0 if pos.position >= 0 else -1.0
    return {
        "label": f"{contract.symbol}→{underlying}" if mapping else contract.symbol,
        "underlying": underlying, "type": "STK",
        "notional": notional, "exposure": notional, "discount": 0.0,
        "delta": delta, "theta": 0.0, "vega": 0.0, "iv": None, "underlying_price": price,
    }


def _years_to_expiry(expiry_str: str) -> float:
    from datetime import date
    expiry = date(int(expiry_str[:4]), int(expiry_str[4:6]), int(expiry_str[6:8]))
    days = max((expiry - date.today()).days, 1)
    return days / 365.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_main.py -v`
Expected: both tests PASS

- [ ] **Step 5: Run the full backend test suite**

Run: `cd backend && pytest -v`
Expected: all tests across `test_calc.py`, `test_config.py`, `test_icons.py`, `test_main.py` PASS

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/tests/test_main.py
git commit -m "Add GET /api/portfolio endpoint wiring ibkr_client, calc, icons, config"
```

---

## Task 10: Frontend scaffold + types + API client

**Files:**
- Create: `frontend/` (via Vite scaffold)
- Create: `frontend/src/types.ts`
- Create: `frontend/src/api.ts`

- [ ] **Step 1: Scaffold the Vite project**

Run from the repo root:
```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
```
Expected: `frontend/` populated with a standard Vite React+TS app, `npm install` completes with no errors.

- [ ] **Step 2: Add the backend proxy to `frontend/vite.config.ts`**

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
```

- [ ] **Step 3: Create `frontend/src/types.ts`**

```ts
export interface UnderlyingRow {
  symbol: string;
  notional: number;
  exposure: number;
  color: string;
  iconUrl: string | null;
}

export interface PositionRow {
  label: string;
  underlying: string;
  type: "STK" | "COPT" | "POPT";
  notional: number;
  exposure: number;
  discount: number;
  delta: number | null;
  iv: number | null;
}

export interface PortfolioResponse {
  nlv: number;
  totalNotional: number;
  totalExposure: number;
  notionalLeverage: number;
  exposureLeverage: number;
  netDelta: number;
  netTheta: number;
  netVega: number;
  underlyings: UnderlyingRow[];
  positions: PositionRow[];
  warnings: string[];
}
```

- [ ] **Step 4: Create `frontend/src/api.ts`**

```ts
import type { PortfolioResponse } from "./types";

export async function fetchPortfolio(): Promise<PortfolioResponse> {
  const res = await fetch("/api/portfolio");
  if (!res.ok) {
    const body = await res.json().catch(() => ({} as { detail?: string }));
    throw new Error(body.detail ?? `請求失敗 (${res.status})`);
  }
  return res.json();
}
```

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "Scaffold Vite React+TS frontend with backend proxy and API types"
```

---

## Task 11: DonutChart component

**Files:**
- Create: `frontend/src/components/DonutChart.tsx`

Ported from `examples/portfolio pie.tsx`'s `DonutChart`, generalized to take
a `colorFor` lookup instead of the hardcoded `COLORS` constant.

- [ ] **Step 1: Implement**

```tsx
// frontend/src/components/DonutChart.tsx
interface SliceDatum {
  und: string;
  label?: string;
  val: number;
}

interface DonutChartProps {
  data: SliceDatum[];
  total: number;
  title: string;
  subtitle: string;
  nlv: number;
  colorFor: (und: string) => string;
  onHover: (und: string | null) => void;
  hoveredUnd: string | null;
}

const fmt = (n: number, d = 0) => n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const fmtM = (n: number) => (n >= 1e6 ? `$${(n / 1e6).toFixed(2)}M` : `$${fmt(n)}`);

export default function DonutChart({ data, total, title, subtitle, nlv, colorFor, onHover, hoveredUnd }: DonutChartProps) {
  const cx = 160, cy = 160, outerR = 128, innerR = 70;
  const slices: Array<SliceDatum & { frac: number; sa: number; ea: number; mid: number }> = [];
  let angle = -Math.PI / 2;
  data.forEach((d) => {
    const frac = d.val / total, sa = angle, ea = angle + frac * 2 * Math.PI, mid = (sa + ea) / 2;
    slices.push({ ...d, frac, sa, ea, mid });
    angle = ea;
  });
  const pol = (a: number, r: number): [number, number] => [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  const arc = (sa: number, ea: number, r: number, R: number) => {
    const lg = ea - sa > Math.PI ? 1 : 0;
    const [x1, y1] = pol(sa, R), [x2, y2] = pol(ea, R), [x3, y3] = pol(ea, r), [x4, y4] = pol(sa, r);
    return `M${x1} ${y1} A${R} ${R} 0 ${lg} 1 ${x2} ${y2} L${x3} ${y3} A${r} ${r} 0 ${lg} 0 ${x4} ${y4}Z`;
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
      <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: "#5a7a9a", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 4 }}>{title}</div>
      <svg width={320} height={320} style={{ overflow: "visible" }}>
        {slices.map((s) => {
          const isH = hoveredUnd === s.und, isO = hoveredUnd && !isH;
          const R = isH ? outerR + 6 : outerR;
          return (
            <path key={s.und} d={arc(s.sa, s.ea, innerR, R)}
              fill={colorFor(s.und)} opacity={isO ? 0.3 : 1}
              stroke="#070b14" strokeWidth={1.5} style={{ cursor: "pointer", transition: "opacity 0.15s" }}
              onMouseEnter={() => onHover(s.und)} onMouseLeave={() => onHover(null)} />
          );
        })}
        {slices.map((s) => {
          if (s.frac < 0.012) return null;
          const [x1, y1] = pol(s.mid, outerR + 4), [x2, y2] = pol(s.mid, outerR + 14), [tx, ty] = pol(s.mid, outerR + 22);
          const anc = Math.cos(s.mid) > 0.1 ? "start" : Math.cos(s.mid) < -0.1 ? "end" : "middle";
          return (
            <g key={"l" + s.und}>
              <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={colorFor(s.und)} strokeWidth={0.8} opacity={0.7} />
              <text x={tx} y={ty} textAnchor={anc} dominantBaseline="middle" fill={colorFor(s.und)} fontSize={9.5} fontFamily="'JetBrains Mono',monospace" fontWeight="600">{s.und}</text>
            </g>
          );
        })}
        <text x={cx} y={cy - 10} textAnchor="middle" fill="#c8ddf0" fontSize={13} fontFamily="'JetBrains Mono',monospace" fontWeight="700">{fmtM(total)}</text>
        <text x={cx} y={cy + 8} textAnchor="middle" fill="#4a7a9a" fontSize={9} fontFamily="'JetBrains Mono',monospace">{subtitle}</text>
        <text x={cx} y={cy + 22} textAnchor="middle" fill="#3a6a8a" fontSize={9} fontFamily="'JetBrains Mono',monospace">{(total / nlv).toFixed(2)}× NLV</text>
      </svg>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/DonutChart.tsx
git commit -m "Port DonutChart component with injectable color lookup"
```

---

## Task 12: App.tsx — live dashboard with refresh/loading/error states

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Implement**

```tsx
// frontend/src/App.tsx
import { useState, useEffect, useCallback } from "react";
import DonutChart from "./components/DonutChart";
import { fetchPortfolio } from "./api";
import type { PortfolioResponse } from "./types";

const fmt = (n: number, d = 0) => n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

export default function App() {
  const [data, setData] = useState<PortfolioResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState<"byUnd" | "byPos">("byUnd");
  const [hoveredUnd, setHoveredUnd] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchPortfolio()
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const bg = "#070b14", card = "#0c1422", border = "#1a2d45", text = "#c8ddf0", muted = "#4a7a9a", accent = "#2a6fb8", mono = "'JetBrains Mono','Fira Code',monospace";

  const colorFor = (und: string) => data?.underlyings.find((u) => u.symbol === und)?.color ?? "#556";

  if (error) {
    return (
      <div style={{ background: bg, minHeight: "100vh", color: text, fontFamily: mono, padding: 24 }}>
        <p>無法載入持倉資料：{error}</p>
        <button onClick={load} style={{ background: accent, color: "#fff", border: "none", padding: "8px 16px", borderRadius: 4, cursor: "pointer" }}>重試</button>
      </div>
    );
  }

  if (loading || !data) {
    return <div style={{ background: bg, minHeight: "100vh", color: text, fontFamily: mono, padding: 24 }}>載入中…</div>;
  }

  const undN = data.underlyings.map((u) => ({ und: u.symbol, val: u.notional }));
  const undE = data.underlyings.map((u) => ({ und: u.symbol, val: u.exposure }));
  const posN = data.positions.map((p) => ({ und: p.underlying, label: p.label, val: p.notional }));
  const posE = data.positions.map((p) => ({ und: p.underlying, label: p.label, val: p.exposure }));

  return (
    <div style={{ background: bg, minHeight: "100vh", color: text, fontFamily: mono, fontSize: 12, paddingBottom: 40 }}>
      <div style={{ background: card, borderBottom: `1px solid ${border}`, padding: "14px 24px", display: "flex", flexWrap: "wrap", gap: 16, alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <div style={{ fontSize: 10, color: muted, letterSpacing: "0.12em", textTransform: "uppercase" }}>Portfolio Risk Dashboard</div>
          <div style={{ fontSize: 15, color: "#e0eeff", fontWeight: 700, marginTop: 2 }}>Notional &amp; Delta Exposure</div>
        </div>
        <div style={{ display: "flex", gap: 20, flexWrap: "wrap", alignItems: "center" }}>
          {[["NLV", `$${fmt(data.nlv)}`], ["Notional", `$${fmt(data.totalNotional)}`], ["Notl Lev", `${data.notionalLeverage.toFixed(2)}×`], ["Exposure", `$${fmt(data.totalExposure)}`], ["Exp Lev", `${data.exposureLeverage.toFixed(2)}×`]].map(([l, v]) => (
            <div key={l} style={{ textAlign: "right" }}>
              <div style={{ fontSize: 9, color: muted, letterSpacing: "0.1em" }}>{l}</div>
              <div style={{ fontSize: 13, color: "#e0eeff", fontWeight: 700 }}>{v}</div>
            </div>
          ))}
          <button onClick={load} style={{ background: accent, color: "#fff", border: "none", padding: "6px 14px", borderRadius: 4, cursor: "pointer", fontFamily: mono }}>重新整理</button>
        </div>
      </div>

      <div style={{ display: "flex", justifyContent: "center", padding: "14px 0 6px", gap: 8 }}>
        {([["byUnd", "依標的"], ["byPos", "依倉位"]] as const).map(([v, l]) => (
          <button key={v} onClick={() => setView(v)} style={{ background: view === v ? accent : "transparent", border: `1px solid ${view === v ? accent : border}`, color: view === v ? "#fff" : muted, fontFamily: mono, fontSize: 11, letterSpacing: "0.08em", padding: "5px 16px", borderRadius: 3, cursor: "pointer" }}>{l}</button>
        ))}
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: 20, padding: "4px 24px" }}>
        <DonutChart data={view === "byUnd" ? undN : posN} total={data.totalNotional} title="名義 Notional" subtitle="Total Notional" nlv={data.nlv} colorFor={colorFor} onHover={setHoveredUnd} hoveredUnd={hoveredUnd} />
        <DonutChart data={view === "byUnd" ? undE : posE} total={data.totalExposure} title="曝險 Delta Exposure" subtitle="Δ-Weighted Exp" nlv={data.nlv} colorFor={colorFor} onHover={setHoveredUnd} hoveredUnd={hoveredUnd} />
      </div>

      <div style={{ display: "flex", justifyContent: "center", padding: "14px 24px 6px" }}>
        <div style={{ background: card, border: `1px solid ${border}`, borderRadius: 4, padding: "10px 32px", display: "flex", gap: 40 }}>
          {[["Net Δ (share-eq)", fmt(data.netDelta), "#4a9eff"], ["Net Θ/day", `${data.netTheta >= 0 ? "+" : ""}$${fmt(data.netTheta, 2)}`, "#4fc3a1"], ["Net Vega /1%vol", `${data.netVega >= 0 ? "+" : "-"}$${fmt(Math.abs(data.netVega), 2)}`, "#e8703a"]].map(([l, v, c]) => (
            <div key={l} style={{ textAlign: "center" }}>
              <div style={{ fontSize: 9, color: muted, letterSpacing: "0.1em", marginBottom: 4 }}>{l}</div>
              <div style={{ fontSize: 15, color: c, fontWeight: 700 }}>{v}</div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 5, justifyContent: "center", padding: "6px 24px" }}>
        {data.underlyings.map((u) => (
          <div key={u.symbol} onMouseEnter={() => setHoveredUnd(u.symbol)} onMouseLeave={() => setHoveredUnd(null)}
            style={{ display: "flex", alignItems: "center", gap: 5, cursor: "pointer", background: hoveredUnd === u.symbol ? "#1a2d45" : "transparent", borderRadius: 3, padding: "2px 8px" }}>
            {u.iconUrl && <img src={u.iconUrl} alt={u.symbol} width={14} height={14} style={{ borderRadius: 2 }} />}
            <span style={{ color: muted, fontSize: 9 }}>{u.symbol}</span>
            <span style={{ color: "#607888", fontSize: 9 }}>{((u.notional / data.totalNotional) * 100).toFixed(1)}%N</span>
            <span style={{ color: "#506070", fontSize: 9 }}>/{((u.exposure / data.totalExposure) * 100).toFixed(1)}%E</span>
          </div>
        ))}
      </div>

      <div style={{ padding: "10px 24px 0" }}>
        <div style={{ fontSize: 9, color: muted, letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 6 }}>標的明細 Underlying Breakdown</div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${border}`, color: muted }}>
                {["標的", "Notional", "Not%", "Exposure", "Exp%", "Discount"].map((h, i) => (
                  <th key={h} style={{ padding: "4px 10px", textAlign: i === 0 ? "left" : "right", fontWeight: 500, fontSize: 9, whiteSpace: "nowrap" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.underlyings.map((u) => {
                const disc = 1 - u.exposure / u.notional;
                return (
                  <tr key={u.symbol} onMouseEnter={() => setHoveredUnd(u.symbol)} onMouseLeave={() => setHoveredUnd(null)} style={{ borderBottom: "1px solid #111b2a" }}>
                    <td style={{ padding: "5px 10px", display: "flex", alignItems: "center", gap: 6 }}>
                      {u.iconUrl && <img src={u.iconUrl} alt={u.symbol} width={14} height={14} style={{ borderRadius: 2 }} />}
                      <span style={{ color: "#c0d8f0", fontWeight: 600 }}>{u.symbol}</span>
                    </td>
                    <td style={{ padding: "5px 10px", textAlign: "right", color: "#a0c0e0" }}>${fmt(u.notional)}</td>
                    <td style={{ padding: "5px 10px", textAlign: "right", color: muted }}>{((u.notional / data.totalNotional) * 100).toFixed(1)}%</td>
                    <td style={{ padding: "5px 10px", textAlign: "right", color: "#a0c0e0" }}>${fmt(u.exposure)}</td>
                    <td style={{ padding: "5px 10px", textAlign: "right", color: muted }}>{((u.exposure / data.totalExposure) * 100).toFixed(1)}%</td>
                    <td style={{ padding: "5px 10px", textAlign: "right" }}>{(disc * 100).toFixed(1)}%</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div style={{ padding: "14px 24px 0" }}>
        <div style={{ fontSize: 9, color: muted, letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 6 }}>倉位明細 Position Details</div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 10.5, minWidth: 680 }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${border}`, color: muted }}>
                {["倉位", "類型", "Notional", "Exposure", "Discount", "Δ", "IV"].map((h, i) => (
                  <th key={h} style={{ padding: "4px 10px", textAlign: i <= 1 ? "left" : "right", fontWeight: 500, fontSize: 9, whiteSpace: "nowrap" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.positions.map((p, i) => (
                <tr key={i} onMouseEnter={() => setHoveredUnd(p.underlying)} onMouseLeave={() => setHoveredUnd(null)} style={{ borderBottom: "1px solid #0e1a28" }}>
                  <td style={{ padding: "4px 10px", color: "#b0ccdf" }}>{p.label}</td>
                  <td style={{ padding: "4px 10px", fontSize: 9 }}>{p.type}</td>
                  <td style={{ padding: "4px 10px", textAlign: "right", color: "#90b0d0" }}>${fmt(p.notional)}</td>
                  <td style={{ padding: "4px 10px", textAlign: "right", color: "#90b0d0" }}>${fmt(p.exposure)}</td>
                  <td style={{ padding: "4px 10px", textAlign: "right" }}>{(p.discount * 100).toFixed(1)}%</td>
                  <td style={{ padding: "4px 10px", textAlign: "right" }}>{p.delta !== null ? (p.delta > 0 ? "+" : "") + p.delta.toFixed(3) : "—"}</td>
                  <td style={{ padding: "4px 10px", textAlign: "right", color: muted }}>{p.iv !== null ? p.iv.toFixed(1) + "%" : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {data.warnings.length > 0 && (
        <div style={{ padding: "14px 24px 0", color: "#e8a03a", fontSize: 10 }}>
          {data.warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Run the dev servers and verify manually**

Run in two terminals:
```bash
cd backend && source .venv/bin/activate && uvicorn main:app --reload --port 8000
cd frontend && npm run dev
```
Open the printed Vite URL. Expected: with IB Gateway running and logged in,
the dashboard loads real positions; with IB Gateway stopped, the page shows
the error state with a working "重試" button.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "Wire dashboard to live backend data with loading/error/refresh states"
```

---

## Task 13: README with setup and run instructions

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write the README**

```markdown
# IBKR Portfolio Pie Dashboard

Read-only dashboard showing notional / delta-weighted exposure / discount
per position and per underlying, sourced live from IBKR via IB Gateway.

## Prerequisites

1. **IB Gateway** installed and running, login mode **IB API** (not FXI CTCI).
   In Configure → Settings → API → Settings: enable "ActiveX and Socket
   Clients" and check "Read-Only API". Port 4001 = live, 4002 = paper.
2. (Optional, for real logos) an API key from the logo provider configured
   in `backend/config.json` under `logo_api.api_key`. Without a key, every
   symbol falls back to a generated text icon — the dashboard still works.

## Run

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Open the URL Vite prints. Click "重新整理" to refetch live data — there is
no automatic/realtime polling by design.

## Read-only guarantee

No code in `backend/` calls any IBKR order-placement or account-modification
API. Combine with IB Gateway's own "Read-Only API" setting for defense in
depth.

## Config

Edit `backend/config.json` to adjust:
- `leveraged_etf_map`: which leveraged ETFs map to which underlying, and at what multiplier
- `dividend_yield`: per-symbol dividend yield used in the Black-Scholes fallback
- `risk_free_rate`: used in the Black-Scholes fallback
- `ib_gateway`: host/port/clientId
- `logo_api`: provider + key for fetching symbol icons
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "Add README with setup, run, and config instructions"
```

---

## Self-Review Notes

- **Spec coverage:** architecture/data-flow (Tasks 8-9), notional/exposure/discount formulas (Task 2), Greeks A/B fallback (Task 3, Task 9 `_position_to_record`), leveraged ETF mapping (Task 5, 9), config file (Task 5), frontend reuse of the example UI (Tasks 10-12), icon fetch/cache/color-sync/fallback (Tasks 6-7, 9, 12), README/run instructions (Task 13), read-only guarantee (Task 8 docstring, Task 13) — all covered.
- **Placeholder scan:** none found; the one open external dependency (logo provider URL) ships with a concrete default and an explicit verification step (Task 7, Step 5) rather than a TBD.
- **Type consistency:** `PortfolioResponse`/`UnderlyingRow`/`PositionRow` (frontend, Task 10) match the keys returned by `build_portfolio_response` (backend, Task 9): `nlv`, `totalNotional`, `totalExposure`, `notionalLeverage`, `exposureLeverage`, `netDelta`, `netTheta`, `netVega`, `underlyings[].{symbol,notional,exposure,color,iconUrl}`, `positions[].{label,underlying,type,notional,exposure,discount,delta,iv}`, `warnings`.
