"""
Verify the enhancement pipeline fix.

Checks:
  A. Idempotency  - running the pipeline twice equals running it once.
  B. AR guard     - a legacy output (cropped, no marker) is not cropped again.
  C. Quality      - the new pipeline against the old one, on the same render.

Usage:  python scratch/verify_upscale_fix.py
"""

from __future__ import annotations

import io
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WORK = Path("scratch/_verify")
MEASURE_WIDTH = 1024


# ── metrics ────────────────────────────────────────────────────────────────

def _norm(path: Path, width: int = MEASURE_WIDTH) -> np.ndarray:
    """Load greyscale, normalised to a common width (lapvar is scale-dependent)."""
    with Image.open(path) as im:
        g = im.convert("L")
        if g.width != width:
            g = g.resize((width, max(1, round(g.height * width / g.width))), Image.Resampling.LANCZOS)
        return np.asarray(g, dtype=np.float32)


def metrics(path: Path) -> dict[str, float]:
    g = _norm(path)
    blur = ndimage.gaussian_filter(g, 1.0)
    detail = g - blur
    lap = ndimage.laplace(blur)
    # Ringing proxy: detail energy in flat areas (a halo lives next to an edge
    # but sits on flat ground).
    grad = np.hypot(*np.gradient(blur))
    flat = grad < np.percentile(grad, 60)
    return {
        "lapvar": float(lap.var()),
        "detail": float(np.mean(np.abs(detail))),
        "ring": float(np.mean(np.abs(detail[flat]))) if flat.any() else 0.0,
        "clip": float(np.mean((g <= 1) | (g >= 254)) * 100),
    }


def kb(path: Path) -> float:
    return path.stat().st_size / 1024


def dims(path: Path) -> tuple[int, int]:
    with Image.open(path) as im:
        return im.size


# ── the OLD pipeline, for comparison ───────────────────────────────────────

