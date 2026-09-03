"""
Pinterest Realism Engine — Anti-AI, Watermark Removal & Studio HD Pin Enhancer.

Upgrades:
1. Bottom Watermark Crop (~8.7% / 120px) to cleanly strip Google/Gemini watermarks.
2. Optional Google Colab AI Upscaler (Real-ESRGAN on cloud GPU with 0 local RAM/GPU use).
3. Local High-Resolution Super-Resolution (Lanczos resampling to Full HD 1080px Pinterest width).
4. Optical Micro-Sharpening (UnsharpMask) for fabric threads, skin, and fine edges without artificial noise.
5. Studio 98% Quality + 4:4:4 Chroma (Zero Subsampling) for razor-sharp Pinterest display on Retina/OLED screens.
"""

from __future__ import annotations

import io
import logging
import os
import shutil
from pathlib import Path
from typing import Sequence

import httpx
from PIL import Image, ImageEnhance, ImageFilter

from app.config import settings

logger = logging.getLogger("pre.anti_ai_processor")

TUNNEL_CACHE = Path("./data/colab_tunnel.txt").resolve()

#: The 120px watermark band was calibrated on Flow's ~1376px-tall renders.
#: Proportional: 120 / 1376 ≈ 8.7% of the height.
_WATERMARK_BAND_RATIO = 120 / 1376


def _auto_crop_px(height: int) -> int:
    """Watermark-band crop for a given image height (40px floor, 480px ceiling)."""
    return min(480, max(40, round(height * _WATERMARK_BAND_RATIO)))


def _resolve_colab_url() -> str | None:
    """Find active Google Colab 4x-UltraSharp AI upscaler endpoint."""
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
                    r = client.get(cand)
                    if r.status_code == 200:
                        return cand
            except Exception:
                pass
    return None


