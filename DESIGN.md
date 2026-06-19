# IBKR Portfolio Pie Dashboard — Design

> Orientation doc for a future LLM agent (or human) picking this project up
> cold. It explains *what* the system does, *how* the pieces fit, *why* the
> non-obvious bits are the way they are, and *where* the landmines are.
> For the original requirements/decisions see
> [`docs/superpowers/specs/2026-06-19-ibkr-portfolio-pie-design.md`](docs/superpowers/specs/2026-06-19-ibkr-portfolio-pie-design.md)
> and the task plan in [`docs/superpowers/plans/`](docs/superpowers/plans/).

## 1. Purpose

A read-only dashboard that visualizes an Interactive Brokers (IBKR) account's
open positions as two donut charts — by **notional** and by **delta-weighted
exposure** — plus a Greeks summary and detail tables.

It replaces a manual, token-expensive workflow where the user pasted a prompt
into Claude, which called IBKR MCP tools, computed Greeks in Python, and
emitted a one-off React artifact each time. That logic is now a standalone
program: routine refreshes hit IBKR directly and need **no LLM in the loop**.

Design priorities, in order: **read-only safety**, **correctness of the risk
math**, **no LLM at runtime**. Latency is explicitly *not* a priority — refresh
is on-demand, not realtime.

## 2. Architecture

```
┌──────────────┐   ib_insync (socket, 127.0.0.1:4001)   ┌───────────────┐
│  IB Gateway   │ ◄───────────────────────────────────── │ Python backend │
│ (IB API mode, │ ──────────────────────────────────────►│   (FastAPI)    │
│  logged in)   │                                         └───────┬────────┘
└──────────────┘                                                 │ GET /api/portfolio
                                                                  │ (only on user refresh)
                                                          ┌───────▼────────┐
                                                          │ React frontend  │
                                                          │ (Vite + TS)     │
                                                          │ proxies /api →  │
                                                          │ backend :8000   │
                                                          └────────────────┘
```

- **IB Gateway** is the user's locally-run IBKR app (the *separate* Client
  Portal-style gateway is NOT used; this project uses the **TWS socket API**
  via `ib_insync`). Must be running, logged in, in **IB API** mode (not FXI
  CTCI), port **4001** (live) — with **Read-Only API** safe to leave enabled
  (see §6).
- **Backend** (`backend/`): FastAPI app, one real endpoint `GET /api/portfolio`.
  On each call it opens a fresh IB connection, pulls positions + NLV + prices,
  computes everything, disconnects, and returns one JSON payload.
- **Frontend** (`frontend/`): Vite + React + TypeScript SPA, a near-verbatim
  port of the reference design in [`examples/portfolio pie.tsx`](examples/portfolio%20pie.tsx).
  Fetches `/api/portfolio` on mount and on a manual "重新整理" (refresh) button;
  the Vite dev server proxies `/api` to the backend.

## 3. Backend modules (each has one job)

| File | Responsibility | Notes |
|---|---|---|
| `backend/calc.py` | **Pure math, no I/O.** Notional/exposure/discount, Black-Scholes price/IV/Greeks, aggregation, leverage, Greeks card. | Fully unit-tested. Flat module functions (intentional — no classes). |
| `backend/config.py` | Load + expose `config.json` as a `Config` dataclass. | `dividend_yield_for(sym)` defaults to 0. |
| `backend/config.json` | Runtime config (no secrets needed). | leveraged-ETF map, dividend yields, risk-free rate, gateway host/port/clientId, logo API. |
| `backend/icons.py` | Per-symbol logo fetch + on-disk cache + dominant-color extraction, with a generated text-icon + hashed-color fallback. | Network call is injectable (`getter=`) so tests never hit the net. Cache: `backend/icon_cache/` (gitignored). |
| `backend/ibkr_client.py` | **Thin `ib_insync` wrapper. The only module that does IBKR I/O.** connect / positions / NLV / underlying price / option market data / `mark_price`. | Deliberately no automated tests (needs a live gateway). **Never** calls any order/account-modifying method. |
| `backend/main.py` | FastAPI app + the wiring: `get_portfolio` route, the pure `build_portfolio_response`, and the I/O glue `_collect_positions` / `_position_to_record`. | Also mounts `/icons` static files (see §5, gotcha G6). |

