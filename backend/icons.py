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
LOGO_URL_TEMPLATE = "https://eodhd.com/img/logos/US/{symbol}.png"


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
