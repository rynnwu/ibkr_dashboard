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
    _dividend_yield: dict = field(default_factory=dict)

    def dividend_yield_for(self, symbol: str) -> float:
        return self._dividend_yield.get(symbol, 0.0)


def load_config(path: Path) -> Config:
    raw = json.loads(Path(path).read_text())
    gateway = raw["ib_gateway"]
    logo = raw["logo_api"]
    margin = raw.get("margin_thresholds", {})
    return Config(
        leveraged_etf_map=raw.get("leveraged_etf_map", {}),
        risk_free_rate=raw["risk_free_rate"],
        ib_gateway_host=gateway["host"],
        ib_gateway_port=gateway["port"],
        ib_gateway_client_id=gateway["client_id"],
        logo_api_provider=logo.get("provider", ""),
        logo_api_key=logo.get("api_key", ""),
        margin_warning_cushion=margin.get("warning_cushion", 0.20),
        margin_danger_cushion=margin.get("danger_cushion", 0.10),
        _dividend_yield=raw.get("dividend_yield", {}),
    )
