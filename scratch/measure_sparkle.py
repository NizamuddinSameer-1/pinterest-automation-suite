"""
Measure the true bounding box of the Flow sparkle watermark.

The sparkle is a bright semi-transparent overlay, so it is found by
subtracting a large-sigma local background inside the bottom-right corner
box and looking for a compact bright blob. Restricted to the known corner,
this does not over-detect on general image content.

Usage:  python scratch/measure_sparkle.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

OUTPUTS = Path("data/outputs")

#: Search window (fractions of the full render) - generous, but corner-only.
WIN_X0, WIN_Y0 = 0.66, 0.76

#: Blob threshold on the background-subtracted luminance (0-255 scale).
THRESH = 7.0
MIN_AREA = 150


def sparkle_box(path: Path) -> tuple[float, float, float, float] | None:
    """Return (x0, y0, x1, y1) as fractions of the full image, or None."""
    with Image.open(path) as im:
        gray = np.asarray(im.convert("L"), dtype=np.float32)
    h, w = gray.shape

    x0, y0 = int(WIN_X0 * w), int(WIN_Y0 * h)
    win = gray[y0:, x0:]
    if win.size < 1000:
        return None

    bg = ndimage.gaussian_filter(win, sigma=15.0)
    diff = win - bg

    mask = diff > THRESH
    if not mask.any():
        return None

    labels, n = ndimage.label(mask)
    if n == 0:
        return None

    # Largest connected blob wins.
    sizes = ndimage.sum(mask, labels, range(1, n + 1))
    best = int(np.argmax(sizes)) + 1
    if sizes[best - 1] < MIN_AREA:
        return None

    ys, xs = np.where(labels == best)
    ax0, ax1 = xs.min() + x0, xs.max() + x0
    ay0, ay1 = ys.min() + y0, ys.max() + y0

    return (ax0 / w, ay0 / h, ax1 / w, ay1 / h)


def main() -> None:
    buckets: dict[tuple[int, int], list[Path]] = {}
    for d in OUTPUTS.iterdir():
        if d.is_dir():
            for f in d.glob("*.jpg"):
                try:
                    with Image.open(f) as im:
                        size = im.size
                except Exception:
                    continue
                buckets.setdefault(size, []).append(f)

    # Only uncropped raw renders carry the watermark.
    raws = sorted(buckets.get((768, 1376), []))
    print("raw 768x1376 renders:", len(raws))
    print()

    found = []
    for f in raws[:40]:
        try:
            box = sparkle_box(f)
        except Exception:
            continue
        if box:
            found.append(box)

    print("detected sparkle in %d/%d sampled renders" % (len(found), min(40, len(raws))))
    if not found:
        return

    arr = np.array(found)
    names = ["x0", "y0", "x1", "y1"]
    print()
    print("%-6s %8s %8s %8s" % ("edge", "min", "median", "max"))
    print("-" * 36)
    for i, nm in enumerate(names):
        col = arr[:, i]
        print("%-6s %8.4f %8.4f %8.4f" % (nm, col.min(), np.median(col), col.max()))

    print()
    x0, y0 = arr[:, 0].min(), arr[:, 1].min()
    x1, y1 = arr[:, 2].max(), arr[:, 3].max()
    print("union box : x %.3f-%.3f   y %.3f-%.3f" % (x0, x1, y0, y1))
    print("width  = %.1f%% of W" % ((x1 - x0) * 100))
    print("height = %.1f%% of H" % ((y1 - y0) * 100))
    print()

    # What crop depth is needed to clear the top of the sparkle?
    top = arr[:, 1].min()
    needed = 1.0 - top
    print("to remove the sparkle entirely, the bottom crop must be >= %.1f%% of H" % (needed * 100))
    print("current single-pass crop                     =  %.1f%% of H" % (120 / 1376 * 100))
    print("current double-pass crop (1 - 0.913^2)       =  %.1f%% of H" % ((1 - (1256 / 1376) * (1146 / 1256)) * 100))


if __name__ == "__main__":
    main()
