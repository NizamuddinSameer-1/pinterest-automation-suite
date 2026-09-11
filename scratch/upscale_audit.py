"""
Upscale / enhancement audit.

Measures what the current post-processing pipeline actually does to an image, and
compares it against alternatives — on sharpness, ringing (halos), grain, clipping,
file size and runtime.

Metrics, and why each one is here:

  lapvar   Laplacian variance. The standard "sharpness" proxy. High is not good in
           itself: a natural photo sits in a range, and pushing it up 3x means the
           image is crunchy, not detailed.
  hf       High-frequency energy = mean |img - blur(sigma=1)|. Rises with both real
           detail and with sharpening halos.
  ring     Ringing / overshoot. Sharpening overshoots an edge, producing a bright
           halo on the light side and a dark one on the dark side. Measured as the
           mean magnitude of the residual lobe that reverses sign from the local
           gradient — i.e. the part of the residual that is halo, not detail.
  grain    Noise sigma estimated in flat areas (local variance below a threshold).
           This is the injected sensor grain, measured where no detail exists.
  clip     Percent of pixels at 0 or 255. Contrast + sharpening blow highlights.
  kb / ms  File size and wall-clock time.

Run: python -m scratch.upscale_audit
"""
from __future__ import annotations

import io
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ───────────────────────────── metrics ─────────────────────────────


def _lum(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("L"), dtype=np.float32)


def _blur(a: np.ndarray, sigma: float) -> np.ndarray:
    return np.asarray(
        Image.fromarray(a.astype(np.uint8)).filter(ImageFilter.GaussianBlur(sigma)),
        dtype=np.float32,
    )


def metrics(img: Image.Image) -> dict[str, float]:
    a = _lum(img)
    # Laplacian variance
    lap = (
        -4 * a[1:-1, 1:-1]
        + a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:]
    )
    lapvar = float(lap.var())

    b1 = _blur(a, 1.0)
    resid = a - b1
    hf = float(np.abs(resid).mean())

    # Ringing: a sharpening halo is a residual that fights the local gradient. Take
    # the gradient direction from a wider blur and measure the residual component
    # that runs against it.
    wide = _blur(a, 2.0)
    grad = wide - _blur(a, 4.0)
    sign = np.sign(grad)
    ring = float(np.abs(np.minimum(resid * sign, 0.0)).mean())

    # Grain in flat areas: local std where the wide-scale gradient is tiny.
    flat = np.abs(grad) < 2.0
    if flat.sum() > 500:
        local = resid[flat]
        grain = float(local.std())
    else:
        grain = float("nan")

    clip = float(((a <= 0.5).mean() + (a >= 254.5).mean()) * 100.0)
    return {"lapvar": lapvar, "hf": hf, "ring": ring, "grain": grain, "clip": clip}


#: Every variant is measured at this width.
#:
#: Laplacian variance is scale-dependent — downscaling concentrates the same detail
#: into fewer pixels and inflates the number — so comparing a 1080px output against a
#: 1440px one measures the resolution difference, not the processing. Resampling every
#: variant to one common width applies the identical low-pass to all of them, which is
#: what makes the remaining differences attributable to the pipeline.
_MEASURE_WIDTH = 1024


def metrics_at(img: Image.Image, width: int = _MEASURE_WIDTH) -> dict[str, float]:
    """Metrics on a copy normalised to a common width, so scale cannot confound."""
    w, h = img.size
    if w != width and w > 0:
        img = img.resize((width, max(1, round(h * (width / w)))), Image.Resampling.LANCZOS)
    return metrics(img)


# ───────────────────────────── pipelines ─────────────────────────────


def _unsharp(img, radius, percent, threshold):
    return img.filter(
        ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=threshold)
    )


def _grain(img, amount, dtype=np.float64):
    arr = np.array(img, dtype=np.float32)
    if dtype is np.float64:
        g = np.random.normal(0, float(amount), arr.shape)
    else:
        g = np.random.default_rng(1234).normal(0, float(amount), arr.shape).astype(np.float32)
    return Image.fromarray(np.clip(arr + g, 0, 255).astype(np.uint8))


