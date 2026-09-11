"""
Corner-targeted watermark test.

The sparkle sits bottom-right. Instead of scanning the whole image (which
over-detects on bright content), measure a *background-subtracted blob
strength* inside the bottom-right corner box and compare it against the
mirrored bottom-left box on the same image. Content cancels out; a present
watermark does not.

Usage:  python scratch/watermark_corner_test.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

OUTPUTS = Path("data/outputs")

#: Sparkle geometry, as a fraction of the full render.
BR_X0, BR_X1 = 0.72, 0.98
BR_Y0, BR_Y1 = 0.86, 1.00
BL_X0, BL_X1 = 0.02, 0.28


def _blob_strength(gray: np.ndarray, y0: int, y1: int, x0: int, x1: int) -> float:
    """Peak brightness above the local background inside a box."""
    box = gray[y0:y1, x0:x1]
    if box.size < 64:
        return 0.0
    bg = ndimage.gaussian_filter(box, sigma=6.0)
    return float(np.max(box - bg))


def score(path: Path) -> tuple[float, float, float]:
    """Return (right_corner, left_corner, delta) for one image."""
    with Image.open(path) as im:
        gray = np.asarray(im.convert("L"), dtype=np.float32)
    h, w = gray.shape

    ry0, ry1 = int(BR_Y0 * h), int(BR_Y1 * h)
    rx0, rx1 = int(BR_X0 * w), int(BR_X1 * w)
    lx0, lx1 = int(BL_X0 * w), int(BL_X1 * w)

    right = _blob_strength(gray, ry0, ry1, rx0, rx1)
    left = _blob_strength(gray, ry0, ry1, lx0, lx1)
    return right, left, right - left


def main() -> int:
    if not OUTPUTS.is_dir():
        print("no data/outputs directory", file=sys.stderr)
        return 1

    # Bucket every output by its exact dimensions, then sample each bucket.
    buckets: dict[tuple[int, int], list[Path]] = defaultdict(list)
    for d in OUTPUTS.iterdir():
        if d.is_dir():
            for f in d.glob("*.jpg"):
                try:
                    with Image.open(f) as im:
                        buckets[im.size].append(f)
                except Exception:
                    continue

    order = sorted(buckets, key=lambda s: -len(buckets[s]))[:7]

    print("=" * 78)
    print("WATERMARK CORNER TEST  (delta = bottom-right blob minus bottom-left blob)")
    print("A visible sparkle gives a large positive delta. Negative/near-zero = clean.")
    print("=" * 78)
    print()
    print("%-13s %5s %9s %9s %9s  %s" % ("dims", "n", "right", "left", "delta", "verdict"))
    print("-" * 78)

    for dims in order:
        files = buckets[dims][:12]
        deltas = []
        for f in files:
            try:
                _, _, d = score(f)
                deltas.append(d)
            except Exception:
                continue
        if not deltas:
            continue
        med = float(np.median(deltas))
        r = float(np.median([score(f)[0] for f in files[:6]]))
        l = float(np.median([score(f)[1] for f in files[:6]]))
        verdict = "WATERMARK PRESENT" if med > 12 else ("clean" if med < 6 else "ambiguous")
        print("%-13s %5d %9.1f %9.1f %9.1f  %s" % (
            "%dx%d" % dims, len(buckets[dims]), r, l, med, verdict))

    print()
    print("Interpretation:")
    print("  uncropped raw renders -> PRESENT")
    print("  band-cropped outputs  -> clean  (crop is doing its job)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
