"""
Side-by-side visual comparison: raw render vs old pipeline vs new pipeline.

All three are normalised to the same width, then the most detailed region of
the raw render is cropped from each at the same fractional position and shown
at 2x zoom. The crop is taken from the upper part of the frame, which is not
affected by the bottom watermark crop, so the content lines up across all three.

Usage:  python scratch/compare_visual.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WORK = Path("scratch/_verify")
OUT = Path("scratch/_compare_halo.png")
BOX = 380
ZOOM = 2


def busiest_window(gray: np.ndarray, box: int) -> tuple[int, int]:
    """Top-left corner of the highest-gradient box, in the upper 60% of the frame."""
    g = ndimage.gaussian_filter(gray, 1.0)
    energy = np.hypot(*np.gradient(g))
    h, w = energy.shape
    limit = int(h * 0.60)
    best, best_xy = -1.0, (int(w * 0.1), int(h * 0.1))
    step = max(1, box // 4)
    for y in range(0, limit - box, step):
        for x in range(0, w - box, step):
            score = float(energy[y:y + box, x:x + box].mean())
            if score > best:
                best, best_xy = score, (x, y)
    return best_xy


def main() -> int:
    from app.services.anti_ai_processor import postprocess_image

    raw = None
    for d in Path("data/outputs").iterdir():
        if not d.is_dir():
            continue
        for f in d.glob("*.jpg"):
            try:
                with Image.open(f) as im:
                    if im.size == (768, 1376):
                        raw = f
                        break
            except Exception:
                continue
        if raw:
            break
    if raw is None:
        print("no raw render found")
        return 1

    # Build the three variants.
    #
    # The old pipeline is reproduced locally rather than read from an existing
    # output file: raw renders and processed outputs live in different job
    # folders, so an old output is a different photograph. The reproduction is
    # faithful - it yields 1440x2150 at ~3.9 MB, matching the real files.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from verify_upscale_fix import old_pipeline

    WORK.mkdir(parents=True, exist_ok=True)
    new_path = WORK / "cmp_new.jpg"
    shutil.copy(raw, new_path)
    postprocess_image(new_path)

    old_path = WORK / "cmp_old.jpg"
    old_pipeline(raw, old_path, passes=2)

    width = 1080

    def load(p: Path) -> Image.Image:
        im = Image.open(p).convert("RGB")
        return im.resize((width, round(im.height * width / im.width)), Image.Resampling.LANCZOS)

    variants = [
        ("Raw Flow render", load(raw)),
        ("Old pipeline (2 passes)", load(old_path)),
        ("New pipeline (1 pass)", load(new_path)),
    ]

    # Locate the busiest region on the raw render, scaled into the common width.
    scale = width / 768
    gx, gy = busiest_window(
        np.asarray(Image.open(raw).convert("L"), dtype=np.float32), BOX
    )
    x0, y0 = int(gx * scale), int(gy * scale)

    tiles = []
    for label, im in variants:
        box = im.crop((x0, y0, x0 + BOX, y0 + BOX))
        tiles.append((label, box.resize((BOX * ZOOM, BOX * ZOOM), Image.Resampling.NEAREST)))

    gap, pad = 10, 34
    tw, th = tiles[0][1].size
    canvas = Image.new(
        "RGB", (len(tiles) * tw + (len(tiles) - 1) * gap, th + pad), (255, 255, 255)
    )
    draw = ImageDraw.Draw(canvas)
    for i, (label, tile) in enumerate(tiles):
        x = i * (tw + gap)
        canvas.paste(tile, (x, pad))
        draw.text((x + 6, 10), label, fill=(0, 0, 0))

    canvas.save(OUT)
    print("wrote", OUT, canvas.size)
    print()
    print("Same 380x380 region, 2x zoom, identical position in all three panels.")
    print("Look at the edges: the old panel has a light rim and a dark rim hugging")
    print("every contour. That is the ringing the sharpening produced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
