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
    # Cushion (ExcessLiquidity / NLV) levels below which the margin card flips to
    # warning / danger. Defaults mirror config.json's margin_thresholds block.
    margin_warning_cushion: float = 0.20
    margin_danger_cushion: float = 0.10
    # SPX-put hedge defaults (see DESIGN §12). target_put_delta/target_dte select
    # the hedge put; assumed_iv is the model-fallback vol; warning_leverage is the
    # beta-weighted leverage above which the hedge banner shows. target_leverage is
    # the default sizing goal: the minimum hedge that brings post-hedge leverage
    # at/under it (1.0× NLV); target_dte caps the expiry near-dated (≤30 DTE).
    spx_target_put_delta: float = 0.30
    spx_floor_put_delta: float = 0.12  # lower (short) put leg for vertical/seagull
    spx_target_dte: int = 30
    spx_assumed_iv: float = 0.20
    spx_hedge_fraction: float = 1.0
    spx_target_leverage: float = 1.0
    spx_dividend_yield: float = 0.013
    spx_warning_leverage: float = 1.5
    # Candidate hedge ETFs (SPY/QQQ/SMH/…) for the "which ETF fits the book best"
    # comparison (DESIGN §13). Each spec: {symbol,label,broad,defaultBeta,betas}.
    # concentration_threshold is the coverage above which a sector ETF is preferred
    # over the broad market as the suggested hedge.
    hedge_etf_specs: list = field(default_factory=list)
    hedge_concentration_threshold: float = 0.6
    # Single bounded-wait ceiling for the concurrent hedge-market fetch (betas +
    # SPX level + ETF spots). Kept short because on an unentitled account those
    # ticks never arrive and the wait can't early-exit — see DEBUG §1d.
    hedge_fetch_timeout: float = 5.0
    _dividend_yield: dict = field(default_factory=dict)
    _beta_overrides: dict = field(default_factory=dict)

    def dividend_yield_for(self, symbol: str) -> float:
        return self._dividend_yield.get(symbol, 0.0)

    def beta_for(self, symbol: str) -> float | None:
        """Configured beta override for an underlying, or None if unset (the
        caller then falls back to IBKR's fundamental beta, then to 1.0)."""
        return self._beta_overrides.get(symbol)


def load_config(path: Path) -> Config:
    raw = json.loads(Path(path).read_text())
    gateway = raw["ib_gateway"]
    logo = raw["logo_api"]
    margin = raw.get("margin_thresholds", {})
    hedge = raw.get("spx_hedge", {})
    hedge_etfs = raw.get("hedge_etfs", {})
    return Config(
        leveraged_etf_map=raw.get("leveraged_etf_map", {}),
        risk_free_rate=raw["risk_free_rate"],
        hedge_fetch_timeout=raw.get("hedge_fetch_timeout", 5.0),
        ib_gateway_host=gateway["host"],
        ib_gateway_port=gateway["port"],
        ib_gateway_client_id=gateway["client_id"],
        logo_api_provider=logo.get("provider", ""),
        logo_api_key=logo.get("api_key", ""),
        margin_warning_cushion=margin.get("warning_cushion", 0.20),
        margin_danger_cushion=margin.get("danger_cushion", 0.10),
        spx_target_put_delta=hedge.get("target_put_delta", 0.30),
        spx_floor_put_delta=hedge.get("floor_put_delta", 0.12),
        spx_target_dte=hedge.get("target_dte", 30),
        spx_assumed_iv=hedge.get("assumed_iv", 0.20),
        spx_hedge_fraction=hedge.get("hedge_fraction", 1.0),
        spx_target_leverage=hedge.get("target_leverage", 1.0),
        spx_dividend_yield=hedge.get("spx_dividend_yield", 0.013),
        spx_warning_leverage=hedge.get("warning_leverage", 1.5),
        hedge_etf_specs=hedge_etfs.get("candidates", []),
        hedge_concentration_threshold=hedge_etfs.get("concentration_threshold", 0.6),
        _dividend_yield=raw.get("dividend_yield", {}),
        _beta_overrides=raw.get("beta_overrides", {}),
    )