def old_pipeline(src: Path, dst: Path, passes: int = 2) -> None:
    """Reproduce the previous behaviour: proportional crop, 1440 box, heavy sharpen."""
    shutil.copy(src, dst)
    for _ in range(passes):
        with Image.open(dst) as img:
            img = img.convert("RGB")
            w, h = img.size
            crop = min(480, max(40, round(h * 120 / 1376)))
            if crop > 0 and h > crop + 100:
                img = img.crop((0, 0, w, h - crop))
                w, h = img.size
            MAX_W, MAX_H = 1440, 2560
            if w != MAX_W or h != MAX_H:
                scale = min(MAX_W / w, MAX_H / h)
                img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
            img = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=140, threshold=1))
            img = ImageEnhance.Sharpness(img).enhance(1.15)
            img = ImageEnhance.Contrast(img).enhance(1.03)
            arr = np.asarray(img, dtype=np.float32)
            arr = np.clip(arr + np.random.normal(0, 2.5, arr.shape), 0, 255)
            img = Image.fromarray(arr.astype(np.uint8))
            img.save(dst, format="JPEG", quality=98, subsampling=0, optimize=True)


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    from app.services.anti_ai_processor import finalize_upscaled_image, postprocess_image

    # Pick a raw render and a legacy cropped output.
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
        print("no raw 768x1376 render found")
        return 1

    failures: list[str] = []

    # ── A. idempotency ────────────────────────────────────────────────────
    print("=" * 74)
    print("A. IDEMPOTENCY — run the pipeline twice, compare with running it once")
    print("=" * 74)
    a1 = WORK / "a_once.jpg"
    shutil.copy(raw, a1)
    postprocess_image(a1)
    d1, s1 = dims(a1), kb(a1)

    postprocess_image(a1)
    d2, s2 = dims(a1), kb(a1)

    print("   pass 1 : %sx%s  %.0f KB" % (d1[0], d1[1], s1))
    print("   pass 2 : %sx%s  %.0f KB" % (d2[0], d2[1], s2))
    if d1 == d2 and abs(s1 - s2) < 0.5:
        print("   PASS - the second pass changed nothing")
    else:
        failures.append("idempotency: pass 2 altered the image")
        print("   FAIL - the second pass altered the image")

    # ── B. aspect-ratio guard on a legacy file ────────────────────────────
    print()
    print("=" * 74)
    print("B. AR GUARD — a legacy cropped file (no marker) must not crop again")
    print("=" * 74)
    legacy_src = None
    for d in Path("data/outputs").iterdir():
        if not d.is_dir():
            continue
        for f in d.glob("*.jpg"):
            try:
                with Image.open(f) as im:
                    if im.size == (1440, 2355):
                        legacy_src = f
                        break
            except Exception:
                continue
        if legacy_src:
            break

    if legacy_src is None:
        print("   (no 1440x2355 legacy file found, skipping)")
    else:
        b = WORK / "b_legacy.jpg"
        shutil.copy(legacy_src, b)
        before = dims(b)
        postprocess_image(b)
        after = dims(b)
        print("   legacy file      : %sx%s" % before)
        print("   after processing : %sx%s  (resized to target width, not re-cropped)" % after)
        expected_h = round(before[1] * 1080 / before[0])
        if after[0] == 1080 and abs(after[1] - expected_h) <= 2:
            print("   PASS - width normalised to 1080, height scaled proportionally (no extra crop)")
        else:
            failures.append("AR guard: legacy file was re-cropped")
            print("   FAIL - unexpected dimensions")

    # ── C. quality, old vs new ────────────────────────────────────────────
    print()
    print("=" * 74)
    print("C. QUALITY — old pipeline (two passes) vs the new one, same render")
    print("=" * 74)
    c_old = WORK / "c_old.jpg"
    old_pipeline(raw, c_old, passes=2)

    c_new = WORK / "c_new.jpg"
    shutil.copy(raw, c_new)
    postprocess_image(c_new)

    base = metrics(raw)
    print("   %-24s %10s %10s %10s %8s" % ("", "sharpness", "detail", "halos", "clip%"))
    print("   " + "-" * 66)
    print("   %-24s %10.1f %10.1f %10.1f %8.2f" % ("raw render (reference)", base["lapvar"], base["detail"], base["ring"], base["clip"]))
    for label, path in (("old pipeline x2", c_old), ("new pipeline x1", c_new)):
        m = metrics(path)
        print("   %-24s %10.1f %10.1f %10.1f %8.2f   %sx%s %.0f KB" % (
            label, m["lapvar"], m["detail"], m["ring"], m["clip"],
            dims(path)[0], dims(path)[1], kb(path)))
        print("   %-24s %10s %10s %10s" % ("", "%.1fx" % (m["lapvar"] / base["lapvar"]),
                                           "%.2fx" % (m["detail"] / base["detail"]),
                                           "%.2fx" % (m["ring"] / base["ring"])))

    # ── D. finalize path ──────────────────────────────────────────────────
    print()
    print("=" * 74)
    print("D. FINALIZE — the Colab output path must not re-sharpen")
    print("=" * 74)
    d_src = WORK / "d_upscaled.jpg"
    big = Image.open(raw).convert("RGB").resize((3072, 5504), Image.Resampling.LANCZOS)
    big.save(d_src, format="JPEG", quality=95)
    in_kb = kb(d_src)
    finalize_upscaled_image(d_src)
    fd, fk = dims(d_src), kb(d_src)
    print("   input  : 3072x5504  %.0f KB" % in_kb)
    print("   output : %sx%s  %.0f KB" % (fd[0], fd[1], fk))
    if fd[0] == 1080:
        print("   PASS - resized to the 1080 target")
    else:
        failures.append("finalize: wrong width")
        print("   FAIL - expected width 1080")

    print()
    print("=" * 74)
    if failures:
        print("FAILURES: " + "; ".join(failures))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
