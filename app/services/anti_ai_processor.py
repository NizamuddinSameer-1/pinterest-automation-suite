"""
Pinterest Realism Engine — Watermark removal, anti-AI texture and pin enhancement.

Design contract: **every stage is idempotent.**

This module is reached from several call sites — the harvest path in
``flow_automator``, the direct-API path in ``flow_direct_api``, and the publish
path in ``output_service`` / ``colab_automator``. Previously each of them ran
the full pipeline, and because the watermark crop was proportional to the
*current* height, a second pass cropped a second, larger band. That is what
produced pins at four different aspect ratios and, combined with a 2.76x
unsharp gain applied twice, the ringing halos that made images look "too sharp".

Two independent guards prevent that now:

1. A JPEG comment marker (:data:`_PIPELINE_MARK`) written on save. A file that
   carries it has already been enhanced and will not be enhanced again.
2. An aspect-ratio guard on the crop. The crop targets a fixed ratio, so once
   an image reaches it, cropping again is a no-op — this holds even for files
   written before the marker existed.

Stages, in order:

1. Optional GPU upscale (Real-ESRGAN on Colab) — skipped when already enhanced.
2. Watermark removal — bottom band, ratio-targeted, applied exactly once.
3. Resize to the target width (a ceiling: downscale, rarely upscale).
4. Luminance-only, threshold-gated unsharp mask.
5. Light luminance-only sensor grain.
6. JPEG encode at the configured quality.
"""

from __future__ import annotations

import io
import logging
import os
import shutil
from pathlib import Path
from typing import Sequence

import httpx
from PIL import Image, ImageFilter

from app.config import settings

logger = logging.getLogger("pre.anti_ai_processor")

TUNNEL_CACHE = Path("./data/colab_tunnel.txt").resolve()

#: Written into the JPEG comment so any call site can tell whether this image
#: has already been through the pipeline. Bump the suffix if the stages change
#: in a way that should force a re-process.
_PIPELINE_MARK = b"PRE_ENHANCED_V1"

#: Flow's raw render is 768x1376 (aspect ratio 0.5581). Removing the watermark
#: keeps the top ``watermark_keep_fraction`` of the height, which lands the pin
#: on 0.6133. Used as the idempotency guard and as the crop target.
_PIN_TARGET_AR = 0.6133
_AR_TOLERANCE = 0.006


def _keep_fraction() -> float:
    value = float(getattr(settings, "watermark_keep_fraction", 0.910) or 0.910)
    return min(0.99, max(0.50, value))


def _target_width() -> int:
    return int(getattr(settings, "upscaler_target_width", 1080) or 1080)


def _already_enhanced(img: Image.Image) -> bool:
    """True when this image was written by :func:`postprocess_image`."""
    comment = img.info.get("comment") or b""
    if isinstance(comment, str):
        comment = comment.encode("utf-8", "ignore")
    return comment.startswith(_PIPELINE_MARK)


def _watermark_crop(
    img: Image.Image, crop_bottom_px: int | None = None
) -> tuple[Image.Image, bool]:
    """
    Remove the Flow sparkle by trimming the bottom band.

    Returns ``(image, cropped)``. The crop targets a fixed aspect ratio, so
    calling this on an already-cropped image returns it untouched — that is
    what makes a repeated pipeline run harmless.

    ``crop_bottom_px`` overrides the depth for a raw render; ``0`` disables the
    crop entirely.
    """
    w, h = img.size
    if crop_bottom_px == 0:
        return img, False

    if w / h >= _PIN_TARGET_AR - _AR_TOLERANCE:
        return img, False

    if crop_bottom_px is not None and crop_bottom_px > 0:
        target_h = h - int(crop_bottom_px)
    else:
        target_h = int(round(h * _keep_fraction()))

    if target_h >= h or target_h < 100:
        return img, False
    return img.crop((0, 0, w, target_h)), True


def _fit_width(img: Image.Image, target_width: int) -> tuple[Image.Image, bool]:
    """Scale to ``target_width``. Returns ``(image, resized)``."""
    w, h = img.size
    if w == target_width or w <= 0:
        return img, False
    new_h = max(1, int(round(h * (target_width / w))))
    return img.resize((target_width, new_h), Image.Resampling.LANCZOS), True


