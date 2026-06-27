# Debugging SOP — IBKR Portfolio Pie Dashboard

> Read [`DESIGN.md`](DESIGN.md) first for the architecture. This file is the
> hands-on playbook for *when something is broken*: where to look, how to
> reproduce, and the failure modes we've already diagnosed.

## 0. Golden rule

**Find the root cause before changing anything.** The frontend error
`無法載入持倉資料：…` is generic — it only means "the `/api/portfolio` call did
not return 200". It does **not** by itself tell you the gateway is down. Always
check the backend log + ports before touching code.

## 1. First five commands (triage)

```bash
# 1. Is anything actually listening? backend=8000, frontend=5174, gateway=4001
lsof -nP -iTCP -sTCP:LISTEN | grep -E ':(8000|5174|4001)'

# 2. Are our processes alive?
ps aux | grep -E 'ibkr_piechart|uvicorn|vite' | grep -v grep

# 3. Backend log (the real story is almost always here)
tail -60 logs/ibkr_piechart_backend.log

# 4. Frontend log
tail -20 logs/ibkr_piechart_frontend.log

# 5. Hit the API directly, bypassing the browser/proxy (a request takes ~10s)
curl -s -w "\nHTTP %{http_code}, %{time_total}s\n" http://127.0.0.1:8000/api/portfolio | head -c 400
```

Interpreting command 1:
- A line like `... *:4001 (LISTEN)` (owner `JavaAppli`) = **IB Gateway is up**.
- `... ->x.x.x.x:4001 (ESTABLISHED)` from `JavaAppli` is the gateway's *own
  outbound* link to IBKR servers — **not** a local API client. A local client
  shows as `127.0.0.1:...->127.0.0.1:4001`.
- No `:8000` line = backend is **down** (the most common real cause of the
  frontend error; `start.sh` "looked like it started" but the process exited).

## 1b. "載入中… forever" — alive or hung?

**A warm refresh takes ~15–20s** (DESIGN §9: market data is fetched in one batched
call with a single bounded wait, gotcha G9 — ~16s of that is the market-data wait;
plus the §12/§13 hedge-market fetch ~4–5s). The **first** request after a gateway
(re)connect runs longer (~30s) while IB's market-data lines warm up. So `載入中…`
for ~15–30s is **normal**, not a hang; past ~35s, suspect a real stall. Before
assuming it's stuck, prove it's making progress:

```bash
# 1. Both our processes alive? (start.sh names them)
ps aux | grep -E 'ibkr_piechart_(backend|frontend)' | grep -v grep

# 2. Is a request actually in flight? A live request = a local client socket
#    from the Python backend to the gateway, state ESTABLISHED:
lsof -nP -iTCP:4001 | grep 127.0.0.1
#    -> "...->127.0.0.1:4001 (ESTABLISHED)" owned by Python = working
#    -> only the JavaAppli LISTEN line / all CLOSED = no active request

# 3. Is the backend still writing? Compare mtime to now; reqIds should climb.
stat -f "%Sm  %N" -t "%H:%M:%S" logs/ibkr_piechart_backend.log; date "+%H:%M:%S  (now)"
tail -5 logs/ibkr_piechart_backend.log   # reqId N increasing = progressing
```

**Alive** = process up + ESTABLISHED socket to 4001 + log mtime within seconds +
reqId climbing. **Genuinely hung** = no ESTABLISHED socket and log mtime stale
for minutes → then investigate (gateway dropped, deadlock). Two kinds of log line
scrolling by are **expected** noise, not a stall: `Error 10091 ... requires
additional subscription` (per-option, no OPRA feed — DESIGN G4) and `Error 10358 ...
Fundamentals data is not allowed` (the §12 beta fetch, tick 258, on an account
with no Reuters-fundamentals entitlement — betas then fall back to config
`beta_overrides` / 1.0; see §3 below).

> A warm refresh is ~15–20s (market-data wait ~16s + concurrent hedge-market fetch
> ~4–5s; DESIGN §9/§12, gotcha G9). If it's now consistently **minutes**, that's a
> regression worth investigating — not the old "slow by design" behavior.

## 1c. Where logs live

Live logs are at `logs/ibkr_piechart_{backend,frontend}.log`, written by
`start.sh` and overwritten on each run. `logs/` is **gitignored** — backend
logs contain account figures (NLV, positions); never commit them (CLAUDE.md:
no personal info).

## 2. Layer map (where a failure lives)

```
Browser ──/api proxy──> Vite :5174 ──> FastAPI :8000 ──ib_insync──> IB Gateway :4001 ──> IBKR
   │            │                          │                            │
 UI error   proxy cfg                 backend log                  gateway login /
 state    (vite.config.ts)        (/tmp/...backend.log)            API settings
```

Bisect by asking, in order:
1. Does `curl :8000/api/portfolio` work? → isolates backend⇄gateway from
   browser⇄proxy. If curl works but the browser doesn't, it's a frontend/proxy
   problem, not IBKR.
