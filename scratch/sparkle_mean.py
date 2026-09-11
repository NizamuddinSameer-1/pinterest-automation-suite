"""
Isolate the Flow sparkle by averaging raw renders.

The sparkle is a FIXED overlay at the same pixel position in every render,
while the generated content varies. Averaging many renders therefore keeps
the sparkle sharp and smooths the content into a low-frequency wash, so a
large-sigma background subtraction on the mean isolates the watermark
cleanly - no false positives from bright objects.

Usage:  python scratch/sparkle_mean.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

OUTPUTS = Path("data/outputs")
MEAN_PNG = Path("scratch/_mean_render.png")
CORNER_PNG = Path("scratch/_mean_corner.png")


def raw_renders() -> list[Path]:
    files: list[Path] = []
    for d in OUTPUTS.iterdir():
        if not d.is_dir():
            continue
        for f in d.glob("*.jpg"):
            try:
                with Image.open(f) as im:
                    if im.size == (768, 1376):
                        files.append(f)
            except Exception:
                continue
    return sorted(files)


def main() -> None:
    files = raw_renders()
    print("raw 768x1376 renders:", len(files))
    if len(files) < 8:
        print("not enough samples")
        return

    acc = np.zeros((1376, 768), dtype=np.float64)
    n = 0
    for f in files:
        try:
            with Image.open(f) as im:
                acc += np.asarray(im.convert("L"), dtype=np.float64)
            n += 1
        except Exception:
            continue

    mean = (acc / n).astype(np.float32)
    print("averaged %d renders" % n)

    Image.fromarray(mean.astype(np.uint8)).save(MEAN_PNG)
    print("wrote", MEAN_PNG)

    h, w = mean.shape
    bg = ndimage.gaussian_filter(mean, sigma=25.0)
    diff = mean - bg

    print()
    print("mean-image residual statistics: max %.1f  p99.9 %.1f" % (diff.max(), np.percentile(diff, 99.9)))

    thresh = max(2.0, float(np.percentile(diff, 99.5)))
    mask = diff > thresh
    labels, nlab = ndimage.label(mask)
    print("threshold %.2f -> %d component(s)" % (thresh, nlab))

    if nlab:
        sizes = ndimage.sum(mask, labels, range(1, nlab + 1))
        order = np.argsort(sizes)[::-1]
        print()
        print("%-4s %8s %10s %10s %10s %10s" % ("#", "area", "x0", "y0", "x1", "y1"))
        for rank, idx in enumerate(order[:5], 1):
            ys, xs = np.where(labels == idx + 1)
            print("%-4d %8d %10.3f %10.3f %10.3f %10.3f" % (
                rank, int(sizes[idx]),
                xs.min() / w, ys.min() / h, xs.max() / w, ys.max() / h))

        top = order[0]
        ys, xs = np.where(labels == top + 1)
        y0, y1 = ys.min() / h, ys.max() / h
        x0, x1 = xs.min() / w, xs.max() / w
        print()
        print("SPARKLE BOUNDING BOX (fractions of the full render)")
        print("  x: %.3f - %.3f   (width  %.1f%% of W)" % (x0, x1, (x1 - x0) * 100))
        print("  y: %.3f - %.3f   (height %.1f%% of H)" % (y0, y1, (y1 - y0) * 100))
        print("  centre: (%.3f, %.3f)" % ((x0 + x1) / 2, (y0 + y1) / 2))
        print()
        print("  bottom crop needed to clear it = %.1f%% of H" % ((1 - y0) * 100))

    corner = mean[int(0.72 * h):, int(0.60 * w):]
    corner = np.clip(corner * 1.8, 0, 255).astype(np.uint8)
    Image.fromarray(corner).resize(
        (corner.shape[1] * 2, corner.shape[0] * 2), Image.Resampling.NEAREST
    ).save(CORNER_PNG)
    print()
    print("wrote", CORNER_PNG)


if __name__ == "__main__":
    main()
