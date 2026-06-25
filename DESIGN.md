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
| `backend/calc.py` | **Pure math, no I/O.** Notional/exposure/discount, Black-Scholes price/IV/Greeks, aggregation, leverage, Greeks card, **margin-buffer summary** (`margin_summary`), **roll what-if** (`roll_what_if`, `regt_short_put_maint`, `exposure_match_sizing`, `call_strike_for_delta`, shared `cushion_level`). | Fully unit-tested. Flat module functions (intentional — no classes). |
| `backend/config.py` | Load + expose `config.json` as a `Config` dataclass. | `dividend_yield_for(sym)` defaults to 0. `margin_warning_cushion`/`margin_danger_cushion` default to 0.20/0.10. |
| `backend/config.json` | Runtime config (no secrets needed). | leveraged-ETF map, dividend yields, risk-free rate, gateway host/port/clientId, logo API, `margin_thresholds` (cushion levels for the margin card). |
| `backend/icons.py` | Per-symbol logo fetch + on-disk cache + dominant-color extraction, with a generated text-icon + hashed-color fallback. | Network call is injectable (`getter=`) so tests never hit the net. Cache: `backend/icon_cache/` (gitignored). |
| `backend/ibkr_client.py` | **Thin `ib_insync` wrapper. The only module that does IBKR I/O.** connect / positions / **account values** (`fetch_account_values`: NLV + margin tags in one `accountSummary` call) / NLV (`fetch_nlv`, now a wrapper) / **batched** market data (`fetch_market_data`) / `mark_price`. | Deliberately no automated tests (needs a live gateway). **Never** calls any order/account-modifying method. |
| `backend/cache.py` | **On-disk last-good snapshot** of the `/api/portfolio` payload — save / load / `now_iso`. No IBKR I/O, fully unit-tested. | Backs the offline fallback (§10). Cache file: `backend/portfolio_cache.json` (gitignored). |
| `backend/main.py` | FastAPI app + the wiring: `get_portfolio` route, the pure `build_portfolio_response`, the I/O glue `_collect_positions` (batch-fetches market data), the **pure** `_position_to_record` (reads from the fetched maps), `_build_margin` (turns account values into the margin block via `calc.margin_summary`), and the **`compute_roll_what_if`** / **`price_option`** / **`suggest_call`** POST routes (no IBKR I/O — see §11). | Also mounts `/icons` static files (see §5, gotcha G6). |

Tests live in `backend/tests/` (`test_calc`, `test_config`, `test_icons`,
`test_main`) and run with `backend/.venv/bin/pytest backend/tests/`.

## 4. Request data flow (`GET /api/portfolio`)

1. `connect()` → fresh `ib_insync.IB` to the gateway. On failure (or any error
   during the fetch) the route falls back to the **last cached snapshot** if one
   exists (see §10); only when there is *no* cache does it return HTTP **503**
   with a friendly message (frontend then shows an error state + retry).
2. `_collect_positions()` reads `ib.positions()`, then makes **one batched**
   `ibkr_client.fetch_market_data()` call for the whole portfolio (all
   underlying prices + all option tickers in a single bounded wait — see §9 and
   gotcha G9). It then loops the positions; **each is converted independently
   inside a try/except** — one bad symbol becomes a `warnings[]` entry (and a
   logged traceback), it does not sink the request.
3. `_position_to_record()` is **pure** (no I/O): it reads the underlying price
   from the `price_map` and, for options, the ticker from the
   `option_ticker_map` (keyed by `conId`). It branches per position:
   - **Option (`secType == "OPT"`):** take the underlying price + the option's
     snapshot ticker; if IB's native `modelGreeks` are present use them, else
     **fall back to Black-Scholes** (`calc.implied_vol` → `calc.bs_greeks`)
     off the mark. The native-first ordering is a deliberate design point.
   - **Leveraged ETF** (symbol in `leveraged_etf_map`): notional = `|qty| ×
     price × multiplier`, mapped to the underlying, delta = ±multiplier.
   - **Plain stock:** notional = `|qty| × price`, delta = ±1.
4. `fetch_account_values()` reads NetLiquidation **and the margin tags**
   (`MaintMarginReq`, `ExcessLiquidity`, and their `LookAhead*` projections) in
   one `accountSummary` call. `ib.disconnect()` runs in a `finally`.
   `_build_margin()` then turns those into the margin block via
   `calc.margin_summary()` (or `None` when no maintenance-margin figure is
   reported, e.g. a cash account).