2. What's the **HTTP status**? `503` = backend reached gateway code but
   `connect()`/data failed. `502`/connection refused = backend down. `200` with
   a UI error = frontend bug.
3. What's in the backend log right before the `503`? The real cause is there
   (timeout, clientId clash, market-data subscription, NaN price).

## 3. Known failure modes (seen against the live gateway)

| Symptom in backend log | Root cause | Fix / status |
|---|---|---|
| `Error 326 ... client id is already in use` then `API connection failed: TimeoutError()` → `503` | Two `/api/portfolio` connects overlap on the **fixed clientId** (`config.json` `client_id`). React `<StrictMode>` double-invokes the mount effect → two ~10s requests at once; rapid 重試 does the same. | **Fixed:** `ibkr_client.connect()` now tries the configured id then random fallback ids; `App.tsx` guards against concurrent loads. See §4. |
| `API connection failed: TimeoutError()` with **no** prior 326, gateway port not listening | Gateway not running / not logged in / wrong port. | Start + log into IB Gateway (IB API mode, port 4001). Config: `config.json > ib_gateway`. |
| `Error 10091 ... requires additional subscription` on an **Option** | Account has no live/OPRA options feed. **Expected** — not fatal. | By design (DESIGN G4): we use a plain snapshot + previous close + Black-Scholes. Position only fails if even `close` is NaN. |
| `Error 10358 ... Fundamentals data is not allowed` on a **Stock** | Account has no Reuters-fundamentals entitlement, so the §12 beta fetch (tick 258) gets no data. **Expected** — not fatal. | By design: beta falls back to config `beta_overrides` → 1.0 (defaulted symbols surface in `warnings[]`). The concurrent `fetch_hedge_market` grace-exits instead of waiting the full ceiling for betas that will never arrive. |
| Refresh **~28s+** (was ~15s), no error, 200 OK | **Regression (now fixed).** The §12 hedge added `fetch_betas` (≤8s) + `fetch_spx_level` (≤10s) **serially**; on an unentitled account each burned its *full* timeout (~20s of dead serial waiting). | **Fixed:** one concurrent `ibkr_client.fetch_hedge_market()` (betas + SPX level + ETF spots in a single bounded wait, grace early-exit) + `hedge_fetch_timeout` (default 5s). Hedge block ~20s → ~4–5s; warm refresh back to ~15–20s. See DESIGN §12 "concurrent hedge-market fetch". |
| `ValueError: no valid option mark price for ...` → that symbol in `warnings[]` | No usable mark (no live data **and** no `close`, e.g. illiquid/just-listed option). | Per-position warning, does **not** sink the request (DESIGN G7). Tolerate or add data entitlement. |
| `There is no current event loop` | asyncio loop missing in the FastAPI worker thread. | Already handled in `connect()` (DESIGN G1). If it recurs, that guard regressed. |
| Browser shows broken icons, API is 200 | `iconUrl` not served over HTTP. | Icons are mounted at `/icons` (DESIGN G6); check `StaticFiles` mount + `icon_cache/`. |

## 4. The clientId-collision bug (worked example — keep as a template)

Textbook case of systematic debugging beating a guess ("gateway must be down").

- **Evidence:** gateway port 4001 *was* listening; a **single** `curl` returned
  **200**; but the log showed `clientId 7 already in use` + `TimeoutError`, and
  two overlapping curls **both** returned `503` after the ~10s connect timeout —
  exactly reproducing the user's error.
- **Root cause:** fixed `clientId` + concurrent connects (StrictMode double-fetch).
- **Reproduce:**
  ```bash
  curl -s -o /dev/null -w "A %{http_code}\n" :8000/api/portfolio & \
  sleep 1; curl -s -o /dev/null -w "B %{http_code}\n" :8000/api/portfolio & wait
  # before fix: both 503  |  after fix: both 200
  ```
- **Fix:** unique clientId per connection with retry in `backend/ibkr_client.py`
  + an in-flight guard in `frontend/src/App.tsx` (don't stack overlapping requests).

## 5. Manual run (for tighter debug loops than start.sh)

```bash
# Backend — from repo ROOT (absolute `from backend import ...` imports)
backend/.venv/bin/python -m uvicorn backend.main:app --port 8000
# Frontend
cd frontend && npm run dev
# Backend unit tests (calc/config/icons/main; NOT ibkr_client — needs live gw)
backend/.venv/bin/pytest backend/tests/
```

`ibkr_client.py` has no unit tests by design (needs a live gateway), so verify
I/O-layer changes with the live `curl` reproductions above, not pytest.

## 6. Gotchas index

The hard-won I/O lessons live in [`DESIGN.md`](DESIGN.md) §7 (G1–G8). Read them
before editing `ibkr_client.py` / `main.py`.