def _enhance_luminance(img: Image.Image) -> Image.Image:
    """
    Unsharp mask applied to the Y channel only.

    Sharpening chroma is what puts coloured fringes along edges, so the image is
    split and only luminance is filtered. The threshold leaves low-contrast
    areas — flat colour, sky, skin — completely alone.
    """
    radius = float(getattr(settings, "ugc_sharpen_radius", 1.0) or 1.0)
    percent = int(getattr(settings, "ugc_sharpen_percent", 60) or 0)
    threshold = int(getattr(settings, "ugc_sharpen_threshold", 3) or 0)

    if percent > 0:
        ycbcr = img.convert("YCbCr")
        y, cb, cr = ycbcr.split()
        y = y.filter(
            ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=threshold)
        )
        img = Image.merge("YCbCr", (y, cb, cr)).convert("RGB")

    return img


def _add_grain(img: Image.Image, amount: float) -> Image.Image:
    """
    Sensor grain, luminance-only.

    The same noise value is added to all three channels, so it reads as grain
    rather than colour speckle — and it costs one 2D array instead of a 3D one.
    """
    if amount <= 0:
        return img
    try:
        import numpy as np

        arr = np.asarray(img, dtype=np.float32)
        noise = np.random.normal(0.0, float(amount), arr.shape[:2]).astype(np.float32)
        arr = np.clip(arr + noise[:, :, None], 0, 255)
        return Image.fromarray(arr.astype(np.uint8), "RGB")
    except Exception as e:
        logger.debug("Grain injection skipped: %s", e)
        return img


def _save(img: Image.Image, dst: Path) -> None:
    """Encode with the configured quality, stamping the pipeline marker."""
    img.save(
        dst,
        format="JPEG",
        quality=int(getattr(settings, "upscaler_jpeg_quality", 92) or 92),
        subsampling=int(getattr(settings, "upscaler_subsampling", 2) or 0),
        optimize=False,
        comment=_PIPELINE_MARK,
    )


def _resolve_colab_url() -> str | None:
    """Find a live Colab upscaler endpoint, if one is configured."""
    candidates: list[str] = []

    conf = getattr(settings, "colab_upscaler_url", "").strip()
    if conf:
        candidates.append(conf)

    if TUNNEL_CACHE.exists():
        try:
            cached = TUNNEL_CACHE.read_text(encoding="utf-8").strip()
            if cached and cached not in candidates:
                candidates.append(cached)
        except Exception:
            pass

    for cand in candidates:
        if cand.startswith("http"):
            try:
                with httpx.Client(timeout=2.5) as client:
                    if client.get(cand).status_code == 200:
                        return cand
            except Exception:
                pass
    return None


def _try_colab_upscale(
    image_bytes: bytes, colab_url: str, filename: str = "input.jpg"
) -> bytes | None:
    """
    Send one image to the Colab Real-ESRGAN server.

    The server caps its own output (see ``colab_max_output_px``), so what comes
    back is a few hundred KB rather than tens of megabytes. Any failure returns
    None and the caller falls back to a local resize.
    """
    if not colab_url or not colab_url.startswith("http"):
        return None

    endpoint = colab_url.rstrip("/")
    if not endpoint.endswith("/upscale"):
        endpoint = f"{endpoint}/upscale"

    try:
        logger.info("📡 [AI UPSCALER] Sending '%s' to the Colab GPU upscaler", filename)
        with httpx.Client(timeout=90.0) as client:
            resp = client.post(
                endpoint, files={"file": (filename, image_bytes, "image/jpeg")}
            )
            if resp.status_code == 200 and len(resp.content) > 5000:
                logger.info(
                    "✅ [AI UPSCALER] GPU upscale returned %d KB",
                    len(resp.content) // 1024,
                )
                return resp.content

            detail = resp.text[:200]
            try:
                payload = resp.json()
                detail = f"{payload.get('error_type', 'Error')}: {payload.get('detail', detail)}"
            except Exception:
                pass
            logger.warning(
                "❌ [AI UPSCALER] Colab returned HTTP %d: %s. Using local resize.",
                resp.status_code,
                detail,
            )
    except Exception as e:
        logger.warning("❌ [AI UPSCALER] Colab connection error: %s. Using local resize.", e)

    return None


def _write_temp(img: Image.Image, dst: Path, temp_dst: Path) -> str:
    """Encode to a temp file, then move into place atomically."""
    _save(img, temp_dst)
    if temp_dst.is_file() and temp_dst.stat().st_size > 1024:
        shutil.move(str(temp_dst), str(dst))
        logger.info(
            "✅ Enhanced pin saved: %s (%d KB)", dst.name, dst.stat().st_size // 1024
        )
        return str(dst)
    return ""


