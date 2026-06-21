from backend import cache


def test_load_returns_none_when_no_cache_file(tmp_path):
    assert cache.load_portfolio(tmp_path / "missing.json") is None


def test_save_then_load_roundtrips_and_marks_stale(tmp_path):
    path = tmp_path / "portfolio_cache.json"
    payload = {"nlv": 1000.0, "positions": [{"label": "TSLA"}], "stale": False, "cachedAt": "2026-06-21T08:00:00+08:00"}
    cache.save_portfolio(payload, path)

    loaded = cache.load_portfolio(path)
    assert loaded is not None
    # The fallback read always flips stale True but preserves the original time.
    assert loaded["stale"] is True
    assert loaded["cachedAt"] == "2026-06-21T08:00:00+08:00"
    assert loaded["nlv"] == 1000.0
    assert loaded["positions"][0]["label"] == "TSLA"


def test_load_returns_none_on_corrupt_cache(tmp_path):
    path = tmp_path / "portfolio_cache.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert cache.load_portfolio(path) is None


def test_now_iso_is_parseable_with_offset():
    from datetime import datetime
    parsed = datetime.fromisoformat(cache.now_iso())
    assert parsed.tzinfo is not None