5. Icons/colors resolved per unique underlying (cached).
6. `build_portfolio_response()` (pure, unit-tested) aggregates by underlying,
   computes totals, leverage ratios, the Greeks card, **and embeds the margin
   block**, and shapes the JSON.

### Margin-buffer block (`margin`)

`calc.margin_summary()` is pure risk math over the account values: it reports
`excessLiquidity` (the dollar buffer to forced liquidation — IBKR auto-liquidates
when it hits 0, with no traditional margin-call grace period), `cushion`
(`ExcessLiquidity / NLV`, the same ratio IBKR reports), `bufferRatio`
(`ExcessLiquidity / MaintMarginReq`), the optional `LookAhead*` projections
(after the next known margin change — SPAN updates / options nearing expiry,
especially relevant for short options), and a `level` of `safe`/`warning`/
`danger` derived from the configurable cushion thresholds
(`config.json → margin_thresholds`, defaults 0.20/0.10).

It also carries a **separate funding axis** — `cash` (TotalCashValue),
`availableFunds` (AvailableFunds = ELV − InitMargin), and `canOpenNew`
(`availableFunds > 0`). This axis answers "can I still open / roll positions?",
**not** "am I about to be liquidated?", and deliberately does **not** feed
`level` (mixing them would dilute the liquidation signal). Because
`availableFunds ≤ excessLiquidity` always, it hits zero *first*, so
`canOpenNew == false` is the early warning that a roll/open is no longer
possible (relevant when closing a short put then funding a long call — the
debit to buy back the put can exhaust cash before liquidation risk triggers).

The frontend renders this as a colored card under the header (the liquidation
`level` drives the card color + a red banner at `danger`; `cash`/`availableFunds`
show as extra cells, red when negative; `canOpenNew == false` shows a separate
"無法開新倉" badge). The block is `null` when unavailable, so the frontend (and
old cached snapshots from before this field existed) degrade gracefully.

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
sync with `frontend/src/types.ts` (`PortfolioResponse`, `MarginSummary`). It
carries two cache-status fields — `stale` (bool) and `cachedAt` (local-time
ISO 8601, or null) — see §10 — and the `margin` block (or `null`) described
above. Each position record also carries `strike`, `mark` (per-share option mark; both
`null` for stock) and `daysToExpiry`, plus `quantity`/`underlying_price`/`iv`,
surfaced for the roll what-if SP picker and its model-pricing (§11).

## 5. Frontend

- `src/types.ts` — mirror of the backend JSON (`PortfolioResponse` etc.).
- `src/api.ts` — `fetchPortfolio()`; parses FastAPI's `{detail}` on error.
- `src/components/DonutChart.tsx` — presentational SVG donut; colors come from
  an injected `colorFor` lookup (not a hardcoded table).
- `src/App.tsx` — the dashboard: loading / error / data states, refresh
  button, by-underlying ⇄ by-position toggle, **margin-buffer card + danger
  banner** (driven by `margin.level`), Greeks card, legend, two tables.
- `vite.config.ts` — dev-server proxy `/api → http://127.0.0.1:8000`.

### Mobile / responsive layout

- `src/hooks/useIsMobile.ts` — `matchMedia("(max-width: 640px)")`, live-updated
  via the `change` listener. 640px covers portrait phones (~360-430px) while
  leaving small tablets/desktop windows on the wide layout.
- `App.tsx` reads `useIsMobile()` and switches layout, not markup: on mobile
  the two donut charts stack vertically instead of side-by-side, the legend
  becomes wrappable horizontal tags instead of a side list, and section
  padding shrinks.
- `DonutChart.tsx` uses an SVG `viewBox` (not a fixed `width`/`height`) so the
  chart — including text and stroke width — scales down with its container on
  narrow screens instead of overflowing a fixed 320px box.