def postprocess_image(
    image_path: str | Path,
    output_path: str | Path | None = None,
    crop_bottom_px: int | None = None,
    skip_colab: bool = False,
) -> str:
    """
    Enhance one pin image. Safe to call more than once.

    Args:
        image_path: Source image.
        output_path: Destination. None or same path means overwrite in place.
        crop_bottom_px: Override the watermark crop depth for a raw render.
            Pass 0 to disable cropping. None uses the ratio rule.
        skip_colab: Bypass the optional GPU upscale.

    Returns:
        Path of the processed image, or the original path on failure.
    """
    src = Path(image_path).resolve()
    if not src.is_file():
        logger.warning("Postprocess target does not exist: %s", src)
        return str(image_path)

    dst = Path(output_path).resolve() if output_path else src
    temp_dst = dst.with_suffix(f".enhanced_tmp_{os.getpid()}.jpg")
    target_width = _target_width()

    try:
        raw_bytes = src.read_bytes()

        with Image.open(io.BytesIO(raw_bytes)) as probe:
            already = _already_enhanced(probe)
            probe_w, _ = probe.size

        # Already enhanced and already the right size: re-encoding would only
        # cost a generation of JPEG quality for no change.
        if already and probe_w == target_width and not crop_bottom_px:
            logger.debug("Already enhanced at target width, skipping: %s", dst.name)
            return str(dst)

        # Stage 1 — GPU upscale, on the untouched bytes.
        if not skip_colab and not already:
            active = _resolve_colab_url()
            if active:
                upscaled = _try_colab_upscale(raw_bytes, active, filename=src.name)
                if upscaled:
                    raw_bytes = upscaled

        with Image.open(io.BytesIO(raw_bytes)) as img:
            # Re-read: a Colab response is a fresh JPEG with no marker.
            already = _already_enhanced(img)
            img = img.convert("RGB")

            if not already:
                img, cropped = _watermark_crop(img, crop_bottom_px)
                if cropped:
                    logger.debug("Watermark band cropped: %s", dst.name)

            img, _ = _fit_width(img, target_width)

            if not already:
                img = _enhance_luminance(img)
                img = _add_grain(
                    img, float(getattr(settings, "ugc_grain_amount", 1.5) or 0.0)
                )

            result = _write_temp(img, dst, temp_dst)
            if result:
                return result

    except Exception as e:
        logger.error("Error enhancing image %s: %s", src.name, e)
        if temp_dst.is_file():
            try:
                temp_dst.unlink()
            except OSError:
                pass

    return str(image_path)


def finalize_upscaled_image(
    image_path: str | Path,
    output_path: str | Path | None = None,
    target_width: int | None = None,
) -> str:
    """
    Bring a GPU-upscaled image down to pin size.

    Deliberately does *not* crop or sharpen: the source was already cropped and
    enhanced before it was upscaled, and Real-ESRGAN's output is already crisp.
    Running the full pipeline here is what applied the unsharp mask a second
    time and produced the halos.

    Grain is restored at a reduced level, because upscaling smooths away the
    grain the first pass added and the anti-AI signal would otherwise be lost.
    """
    src = Path(image_path).resolve()
    if not src.is_file():
        logger.warning("Finalize target does not exist: %s", src)
        return str(image_path)

    dst = Path(output_path).resolve() if output_path else src
    temp_dst = dst.with_suffix(f".final_tmp_{os.getpid()}.jpg")
    width = int(target_width or _target_width())

    try:
        with Image.open(src) as img:
            img = img.convert("RGB")
            img, _ = _watermark_crop(img)
            img, _ = _fit_width(img, width)
            grain = float(getattr(settings, "ugc_grain_amount", 1.5) or 0.0)
            img = _add_grain(img, grain * 0.6)

            result = _write_temp(img, dst, temp_dst)
            if result:
                return result
    except Exception as e:
        logger.error("Error finalizing upscaled image %s: %s", src.name, e)
        if temp_dst.is_file():
            try:
                temp_dst.unlink()
            except OSError:
                pass

    return str(image_path)


def postprocess_batch(
    image_paths: Sequence[str | Path], skip_colab: bool = False
) -> list[str]:
    """Run :func:`postprocess_image` across a list. Already-enhanced files are no-ops."""
    return [postprocess_image(p, skip_colab=skip_colab) for p in image_paths]