def _try_colab_upscale(image_bytes: bytes, colab_url: str) -> bytes | None:
    """
    Query Google Colab GPU running 4x-UltraSharp (Fine-Tuned for UGC Realism & Micro-Textures).
    Recovers authentic fabric weave, clothing stitches, and skin pores without plastic smoothing.
    """
    if not colab_url or not colab_url.startswith("http"):
        return None

    endpoint = colab_url.rstrip("/")
    if not endpoint.endswith("/upscale"):
        endpoint = f"{endpoint}/upscale"

    try:
        logger.info("📡 [AI UPSCALER] Sending image to Colab 4x-UltraSharp GPU upscaler: %s", endpoint)
        with httpx.Client(timeout=60.0) as client:
            files = {"file": ("input.jpg", image_bytes, "image/jpeg")}
            resp = client.post(endpoint, files=files)
            if resp.status_code == 200 and len(resp.content) > 5000:
                logger.info("✅ [AI UPSCALER] 4x-UltraSharp upscaler succeeded (%d KB returned)", len(resp.content) // 1024)
                return resp.content
            logger.warning(
                "⚠️ [AI UPSCALER] Colab returned HTTP %d: %s. Falling back to local UGC texture engine.",
                resp.status_code,
                resp.text[:200],
            )
    except Exception as e:
        logger.warning("⚠️ [AI UPSCALER] Colab upscaler connection error: %s. Falling back to local UGC engine.", e)

    return None


def postprocess_image(
    image_path: str | Path,
    output_path: str | Path | None = None,
    crop_bottom_px: int | None = None,
) -> str:
    """
    Post-process an image: remove watermark, enhance UGC micro-details (fabric & skin pores),
    inject organic camera sensor grain to break AI plastic smoothness, and save with studio 98% 4:4:4 clarity.

    Args:
        image_path: Path to the source image.
        output_path: Destination path. If None or same as image_path, overwrites in-place.
        crop_bottom_px: Pixels to crop from bottom. Default (None) is proportional (~8.7%).

    Returns:
        str: Absolute or resolved path of the processed image.
    """
    src = Path(image_path).resolve()
    if not src.is_file():
        logger.warning("Postprocess target does not exist: %s", src)
        return str(image_path)

    dst = Path(output_path).resolve() if output_path else src
    temp_dst = dst.with_suffix(f".enhanced_tmp_{os.getpid()}.jpg")

    try:
        raw_bytes = src.read_bytes()

        # Step 1: Check if Google Colab 4x-UltraSharp AI Upscaler is active
        active_colab_url = _resolve_colab_url()
        if active_colab_url:
            upscaled_bytes = _try_colab_upscale(raw_bytes, active_colab_url)
            if upscaled_bytes:
                raw_bytes = upscaled_bytes

        # Step 2: Open with Pillow for processing
        with Image.open(io.BytesIO(raw_bytes)) as img:
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            # Step 3: Watermark Crop
            w, h = img.size
            crop_px = crop_bottom_px if crop_bottom_px is not None else _auto_crop_px(h)
            if h > crop_px + 100:
                img = img.crop((0, 0, w, h - crop_px))
                w, h = img.size

            # Step 4: 2K Master Resolution Standard (Max 1440px width / 2560px height)
            MAX_2K_WIDTH = 1440
            MAX_2K_HEIGHT = 2560

            if w > MAX_2K_WIDTH or h > MAX_2K_HEIGHT:
                scale = min(MAX_2K_WIDTH / w, MAX_2K_HEIGHT / h)
                new_w = int(w * scale)
                new_h = int(h * scale)
                img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                w, h = img.size
            elif w < MAX_2K_WIDTH and h < MAX_2K_HEIGHT:
                scale = min(MAX_2K_WIDTH / w, MAX_2K_HEIGHT / h)
                new_w = int(w * scale)
                new_h = int(h * scale)
                img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                w, h = img.size

            # Step 5: UGC Photorealistic Micro-Detail Recovery (Anti-Smoothing)
            # 1. High-frequency UnsharpMask to pop fabric weave, clothing seams, and skin texture
            sharpen_pct = getattr(settings, "ugc_sharpen_percent", 140)
            if sharpen_pct > 0:
                img = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=sharpen_pct, threshold=1))

            # 2. Micro-clarity & contrast pop to eliminate dull AI haze
            img = ImageEnhance.Sharpness(img).enhance(1.15)
            img = ImageEnhance.Contrast(img).enhance(1.03)

            # 3. Organic UGC Camera Sensor Micro-Grain (Kills Plastic AI Smoothness)
            grain_amount = getattr(settings, "ugc_grain_amount", 2.5)
            if grain_amount > 0:
                try:
                    import numpy as np
                    arr = np.array(img, dtype=np.float32)
                    grain = np.random.normal(0, float(grain_amount), arr.shape)
                    arr = np.clip(arr + grain, 0, 255).astype(np.uint8)
                    img = Image.fromarray(arr)
                except Exception as e:
                    logger.debug("Grain injection note: %s", e)

            # Step 6: Studio Master Save (98% quality, 4:4:4 zero chroma subsampling)
            jpeg_quality = getattr(settings, "upscaler_jpeg_quality", 98)
            subsampling = getattr(settings, "upscaler_subsampling", 0)  # 0 = 4:4:4

            img.save(
                temp_dst,
                format="JPEG",
                quality=jpeg_quality,
                subsampling=subsampling,
                optimize=True,
            )

        if temp_dst.is_file() and temp_dst.stat().st_size > 1024:
            shutil.move(str(temp_dst), str(dst))
            logger.info("✅ Enhanced studio UGC pin saved: %s (%d KB, 4:4:4)", dst.name, dst.stat().st_size // 1024)
            return str(dst)

    except Exception as e:
        logger.error("Error enhancing image %s: %s", src.name, e)
        if temp_dst.is_file():
            try:
                temp_dst.unlink()
            except OSError:
                pass

    return str(image_path)


def postprocess_batch(image_paths: Sequence[str | Path]) -> list[str]:
    """
    Run watermark removal, Lanczos super-resolution, and 4:4:4 studio encoding across a list of images.
    """
    processed: list[str] = []
    for path in image_paths:
        res = postprocess_image(path)
        processed.append(res)
    return processed