- The "by underlying" and "by position" detail tables keep their first column
  (underlying/position) `position: sticky` while scrolling horizontally. The
  underlying table's frozen cell wraps the icon+text in a flex `div` *inside*
  the `td` rather than making the `td` itself `display: flex` — the latter
  broke `sticky` on Safari/WebKit.

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
- **G9 — market data is batched; use a *bounded, polled* wait, not
  `reqTickers`.** `fetch_market_data()` fires every snapshot `reqMktData` up
  front and waits for replies to stream in concurrently — this is what makes a
  refresh ~10s instead of ~2 min (see §9). Do **not** swap in ib_insync's
  `ib.reqTickers`: it awaits *every* snapshot with no timeout and would hang
  forever if one option's snapshot never ends — the common non-OPRA case (G4).
  The wait is polled in small increments (default 0.5s, up to a 15s ceiling)
  and exits early once every contract has a usable mark, so the common case is
  still fast; a contract that hasn't priced by the ceiling degrades to a
  `warnings[]` entry. Underlyings are deduplicated, so an option and its stock
  share one price fetch. The first request after a (re)connect can be slower /
  occasionally miss a symbol while IB's market-data lines warm up; it clears on
  the next refresh. (Previously this was a single fixed `ib.sleep(8.0)` with no
  early exit and no extra budget for slow lines — that caused the same
  illiquid option to intermittently warn on one refresh and price fine on the
  next, since whatever hadn't arrived by 8s was dropped regardless of how close
  it was.)
- **G8 — clientId collisions look like "gateway down".** Each request opens its
  own connection, but with a *fixed* clientId two overlapping connects collide:
  IB returns `Error 326 "client id is already in use"` and ib_insync then hangs
  until the connect timeout, surfacing as a misleading **503 "無法連線到 IB
  Gateway"** even though the gateway is up. The trigger is the frontend firing
  two requests at once — React `<StrictMode>` double-invokes the mount effect,
  and rapid 重試/refresh does the same (each request is ~2 min, so they overlap
  easily). Fix is two-layer: `ibkr_client.connect()` tries the configured
  clientId then falls back to random ids until one is free; `App.tsx` guards
  against concurrent loads. See [`DEBUG.md`](DEBUG.md) §4 for the reproduction.

## 8. Running it

```bash
./start.sh   # starts backend + frontend (named processes), opens the browser
./stop.sh    # stops both
```

- IB Gateway must be running and logged in first (IB API mode, port 4001),
  or the dashboard loads but shows a connection error on refresh.
- Backend → `http://127.0.0.1:8000`, frontend → `http://localhost:5174`.
- Logs: `logs/ibkr_piechart_backend.log`, `logs/ibkr_piechart_frontend.log`
  (gitignored; written fresh on every `start.sh`).

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

- **Refresh takes ~10s** (was ~2 min). Market data for the whole portfolio is
  fetched in **one batched call** with a polled, bounded wait that exits early
  once every ticker has a usable mark (see §4 step 2 and gotcha G9), instead of
  a serial per-position snapshot timeout. A symbol that still hasn't priced
  by the 15s ceiling degrades to a `warnings[]` entry.
- **Options are priced off the previous close** (see G4), i.e. end-of-day, not
  intraday, unless the account has a live options data feed.
- **One account.** No multi-account handling.
- **No remote/auth.** Binds to localhost; intended for the user's own machine
  alongside their gateway.

## 10. Offline cache (last-good snapshot)

Goal: when IB Gateway is down (not running, not logged in, mid-restart) the
dashboard should still show the **most recent successful snapshot** rather than
only an error screen.

- **Where it lives.** `backend/cache.py` owns it; the file is
  `backend/portfolio_cache.json` (gitignored). No IBKR I/O, fully unit-tested
  (`backend/tests/test_cache.py`).
- **Write path.** On every *successful* live fetch, `get_portfolio` calls
  `cache.save_portfolio(payload)` with the exact response dict — which already
  has `stale: false` and `cachedAt: <now>` baked in by
  `build_portfolio_response`. Writes are best-effort: a cache write failure is
  logged and swallowed so it can never break a good request.
- **Read/fallback path.** `get_portfolio` wraps the live fetch
  (`_fetch_live_portfolio`) in a try/except. On **any** failure (connect *or*
  fetch) it calls `cache.load_portfolio()`:
  - cache present → return it with **`stale` forced True** and the original
    `cachedAt` preserved (so the frontend can say how old it is). HTTP 200.
  - no/again-unreadable cache → re-raise as the friendly HTTP **503**.
- **Response contract.** Two extra fields, mirrored in
  `frontend/src/types.ts`: `stale: boolean`, `cachedAt: string | null`.
