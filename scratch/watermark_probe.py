"""
Watermark probe — find Google Flow's sparkle watermark and measure its geometry.

The pipeline currently crops 8.7% of the image HEIGHT across the FULL WIDTH to remove
a watermark that is actually a small four-pointed sparkle in one corner. This probe
establishes where the mark really is and how big it is, so the crop can be replaced
with something that does not throw away a band of real photograph.

Method: the mark is a semi-transparent bright overlay. A large median filter estimates
the background underneath it, and the mark shows up as a strong positive residual.
Connected-component labelling over that residual in the lower part of the frame gives
a bounding box per image.

Run: python -m scratch.watermark_probe
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def raw_renders(limit: int | None = None) -> list[Path]:
    """
    Unprocessed Flow renders.

    The post-processor resizes every image into a 1440x2560 box and crops the bottom,
    so a processed file cannot tell you what was removed. 768x1376 is the untouched
    render size (9:16) and is the most common size on disk.
    """
    out: list[Path] = []
    for d in sorted((ROOT / "data" / "outputs").iterdir()):
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.jpg")):
            try:
                with Image.open(f) as im:
                    if im.size == (768, 1376):
                        out.append(f)
            except Exception:
                continue
    return out[:limit] if limit else out


def _background(g: np.ndarray, down: int = 4, sigma: float = 10.0) -> np.ndarray:
    """
    Wide low-pass background estimate, computed on a downscaled copy.

    A Gaussian wide enough to reject the sparkle needs sigma ~45px at full size, and
    the default 4-sigma truncation then builds a 368px kernel — which is far too slow
    per image. Estimating on a 1/down copy makes the kernel 1/down the size at 1/down^2
    the pixels, then the estimate is scaled back up.
    """
    h, w = g.shape
    small = g[::down, ::down]
    bg_small = ndimage.gaussian_filter(small, sigma=sigma)
    return np.asarray(
        Image.fromarray(bg_small.astype(np.float32)).resize((w, h), Image.Resampling.BILINEAR),
        dtype=np.float32,
    )


def find_mark(path: Path, *, min_contrast: float = 10.0) -> dict | None:
    """
    Bounding box of the sparkle, in pixels and as fractions of the image.

    `min_contrast` is deliberately low: the mark is semi-transparent, so over a dark
    background it is faint. False positives are controlled by requiring a compact
    blob (the sparkle is roughly as tall as it is wide) rather than by raising the
    threshold, which would simply miss marks on dark backgrounds.
    """
    with Image.open(path) as im:
        g = np.asarray(im.convert("L"), dtype=np.float32)
    h, w = g.shape

    resid = g - _background(g)

    # Only the lower 30% of the frame can contain the mark.
    y_start = int(h * 0.70)
    band = resid[y_start:, :]
    mask = band > min_contrast

    labels, n = ndimage.label(mask)
    if n == 0:
        return None

    best = None
    for i in range(1, n + 1):
        ys, xs = np.nonzero(labels == i)
        if ys.size < 60:            # too small to be the sparkle
            continue
        bw = xs.max() - xs.min() + 1
        bh = ys.max() - ys.min() + 1
        # The sparkle is a compact star: roughly square, not a long edge or a
        # bright streak along the frame border.
        aspect = bw / bh if bh else 99
        if not (0.35 <= aspect <= 3.0):
            continue
        if bw > w * 0.45 or bh > h * 0.30:
            continue
        density = ys.size / float(bw * bh)
        if density < 0.05:
            continue
        score = ys.size * density
        if best is None or score > best[0]:
            best = (score, xs.min(), ys.min() + y_start, xs.max(), ys.max() + y_start)

    if best is None:
        return None

    _, x0, y0, x1, y1 = best
    return {
        "px": (int(x0), int(y0), int(x1), int(y1)),
        "frac": (x0 / w, y0 / h, (x1 + 1) / w, (y1 + 1) / h),
        "size": (int(x1 - x0 + 1), int(y1 - y0 + 1)),
        "w": w,
        "h": h,
    }


def main() -> int:
    files = raw_renders()
    if not files:
        print("no 768x1376 raw renders found")
        return 1

    print("=" * 100)
    print("WATERMARK PROBE — 768x1376 raw Flow renders")
    print("=" * 100)
    print(f"{len(files)} raw render(s)\n")

    hits, misses = [], 0
    for f in files:
        r = find_mark(f)
        if r is None:
            misses += 1
            continue
        hits.append(r)

    print(f"detected : {len(hits)}/{len(files)}  ({len(hits) / len(files) * 100:.0f}%)")
    print(f"missed   : {misses}")

    if not hits:
        print("\nno marks detected — the detector needs revisiting")
        return 1

    xs0 = [r["frac"][0] for r in hits]
    ys0 = [r["frac"][1] for r in hits]
    xs1 = [r["frac"][2] for r in hits]
    ys1 = [r["frac"][3] for r in hits]
    ws = [r["size"][0] for r in hits]
    hs = [r["size"][1] for r in hits]

    print()
    print("bounding box as a fraction of the image:")
    print(f"  x0  min {min(xs0):.3f}  mean {statistics.mean(xs0):.3f}  max {max(xs0):.3f}")
    print(f"  y0  min {min(ys0):.3f}  mean {statistics.mean(ys0):.3f}  max {max(ys0):.3f}")
    print(f"  x1  min {min(xs1):.3f}  mean {statistics.mean(xs1):.3f}  max {max(xs1):.3f}")
    print(f"  y1  min {min(ys1):.3f}  mean {statistics.mean(ys1):.3f}  max {max(ys1):.3f}")
    print()
    print(f"mark size in px : width  min {min(ws)}  mean {statistics.mean(ws):.0f}  max {max(ws)}")
    print(f"                  height min {min(hs)}  mean {statistics.mean(hs):.0f}  max {max(hs)}")
    print()
    print(f"mark height as % of image height : {statistics.mean(hs) / 1376 * 100:.1f}%")
    print(f"mark width  as % of image width  : {statistics.mean(ws) / 768 * 100:.1f}%")
    print(f"gap below the mark               : {(1 - max(ys1)) * 100:.2f}% of height")
    print()
    print(f"current crop removes             : {120 / 1376 * 100:.1f}% of height, FULL WIDTH")
    print(f"  -> {(1 - 120 / 1376) * 100:.1f}% of the frame height survives")
    print(f"  -> but {(1 - 120 / 1376) * 100:.1f}% of the width is discarded in that band,")
    print( "     of which only the mark's own footprint needed removing")
    print()

    # A safe union box: everything the mark has ever occupied, with a margin.
    print("union box across all detections (the smallest box that always contains it):")
    print(f"  x {min(xs0):.3f} -> {max(xs1):.3f}   y {min(ys0):.3f} -> {max(ys1):.3f}")
    margin = 0.012
    print(f"  with {margin * 100:.1f}% margin:")
    print(f"  x {max(0, min(xs0) - margin):.3f} -> {min(1, max(xs1) + margin):.3f}"
          f"   y {max(0, min(ys0) - margin):.3f} -> {min(1, max(ys1) + margin):.3f}")
    print(f"  -> that box is {(min(1, max(xs1) + margin) - max(0, min(xs0) - margin)) * 100:.1f}%"
          f" of the width and {(min(1, max(ys1) + margin) - max(0, min(ys0) - margin)) * 100:.1f}%"
          " of the height")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
