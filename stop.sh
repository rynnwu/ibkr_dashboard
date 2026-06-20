#!/usr/bin/env bash
#
# Stop the IBKR pie-chart dashboard. Matches the backend and frontend
# precisely by the ibkr_piechart_* process names set via `exec -a` in
# start.sh, so it never touches unrelated python/node/vite processes.

set -uo pipefail

stopped_any=0
for name in ibkr_piechart_backend ibkr_piechart_frontend; do
  pids="$(pgrep -f "$name" || true)"
  if [ -n "$pids" ]; then
    echo "stopping ${name} (pid: $(echo "$pids" | tr '\n' ' '))"
    pkill -f "$name"
    # Wait for graceful exit (uvicorn handles SIGTERM), then force any straggler.
    for _ in $(seq 1 10); do
      pgrep -f "$name" >/dev/null || break
      sleep 0.5
    done
    if pgrep -f "$name" >/dev/null; then
      echo "  still alive — forcing (SIGKILL)"
      pkill -9 -f "$name"
    fi
    stopped_any=1
  else
    echo "${name} not running"
  fi
done

if [ "$stopped_any" -eq 1 ]; then
  echo "done."
else
  echo "nothing to stop."
fi
