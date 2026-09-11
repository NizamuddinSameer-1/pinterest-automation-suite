"""
Visual proof of the watermark corner.

Renders the bottom-right corner of several renders side by side at 2x zoom,
so the sparkle (or its absence) is unambiguous to the eye.

Usage:  python scratch/corner_strip.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUTPUTS = Path("data/outputs")
ZOOM = 2
X0, X1 = 0.68, 1.00
Y0, Y1 = 0.82, 1.00


def collect() -> dict[tuple[int, int], list[Path]]:
    buckets: dict[tuple[int, int], list[Path]] = {}
    for d in OUTPUTS.iterdir():
        if not d.is_dir():
            continue
        for f in d.glob("*.jpg"):
            try:
                with Image.open(f) as im:
                    size = im.size
            except Exception:
                continue
            buckets.setdefault(size, []).append(f)
    return buckets


def strip(files: list[Path], out: Path, title: str) -> None:
    tiles = []
    for f in files:
        with Image.open(f) as im:
            im = im.convert("RGB")
            w, h = im.size
            box = im.crop((int(X0 * w), int(Y0 * h), int(X1 * w), int(Y1 * h)))
            tw, th = box.size[0] * ZOOM, box.size[1] * ZOOM
            tiles.append((f, box.resize((tw, th), Image.Resampling.NEAREST)))

    if not tiles:
        print("no tiles for", title)
        return

    tw, th = tiles[0][1].size
    gap, pad = 6, 30
    canvas = Image.new("RGB", (len(tiles) * tw + (len(tiles) - 1) * gap, th + pad), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    draw.text((4, 8), title, fill=(0, 0, 0))

    for i, (f, tile) in enumerate(tiles):
        x = i * (tw + gap)
        canvas.paste(tile, (x, pad))
        draw.text((x + 4, pad + 4), f"{f.parent.name[:8]} {f.stat().st_size // 1024}KB", fill=(255, 0, 0))

    canvas.save(out)
    print("wrote", out, canvas.size)


def main() -> None:
    buckets = collect()
    for dims, out, title in [
        ((768, 1376), Path("scratch/_corner_raw_768.png"), "768x1376  (0 crops - raw render)"),
        ((1440, 2150), Path("scratch/_corner_proc_1440.png"), "1440x2150  (2 crops - current output)"),
    ]:
        files = sorted(buckets.get(dims, []))[:4]
        strip(files, out, title)


if __name__ == "__main__":
    main()
