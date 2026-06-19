import io
import re
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
