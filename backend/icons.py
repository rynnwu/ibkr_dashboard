"""Per-symbol icon fetch/cache and color derivation.

Network calls go through an injectable `getter` so tests never hit the
real logo API. See get_icon_and_color() for the orchestration entrypoint
used by main.py.
"""
import hashlib
import io
import json
from pathlib import Path

import requests
from PIL import Image, ImageDraw

CACHE_DIR = Path(__file__).parent / "icon_cache"
LOGO_URL_TEMPLATE = "https://images.financialmodelingprep.com/symbol/{symbol}.png"


def hash_color(symbol: str) -> str:
    digest = hashlib.sha256(symbol.encode()).hexdigest()
    return f"#{digest[:6]}"


def extract_dominant_color(image_bytes: bytes) -> str:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    r, g, b = img.resize((1, 1)).getpixel((0, 0))
    return f"#{r:02x}{g:02x}{b:02x}"


def generate_text_fallback_icon(symbol: str, color: str) -> bytes:
    size = 64
    img = Image.new("RGB", (size, size), color)
    draw = ImageDraw.Draw(img)
    text = symbol[:4].upper()
    bbox = draw.textbbox((0, 0), text)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - text_w) / 2 - bbox[0]
    y = (size - text_h) / 2 - bbox[1]
    draw.text((x, y), text, fill="#ffffff")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def fetch_logo_bytes(symbol: str, api_key: str, getter=requests.get) -> bytes | None:
    # The logo provider (images.financialmodelingprep.com) needs no API key,
    # but api_key is kept as a gate for backward compatibility: callers that
    # have no key configured get the text-fallback icon instead of a fetch
    # attempt.
    if not api_key:
        return None
    try:
        resp = getter(LOGO_URL_TEMPLATE.format(symbol=symbol), timeout=5)
    except requests.RequestException:
        return None
    if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image"):
        return resp.content
    return None


def get_icon_and_color(
    symbol: str,
    api_key: str,
    cache_dir: Path = CACHE_DIR,
    getter=requests.get,
) -> tuple[str, str]:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    icon_path = cache_dir / f"{symbol}.png"
    colors_path = cache_dir / "colors.json"
    colors = json.loads(colors_path.read_text()) if colors_path.exists() else {}

    if icon_path.exists() and symbol in colors:
        return str(icon_path), colors[symbol]

    logo_bytes = fetch_logo_bytes(symbol, api_key, getter)
    if logo_bytes:
        try:
            color = extract_dominant_color(logo_bytes)
            icon_path.write_bytes(logo_bytes)
        except Exception:
            logo_bytes = None
    if not logo_bytes:
        color = hash_color(symbol)
        icon_path.write_bytes(generate_text_fallback_icon(symbol, color))

    colors[symbol] = color
    colors_path.write_text(json.dumps(colors))
    return str(icon_path), color