Tests live in `backend/tests/` (`test_calc`, `test_config`, `test_icons`,
`test_main`) and run with `backend/.venv/bin/pytest backend/tests/`.

## 4. Request data flow (`GET /api/portfolio`)

1. `connect()` → fresh `ib_insync.IB` to the gateway. On failure → HTTP **503**
   with a friendly message (frontend shows an error state + retry).
2. `_collect_positions()` loops over `ib.positions()`. **Each position is
   converted independently inside a try/except** — one bad symbol becomes a
   `warnings[]` entry (and a logged traceback), it does not sink the request.
3. `_position_to_record()` branches per position:
   - **Option (`secType == "OPT"`):** get underlying price; get the option's
     mark via a snapshot; if IB's native `modelGreeks` are present use them,
     else **fall back to Black-Scholes** (`calc.implied_vol` → `calc.bs_greeks`)
     off the mark. The native-first ordering is a deliberate design point.
   - **Leveraged ETF** (symbol in `leveraged_etf_map`): notional = `|qty| ×
     price × multiplier`, mapped to the underlying, delta = ±multiplier.
   - **Plain stock:** notional = `|qty| × price`, delta = ±1.
4. `fetch_nlv()` reads NetLiquidation. `ib.disconnect()` runs in a `finally`.
5. Icons/colors resolved per unique underlying (cached).
6. `build_portfolio_response()` (pure, unit-tested) aggregates by underlying,
   computes totals, leverage ratios, and the Greeks card, and shapes the JSON.

### Key formulas (must match `examples/Prompt of notional pie chart.md`)

- **Notional** — option: `|contracts| × 100 × underlying_price`; stock:
  `|shares| × price`; leveraged ETF: `× multiplier`.
- **Exposure** — `notional × |delta|` (options get "discounted" by delta;
  stocks/ETFs have notional == exposure).
- **Discount** — `1 − exposure/notional` (0 for stocks).
- **Leverage** — notional/NLV and exposure/NLV.
- **Greeks card (options only)** — per position: `signed_qty × 100 × greek`.
  `signed_qty` carries the long/short sign, so a short put correctly shows
  *positive* delta-equivalent and *positive* (collected) theta.

The response JSON shape is the contract with the frontend; it must stay in
sync with `frontend/src/types.ts` (`PortfolioResponse`).

## 5. Frontend

- `src/types.ts` — mirror of the backend JSON (`PortfolioResponse` etc.).
- `src/api.ts` — `fetchPortfolio()`; parses FastAPI's `{detail}` on error.
- `src/components/DonutChart.tsx` — presentational SVG donut; colors come from
  an injected `colorFor` lookup (not a hardcoded table).
- `src/App.tsx` — the dashboard: loading / error / data states, refresh
  button, by-underlying ⇄ by-position toggle, Greeks card, legend, two tables.
- `vite.config.ts` — dev-server proxy `/api → http://127.0.0.1:8000`.

## 6. Read-only guarantee

No code under `backend/` calls any order-placement or account-modifying
ib_insync method (`placeOrder`, `cancelOrder`, etc.) — verifiable by grep.
The connection is opened with `readonly=True` (see gotcha G2). Leaving IB
Gateway's own **Read-Only API** checkbox enabled is compatible and recommended
(defense in depth).

## 7. Gotchas / hard-won lessons (READ THIS before changing the I/O layer)

These were all discovered running against a live gateway; the fixes live in
`backend/ibkr_client.py` and `backend/main.py`.

- **G1 — event loop in a worker thread.** `ib_insync` is asyncio-based and
  needs an event loop bound to the *calling* thread. FastAPI runs sync `def`
  routes in an anyio worker thread that has none → connect crashes with
  "There is no current event loop". `connect()` creates/sets one first.
