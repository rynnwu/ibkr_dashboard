"""On-disk cache of the last good portfolio payload.

Purpose: when IB Gateway is unreachable (connect fails, or the fetch errors
out), the dashboard should still show the *most recent* successful snapshot
instead of only an error state. This module is the single place that reads and
writes that snapshot. It does no IBKR I/O and has no other dependencies, so it
stays trivially unit-testable.

The cached file is the exact `/api/portfolio` response dict as last served
live, with `stale: false` / `cachedAt: <when it was fetched>` already baked in.
On a fallback read we flip `stale` to true but keep the original `cachedAt`, so
the frontend can tell the user how old the data is.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).parent / "portfolio_cache.json"


def save_portfolio(payload: dict, path: Path = CACHE_PATH) -> None:
    """Persists a freshly-fetched portfolio payload as the latest snapshot.

    Best-effort: a cache write failure must never break a successful request,
    so any error is logged and swallowed."""
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        logger.exception("Failed to write portfolio cache to %s", path)


def load_portfolio(path: Path = CACHE_PATH) -> dict | None:
    """Returns the cached payload flagged as stale, or None if no usable cache.

    `stale` is forced to True and the original `cachedAt` is preserved so the
    caller/frontend can show "資料來自快照 · <time>"."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        logger.exception("Failed to read portfolio cache from %s", path)
        return None
    payload["stale"] = True
    return payload


def now_iso() -> str:
    """Local-time ISO 8601 timestamp (seconds precision) for `cachedAt`."""
    return datetime.now().astimezone().isoformat(timespec="seconds")
