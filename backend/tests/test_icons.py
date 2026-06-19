import io
import re
from pathlib import Path
from PIL import Image
from backend import icons


def test_hash_color_is_deterministic():
    assert icons.hash_color("TSLA") == icons.hash_color("TSLA")


def test_hash_color_format_is_hex():
    assert re.fullmatch(r"#[0-9a-f]{6}", icons.hash_color("TSLA"))


def test_hash_color_differs_for_different_symbols():
    assert icons.hash_color("TSLA") != icons.hash_color("GOOG")


def test_extract_dominant_color_on_solid_red_image():
    img = Image.new("RGB", (32, 32), (255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    color = icons.extract_dominant_color(buf.getvalue())
    assert color == "#ff0000"


def test_generate_text_fallback_icon_is_valid_png():
    png_bytes = icons.generate_text_fallback_icon("TSLA", "#336699")
    img = Image.open(io.BytesIO(png_bytes))
    assert img.format == "PNG"
    assert img.size == (64, 64)


def test_generate_text_fallback_icon_renders_text_near_center():
    png_bytes = icons.generate_text_fallback_icon("TSLA", "#336699")
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    bg = img.getpixel((1, 1))  # corner pixel is background, no text there
    center_box = [img.getpixel((x, y)) for x in range(24, 41) for y in range(24, 41)]
    assert any(pixel != bg for pixel in center_box), "expected white text pixels near the center"


class _FakeResponse:
    def __init__(self, status_code, content=b"", content_type="image/png"):
        self.status_code = status_code
        self.content = content
        self.headers = {"content-type": content_type}


def _solid_png(color=(0, 255, 0)):
    img = Image.new("RGB", (8, 8), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_fetch_logo_bytes_returns_none_without_api_key():
    assert icons.fetch_logo_bytes("TSLA", api_key="", getter=lambda *a, **k: _FakeResponse(200)) is None


def test_fetch_logo_bytes_returns_image_on_200(monkeypatch):
    png = _solid_png()
    result = icons.fetch_logo_bytes("TSLA", api_key="key", getter=lambda *a, **k: _FakeResponse(200, png))
    assert result == png


def test_fetch_logo_bytes_returns_none_on_404():
    result = icons.fetch_logo_bytes("ZZZZ", api_key="key", getter=lambda *a, **k: _FakeResponse(404))
    assert result is None


def test_get_icon_and_color_uses_fetched_logo_when_available(tmp_path):
    png = _solid_png((0, 255, 0))
    calls = {"n": 0}

    def fake_getter(*a, **k):
        calls["n"] += 1
        return _FakeResponse(200, png)

    path, color = icons.get_icon_and_color("NVDA", api_key="key", cache_dir=tmp_path, getter=fake_getter)
    assert color == "#00ff00"
    assert Path(path).exists()
    assert calls["n"] == 1


def test_get_icon_and_color_caches_and_does_not_refetch(tmp_path):
    png = _solid_png((0, 0, 255))
    calls = {"n": 0}

    def fake_getter(*a, **k):
        calls["n"] += 1
        return _FakeResponse(200, png)

    icons.get_icon_and_color("META", api_key="key", cache_dir=tmp_path, getter=fake_getter)
    icons.get_icon_and_color("META", api_key="key", cache_dir=tmp_path, getter=fake_getter)
    assert calls["n"] == 1


def test_get_icon_and_color_falls_back_to_text_icon_when_fetch_fails(tmp_path):
    path, color = icons.get_icon_and_color(
        "ZZZZ", api_key="key", cache_dir=tmp_path, getter=lambda *a, **k: _FakeResponse(404)
    )
    assert color == icons.hash_color("ZZZZ")
    assert Path(path).exists()