def _resize_box(img, max_w, max_h):
    """The current code's resize: always lands inside the box, up or down."""
    w, h = img.size
    if w > max_w or h > max_h:
        s = min(max_w / w, max_h / h)
    elif w < max_w and h < max_h:
        s = min(max_w / w, max_h / h)
    else:
        return img
    return img.resize((int(w * s), int(h * s)), Image.Resampling.LANCZOS)


def pipeline_current(img, crop_px=None, quality=98, subsampling=0, optimize=True,
                     max_w=1440, max_h=2560):
    """Exactly what anti_ai_processor.postprocess_image does today."""
    w, h = img.size
    if crop_px is None:
        crop_px = min(480, max(40, round(h * (120 / 1376))))
    if crop_px > 0 and h > crop_px + 100:
        img = img.crop((0, 0, w, h - crop_px))
    img = _resize_box(img, max_w, max_h)
    img = _unsharp(img, 1.2, 140, 1)
    img = ImageEnhance.Sharpness(img).enhance(1.15)
    img = ImageEnhance.Contrast(img).enhance(1.03)
    img = _grain(img, 2.5, dtype=np.float64)
    return img, dict(quality=quality, subsampling=subsampling, optimize=optimize)


def pipeline_once_1080(img, crop_px=None, quality=98, subsampling=0, optimize=True):
    """
    The current aggressive settings, but applied ONCE and downscaled to the real
    target width instead of upscaled into a 1440 box.

    This isolates the double-processing bug: same sharpening, one pass.
    """
    w, h = img.size
    if crop_px is None:
        crop_px = min(480, max(40, round(h * (120 / 1376))))
    if crop_px > 0 and h > crop_px + 100:
        img = img.crop((0, 0, w, h - crop_px))
    w, h = img.size
    if w > 1080:
        img = img.resize((1080, int(h * (1080 / w))), Image.Resampling.LANCZOS)
    img = _unsharp(img, 1.2, 140, 1)
    img = ImageEnhance.Sharpness(img).enhance(1.15)
    img = ImageEnhance.Contrast(img).enhance(1.03)
    img = _grain(img, 2.5, dtype=np.float32)
    return img, dict(quality=quality, subsampling=subsampling, optimize=optimize)


def pipeline_proposed(img, crop_px=None, quality=92, subsampling=0, optimize=False):
    """
    Proposed: sharpen once, gently, with a threshold that protects flat areas; sharpen
    luminance only so colour does not fringe; never upscale; downscale to the real
    target width.
    """
    w, h = img.size
    if crop_px is None:
        crop_px = min(480, max(40, round(h * (120 / 1376))))
    if crop_px > 0 and h > crop_px + 100:
        img = img.crop((0, 0, w, h - crop_px))

    # Downscale only — never upscale. Upscaling with Lanczos then sharpening is what
    # makes a soft, crunched image.
    target_w = 1080
    w, h = img.size
    if w > target_w:
        s = target_w / w
        img = img.resize((target_w, int(h * s)), Image.Resampling.LANCZOS)

    # Sharpen luminance only: sharpening chroma produces colour fringing on edges.
    ycc = img.convert("YCbCr")
    y, cb, cr = ycc.split()
    y = _unsharp(y, 1.0, 60, 3)
    img = Image.merge("YCbCr", (y, cb, cr)).convert("RGB")

    img = _grain(img, 1.5, dtype=np.float32)
    return img, dict(quality=quality, subsampling=subsampling, optimize=optimize)