- **Frontend.** When `stale` is true, `App.tsx` renders a yellow banner under
  the header showing the snapshot time and prompting a refresh; the normal
  charts/tables still render off the cached payload.
- **Deliberately no TTL.** A snapshot never "expires"; staleness is surfaced
  via the banner/`cachedAt` and left to the user to judge. (If a hard cap is
  ever wanted, that's the single place to add it.)

## 11. Roll what-if (換倉資金/保證金試算)

Goal: estimate, on the dashboard, the effect of **closing a short put and
opening a long call (or buying a 2x ETF)** on (a) the margin/liquidation buffer
and (b) whether there's enough cash to execute the roll. It's an extension of
the margin-buffer card (§4) — same two axes (liquidation vs. funding), same
`cushion_level` thresholds. Full derivation + limitations live in
[`TODO.md`](TODO.md).

- **Backend math** is pure in `calc.py`:
  - `roll_what_if(...)` — given current `excess_liquidity`/`nlv` (+ optional
    `cash`/`available_funds`), the released `mm_sp`, the close debit `D`, and
    the replacement leg (call premium and/or ETF value × maint rate), returns
    EL/cushion/level **before→after** plus the funding `surplus`/`canExecute`/
    `shortfall`. ΔEL = +mm_sp (release SP) − premium (long call, no loan value)
    − maint_rate×V (ETF). Funding outflow = D + premium + ETF value.
  - `regt_short_put_maint(...)` — Reg T naked-put maintenance approximation, the
    **default** for the most fragile input (`mm_sp`); the UI lets the user
    override it with the actual TWS What-If figure.
  - `exposure_match_sizing(...)` — sizes a replacement leg to match the SP's
    current delta exposure (helper; not yet surfaced in the UI).
- **Endpoints** (both thin, **I/O-free** wrappers — no gateway connection):
  - `POST /api/roll-what-if` (`compute_roll_what_if`): the client already holds
    the current account figures (from the latest `/api/portfolio` margin block),
    so it sends them in the request and the route just runs the pure calc +
    config thresholds. Mirrors `RollWhatIfRequest`/`RollWhatIfResult`.
  - `POST /api/price-option` (`price_option`): Black-Scholes model price + Greeks
    for one leg given S/K/days-to-expiry/right/IV (risk-free rate from config).
    Lets the panel **model-price** a leg via `calc.bs_price`/`bs_greeks` — the
    same single-sourced math as the portfolio fetch. Mirrors
    `PriceOptionRequest`/`PriceOptionResult`.
  - `POST /api/suggest-call` (`suggest_call`): suggests a replacement long-call
    strike at a **target delta** = max(|SP delta|, `minDelta`) via the
    closed-form `calc.call_strike_for_delta` (inverse of BS delta), rounds it to
    a whole dollar, and prices it. The frontend defaults `daysToExpiry` to ~180
    and `minDelta` to 0.85. Mirrors `SuggestCallRequest`/`SuggestCallResult`.
- **Frontend** `components/RollWhatIf.tsx` — a collapsible panel under the
  margin card. Lists **every** short put from the live positions (auto-fills
  S/K/contracts/IV/days from `strike`/`quantity`/`underlying_price`/`iv`/
  `daysToExpiry`). The put's mark is the live `mark` when present, else
  **model-priced off its IV** via `/api/price-option` (tagged 市場/模型) — so a
  leg with no OPRA quote (mark `null`) is still selectable. The long-call leg defaults to a
  **~180 DTE** call whose strike is auto-suggested (`/api/suggest-call`) to a
  delta of max(|SP delta|, 0.85), priced off the SP's IV; `Q` defaults to the
  SP's contract count. The user can re-derive the strike (`依 Δ 建議履約價`),
  re-price an edited strike (`依模型估算 Call`), or delta-exposure-match Q. Takes an optional `MM_SP` override, and shows
  the before→after level chips + funding verdict. Renders a note when there's no
  margin block or no short put.
- **Hard limit** (carried as an in-UI caveat): this is an order-of-magnitude
  estimate. IBKR uses TIMS/SPAN scenario models (esp. Portfolio Margin —
  whole-account, non-linear, not decomposable per-leg), so a PM account must
  treat TWS What-If as authoritative.
