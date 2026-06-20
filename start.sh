#!/usr/bin/env bash
#
# Start the IBKR pie-chart dashboard: FastAPI backend + Vite frontend, then
# open the dashboard in the default browser.
#
# Each service is launched so a precise, greppable token appears in its
# process command line, letting stop.sh target it exactly without catching
# unrelated python/node/vite processes:
#
#   ibkr_piechart_backend    -> uvicorn serving backend.main:app  (port 8000)
#   ibkr_piechart_frontend   -> vite dev server                   (port 5174)
#
# Naming mechanics differ by runtime: the frontend (node) takes its name from
# `exec -a` (argv[0]); the backend cannot, because macOS framework Python
# re-execs into Python.app and drops argv[0] — so the backend name is passed
# as a trailing marker arg, which survives the re-exec and shows up in `ps`.
#
# Idempotent: re-running skips whichever service is already up.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

BACKEND_NAME="ibkr_piechart_backend"
FRONTEND_NAME="ibkr_piechart_frontend"
BACKEND_PORT=8000
FRONTEND_PORT=5174
LOG_DIR="${ROOT}/logs"
BACKEND_LOG="${LOG_DIR}/${BACKEND_NAME}.log"
FRONTEND_LOG="${LOG_DIR}/${FRONTEND_NAME}.log"
URL="http://localhost:${FRONTEND_PORT}"

mkdir -p "$LOG_DIR"

# --- IB Gateway reachability hint (non-fatal) ---------------------------------
if ! nc -z 127.0.0.1 4001 2>/dev/null; then
  echo "NOTE: nothing is listening on 127.0.0.1:4001 — start and log in to"
  echo "      IB Gateway (IB API mode, port 4001) or the dashboard will show a"
  echo "      connection error when you refresh."
fi

# --- Backend ------------------------------------------------------------------
if pgrep -f "$BACKEND_NAME" >/dev/null; then
  echo "backend already running (pid $(pgrep -f "$BACKEND_NAME" | tr '\n' ' '))"
else
  echo "starting backend on :${BACKEND_PORT} ..."
  # Trailing "$BACKEND_NAME" is an unused argv marker so the process is
  # greppable by name; it survives framework Python's re-exec (argv[0] does not).
  PYCODE="import uvicorn; uvicorn.run('backend.main:app', host='127.0.0.1', port=${BACKEND_PORT})"
  ( exec backend/.venv/bin/python -c "$PYCODE" "$BACKEND_NAME" ) >"$BACKEND_LOG" 2>&1 &
fi

for _ in $(seq 1 30); do
  curl -sf "http://127.0.0.1:${BACKEND_PORT}/docs" >/dev/null 2>&1 && break
  sleep 0.5
done
if curl -sf "http://127.0.0.1:${BACKEND_PORT}/docs" >/dev/null 2>&1; then
  echo "backend ready  (log: ${BACKEND_LOG})"
else
  echo "WARNING: backend did not become ready — see ${BACKEND_LOG}"
fi

# --- Frontend -----------------------------------------------------------------
if pgrep -f "$FRONTEND_NAME" >/dev/null; then
  echo "frontend already running (pid $(pgrep -f "$FRONTEND_NAME" | tr '\n' ' '))"
else
  echo "starting frontend on :${FRONTEND_PORT} ..."
  ( cd frontend && exec -a "$FRONTEND_NAME" node node_modules/vite/bin/vite.js \
      --port "$FRONTEND_PORT" --strictPort ) >"$FRONTEND_LOG" 2>&1 &
fi

for _ in $(seq 1 40); do
  curl -sf "$URL" >/dev/null 2>&1 && break
  sleep 0.5
done
if curl -sf "$URL" >/dev/null 2>&1; then
  echo "frontend ready (log: ${FRONTEND_LOG})"
else
  echo "WARNING: frontend did not become ready — see ${FRONTEND_LOG}"
fi

# --- Open browser -------------------------------------------------------------
echo "opening ${URL}"
open "$URL" 2>/dev/null || echo "open the dashboard manually: ${URL}"

echo
echo "Stop everything with: ./stop.sh"
