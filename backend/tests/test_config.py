import json
import pytest
from backend import config


def test_load_config_reads_known_keys(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "leveraged_etf_map": {"TSLL": {"underlying": "TSLA", "multiplier": 2}},
        "dividend_yield": {"GOOG": 0.005},
        "risk_free_rate": 0.0425,
        "ib_gateway": {"host": "127.0.0.1", "port": 4001, "client_id": 7},
        "logo_api": {"provider": "eodhd", "api_key": "abc"},
    }))
    cfg = config.load_config(cfg_path)
    assert cfg.risk_free_rate == 0.0425
    assert cfg.ib_gateway_host == "127.0.0.1"
    assert cfg.ib_gateway_port == 4001
    assert cfg.ib_gateway_client_id == 7
    assert cfg.leveraged_etf_map["TSLL"] == {"underlying": "TSLA", "multiplier": 2}
    assert cfg.logo_api_key == "abc"


def test_dividend_yield_defaults_to_zero_for_unknown_symbol(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "leveraged_etf_map": {},
        "dividend_yield": {"GOOG": 0.005},
        "risk_free_rate": 0.0425,
        "ib_gateway": {"host": "127.0.0.1", "port": 4001, "client_id": 7},
        "logo_api": {"provider": "eodhd", "api_key": ""},
    }))
    cfg = config.load_config(cfg_path)
    assert cfg.dividend_yield_for("GOOG") == 0.005
    assert cfg.dividend_yield_for("AAPL") == 0.0


def test_margin_thresholds_default_when_absent(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "leveraged_etf_map": {},
        "risk_free_rate": 0.0425,
        "ib_gateway": {"host": "127.0.0.1", "port": 4001, "client_id": 7},
        "logo_api": {"provider": "eodhd", "api_key": ""},
    }))
    cfg = config.load_config(cfg_path)
    assert cfg.margin_warning_cushion == 0.20
    assert cfg.margin_danger_cushion == 0.10


def test_margin_thresholds_read_from_config(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "leveraged_etf_map": {},
        "risk_free_rate": 0.0425,
        "ib_gateway": {"host": "127.0.0.1", "port": 4001, "client_id": 7},
        "logo_api": {"provider": "eodhd", "api_key": ""},
        "margin_thresholds": {"warning_cushion": 0.30, "danger_cushion": 0.15},
    }))
    cfg = config.load_config(cfg_path)
    assert cfg.margin_warning_cushion == 0.30
    assert cfg.margin_danger_cushion == 0.15
