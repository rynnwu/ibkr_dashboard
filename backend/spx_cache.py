"""On-disk cache of the latest live SPX market inputs for the hedge what-if.

Why this exists: the SPX-hedge proposals (DESIGN §12) need a live SPX index
level, the option-chain expirations/strikes, and a vol to model-price the legs.
Re-connecting to IB Gateway on every hedge what-if (each parameter tweak /
strategy switch) is slow and re-opens a socket. Instead the **portfolio refresh**
— which already holds a live connection — snapshots these inputs here, and the
hedge endpoint recomputes the proposals from this cache with *no* IBKR I/O. When
the gateway has never been up this session, the endpoint degrades to model
pricing off a client-supplied SPX level.

No IBKR I/O, no other dependencies → trivially unit-testable. Best-effort writes
(a cache failure must never break the portfolio refresh).

Cached shape:
    {"spxLevel": float, "expirations": [YYYYMMDD...], "strikes": [float...],
     "iv": float (decimal, e.g. 0.18), "source": "live"|"model",
     "cachedAt": "<local ISO 8601>"}
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).parent / "spx_hedge_cache.json"


def save_spx(payload: dict, path: Path = CACHE_PATH) -> None:
    """Persist the latest live SPX market inputs. Best-effort: any error is
    logged and swallowed so it can never break a successful portfolio refresh."""
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        logger.exception("Failed to write SPX hedge cache to %s", path)


def load_spx(path: Path = CACHE_PATH) -> dict | None:
    """Return the cached SPX market inputs, or None if no usable cache."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        logger.exception("Failed to read SPX hedge cache from %s", path)
        return None