def colab_transfer_cost(img) -> dict:
    """
    What the Colab path costs to move across the Cloudflare tunnel.

    The server loads RealESRGAN_x4plus, a 4x model, so a 1440px input comes back at
    5760px. This approximates that round trip with a 4x Lanczos + the server's own
    JPEG settings (quality 98, 4:4:4, optimize) to size the payload. It measures the
    TRANSFER, not the model's quality — ESRGAN output would differ in detail, not in
    pixel count or encoding.
    """
    w, h = img.size
    t0 = time.perf_counter()
    big = img.resize((w * 4, h * 4), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    big.save(buf, format="JPEG", quality=98, subsampling=0, optimize=True)
    enc_ms = int((time.perf_counter() - t0) * 1000)
    # Then the local side downscales it straight back to the 1440 box.
    t1 = time.perf_counter()
    back = big.resize((1440, int(big.size[1] * (1440 / big.size[0]))), Image.Resampling.LANCZOS)
    dec_ms = int((time.perf_counter() - t1) * 1000)
    return {"px": big.size[0], "kb": len(buf.getvalue()) // 1024,
            "enc_ms": enc_ms, "down_ms": dec_ms}


def save_and_measure(img, save_kw) -> tuple[bytes, dict]:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", **save_kw)
    data = buf.getvalue()
    with Image.open(io.BytesIO(data)) as back:
        m = metrics(back)
    return data, m


# ───────────────────────────── run ─────────────────────────────


def _inputs(limit: int = 6) -> list[Path]:
    out: list[Path] = []
    refs = sorted((ROOT / "data" / "references").glob("*.jpg"))
    out += refs[: limit // 2]
    for d in sorted((ROOT / "data" / "outputs").iterdir()):
        if not d.is_dir():
            continue
        for f in sorted(d.glob("flow_var_*.jpg")):
            out.append(f)
            break
        if len(out) >= limit:
            break
    return out[:limit]


def main() -> int:
    files = _inputs()
    if not files:
        print("no test images found")
        return 1

    print("=" * 104)
    print("UPSCALE / ENHANCEMENT AUDIT")
    print("=" * 104)
    print(f"{len(files)} test image(s)\n")

    rows: list[tuple[str, str, dict, int, int]] = []

    def add(name, variant, img, data, ms):
        with Image.open(io.BytesIO(data)) as back:
            m = metrics_at(back)
        rows.append((name[:26], variant, {**m, "_ms": ms}, img.size[0], len(data) // 1024))

    for f in files:
        with Image.open(f) as src:
            base = src.convert("RGB")
        name = f.name[:26]
        bw, bh = base.size
        rows.append((name, "INPUT", {**metrics_at(base), "_ms": 0}, bw, f.stat().st_size // 1024))

        # current, once
        t0 = time.perf_counter()
        im, kw = pipeline_current(base)
        data, _ = save_and_measure(im, kw)
        add(name, "current x1", im, data, int((time.perf_counter() - t0) * 1000))

        # current, twice — what the pipeline actually does today
        t0 = time.perf_counter()
        im2, kw2 = pipeline_current(Image.open(io.BytesIO(data)).convert("RGB"))
        data2, _ = save_and_measure(im2, kw2)
        add(name, "current x2", im2, data2, int((time.perf_counter() - t0) * 1000))

        # same aggressive settings, applied ONCE, downscaled to 1080
        t0 = time.perf_counter()
        im3, kw3 = pipeline_once_1080(base)
        data3, _ = save_and_measure(im3, kw3)
        add(name, "A once@1080", im3, data3, int((time.perf_counter() - t0) * 1000))

        # proposed
        t0 = time.perf_counter()
        im4, kw4 = pipeline_proposed(base)
        data4, _ = save_and_measure(im4, kw4)
        add(name, "B proposed", im4, data4, int((time.perf_counter() - t0) * 1000))

    hdr = f"{'image':<28}{'variant':<12}{'px':>6}{'lapvar':>9}{'hf':>7}{'ring':>7}{'grain':>7}{'clip%':>7}{'KB':>7}{'ms':>7}"
    print(hdr)
    print("-" * len(hdr))
    last = None
    for name, variant, m, w, kb in rows:
        if last and name != last:
            print()
        last = name
        print(
            f"{name:<28}{variant:<12}{w:>6}{m['lapvar']:>9.0f}{m['hf']:>7.2f}"
            f"{m['ring']:>7.3f}{m['grain']:>7.2f}{m['clip']:>7.2f}{kb:>7}{m.get('_ms', 0):>7}"
        )

    # ── summary: mean change vs the input ──
    print()
    print("=" * 104)
    print("MEAN CHANGE vs INPUT  (1.00x = unchanged; higher = more processed)")
    print("=" * 104)
    by_img: dict[str, dict[str, dict]] = {}
    for name, variant, m, w, kb in rows:
        by_img.setdefault(name, {})[variant] = {**m, "kb": kb}

    print(f"{'variant':<14}{'lapvar':>10}{'hf':>10}{'ring':>10}{'grain':>10}{'clip':>10}{'KB':>10}{'ms':>9}")
    print("-" * 84)
    for variant in ("current x1", "current x2", "A once@1080", "B proposed"):
        ratios = {k: [] for k in ("lapvar", "hf", "ring", "grain", "clip")}
        kbs, mss = [], []
        for name, d in by_img.items():
            base, v = d.get("INPUT"), d.get(variant)
            if not base or not v:
                continue
            for k in ratios:
                if base[k] and base[k] > 0:
                    ratios[k].append(v[k] / base[k])
            kbs.append(v["kb"])
            mss.append(v.get("_ms", 0))

        def r(seq):
            a = [x for x in seq if not np.isnan(x)]
            return f"{np.mean(a):.2f}x" if a else "n/a"

        print(
            f"{variant:<14}{r(ratios['lapvar']):>10}{r(ratios['hf']):>10}{r(ratios['ring']):>10}"
            f"{r(ratios['grain']):>10}{r(ratios['clip']):>10}"
            f"{np.mean(kbs):>9.0f}KB{np.mean(mss):>7.0f}ms"
        )

    # ── the real Flow outputs only (these are what the pipeline actually sees) ──
    print()
    print("=" * 104)
    print("REAL FLOW OUTPUTS ONLY — already ~2K when they arrive")
    print("=" * 104)
    flow_names = {f.name[:26] for f in files if f.name.startswith("flow_var")}
    real = {n: d for n, d in by_img.items() if n in flow_names}
    print(f"{len(real)} Flow output(s)\n")
    print(f"{'variant':<14}{'lapvar':>10}{'ring':>10}{'grain':>10}{'KB':>10}{'ms':>9}")
    print("-" * 63)
    for variant in ("current x1", "current x2", "A once@1080", "B proposed"):
        lv, rg, gr, kbs, mss = [], [], [], [], []
        for n, d in real.items():
            v = d.get(variant)
            if not v:
                continue
            lv.append(v["lapvar"]); rg.append(v["ring"]); gr.append(v["grain"])
            kbs.append(v["kb"]); mss.append(v.get("_ms", 0))
        if not lv:
            continue
        print(f"{variant:<14}{np.mean(lv):>10.0f}{np.mean(rg):>10.3f}{np.mean(gr):>10.2f}"
              f"{np.mean(kbs):>9.0f}KB{np.mean(mss):>7.0f}ms")
    if real:
        base_lv = np.mean([d["INPUT"]["lapvar"] for d in real.values()])
        print(f"\ninput lapvar (normalised to {_MEASURE_WIDTH}px): {base_lv:.0f}")

    # ── Colab transfer cost ──
    print()
    print("=" * 104)
    print("COLAB PATH — transfer cost of a 4x round trip (RealESRGAN_x4plus)")
    print("=" * 104)
    sample = None
    for f in files:
        with Image.open(f) as s:
            if s.width >= 1000:
                sample = s.convert("RGB")
                break
    if sample:
        c = colab_transfer_cost(sample)
        print(f"input            : {sample.size[0]}x{sample.size[1]}")
        print(f"after 4x         : {c['px']}px wide")
        print(f"payload returned : {c['kb'] / 1024:.1f} MB  (server sends JPEG 98 / 4:4:4 / optimize)")
        print(f"encode on Colab  : {c['enc_ms']} ms   downscale back on local: {c['down_ms']} ms")
        print(f"then discarded   : the local side immediately resizes it back to 1440px")
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
