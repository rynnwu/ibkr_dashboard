# IBKR Portfolio Pie Dashboard

Read-only dashboard showing notional / delta-weighted exposure / discount
per position and per underlying, sourced live from IBKR via IB Gateway.

## Prerequisites

1. **IB Gateway** installed and running, login mode **IB API** (not FXI CTCI).
   In Configure → Settings → API → Settings: enable "ActiveX and Socket
   Clients" and check "Read-Only API". Port 4001 = live, 4002 = paper.
2. (Optional, for real logos) an API key from the logo provider configured
   in `backend/config.json` under `logo_api.api_key`. The shipped config
   already has a placeholder (`"enabled"`) that turns on real logo fetching
   by default — no signup/account needed for the current provider
   (financialmodelingprep's keyless image endpoint). To disable real logos
   and force text-fallback icons, set `logo_api.api_key` to an empty string `""`.

## Run

```bash
# Backend (run from the REPO ROOT, not from inside backend/ —
# main.py uses `from backend import ...` absolute imports, so uvicorn
# needs `backend` importable as a package, which only works from the root)
python3 -m venv backend/.venv && source backend/.venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --port 8000

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
