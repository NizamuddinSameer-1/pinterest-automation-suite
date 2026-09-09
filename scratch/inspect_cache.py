"""Inspect bad cache files to understand what's wrong."""
import json
from pathlib import Path

cache_dir = Path("data/pinterest_trends")

bad_files = [
    "deep_dive_fall_hair_color_2026_US.json",
    "deep_dive_fall_nails_2026_trends_US.json",
    "deep_dive_halloween_nails_US.json",
    "deep_dive_sunset_ambient_projection_lamp_US.json",
]

for fname in bad_files:
    f = cache_dir / fname
    try:
        payload = json.loads(f.read_bytes().decode("utf-8", errors="replace"))
        items = payload.get("trends", [])
        if not items:
            print(f"{fname}: empty trends list")
            continue
        item = items[0]
        pins = item.get("popular_pins", [])
        imgs = [p.get("image_url", "")[:80] for p in pins]
        sources = list(dict.fromkeys(p.get("source", "?") for p in pins))
        print(f"{fname}: {len(pins)} pins, sources={sources}")
        unique_imgs = list(dict.fromkeys(imgs))
        print(f"  Unique images: {len(unique_imgs)} / {len(imgs)}")
        for img in imgs[:4]:
            print(f"    - {img}")
        print()
    except Exception as e:
        print(f"{fname}: error {e}")