- **G2 — Read-Only API blocks the handshake.** ib_insync's normal connect
  reserves the next valid order id; with IB Gateway's "Read-Only API" enabled
  that trips a "needs API write access" prompt and hangs. Fix: connect with
  `ib.connect(..., readonly=True)`, which skips the open-orders/order-id steps.
  (This is *not* our code trying to trade — it's the stock handshake.)
- **G3 — no live data → use delayed.** `ib.reqMarketDataType(3)` enables
  delayed data so accounts without a live subscription still get quotes where
  delayed entitlement exists.
- **G4 — options have no real-time/delayed quotes without OPRA.** For accounts
  without an options data feed, streaming option data (and `genericTickList=
  "106"` model/IV computation) is rejected and `marketPrice()` is NaN. **But
  the previous close (`ticker.close`) is available for free.** So: request a
  plain **snapshot** (no "106" tick) and fall back to `close` for the mark
  (`ibkr_client.mark_price()`). Greeks are then computed via Black-Scholes off
  that close. This makes the dashboard an *end-of-day* view for options, which
  fits the on-demand-refresh design.
- **G5 — option contracts from `positions()` lack an exchange.** They must be
  `qualifyContracts()`-ed (and given `exchange="SMART"`) before `reqMktData`,
  or IB returns "Please enter exchange".
- **G6 — icons must be served over HTTP.** `get_icon_and_color` returns a
  filesystem path; the response `iconUrl` is rewritten to `/icons/<sym>.png`
  and `main.py` mounts `backend/icon_cache/` at `/icons` via `StaticFiles`.
  A raw filesystem path in `<img src>` silently fails in the browser.
- **G7 — NaN guards.** A NaN price defeats naive `== 0` checks and silently
  produces garbage (e.g. Black-Scholes returning ~500% IV). Both underlying
  and option marks are explicitly `math.isnan`-guarded; a position with no
  usable price is dropped into `warnings`, not shown with junk numbers.

## 8. Running it

```bash
./start.sh   # starts backend + frontend (named processes), opens the browser
./stop.sh    # stops both
```

- IB Gateway must be running and logged in first (IB API mode, port 4001),
  or the dashboard loads but shows a connection error on refresh.
- Backend → `http://127.0.0.1:8000`, frontend → `http://localhost:5173`.
- Logs: `/tmp/ibkr_piechart_backend.log`, `/tmp/ibkr_piechart_frontend.log`.

### Process naming (why it's done the odd way)

`stop.sh` matches processes by the precise tokens `ibkr_piechart_backend` /
`ibkr_piechart_frontend` so it never kills unrelated python/node/vite. The
mechanism differs by runtime:

- **Frontend (node):** launched with `exec -a ibkr_piechart_frontend` — argv[0]
  rename works because node doesn't re-exec.
- **Backend (python):** macOS **framework Python re-execs into `Python.app`
  and discards argv[0]**, so `exec -a` does *not* work. Instead the name is
  passed as a **trailing marker arg** to `python -c "...uvicorn.run..."`, which
  survives the re-exec and appears in `ps`. (Because it's launched via `-c`,
  uvicorn doesn't trap SIGTERM cleanly, so `stop.sh` force-kills any straggler
  after a grace period.)

A manual run, for reference:
```bash
# from repo ROOT (backend/main.py uses `from backend import ...` absolute imports)
backend/.venv/bin/python -m uvicorn backend.main:app --port 8000
cd frontend && npm run dev
```

## 9. Known limitations / next steps

- **Refresh takes ~2 min.** Positions are fetched **serially**, each waiting a
  fixed snapshot timeout. The obvious optimization is to parallelize the
  per-position market-data requests (or batch them) — not yet done.
- **Options are priced off the previous close** (see G4), i.e. end-of-day, not
  intraday, unless the account has a live options data feed.
- **One account.** No multi-account handling.
- **No remote/auth.** Binds to localhost; intended for the user's own machine
  alongside their gateway.
