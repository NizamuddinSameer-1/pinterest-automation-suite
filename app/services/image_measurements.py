"""
Pinterest Realism Engine — Physical Image Measurements Service.

Performs a fast, deterministic PIL-based analysis of reference and product images:
  • Dominant color palette (5 hex codes via adaptive quantization)
  • Mean luminance & RMS contrast
  • Aspect ratio & pixel geometry
  • Laplacian variance (blur / sharpness estimate)
  • EXIF metadata extraction (if present)

Runs in < 20ms with pure Pillow (zero heavy CV dependencies).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageStat

logger = logging.getLogger("pre.image_measurements")


def _classify_aspect_ratio(w: int, h: int) -> str:
    if h == 0:
        return "unknown"
    ratio = w / h
    # Standard Pinterest / photography aspect ratios
    targets = [
        (1.0, "1:1"),
        (9 / 16, "9:16"),
        (2 / 3, "2:3"),
        (3 / 4, "3:4"),
        (4 / 5, "4:5"),
        (16 / 9, "16:9"),
        (3 / 2, "3:2"),
        (4 / 3, "4:3"),
    ]
    best_name = f"{round(ratio, 2)}:1"
    best_diff = 0.08  # tolerance
    for target_val, name in targets:
        diff = abs(ratio - target_val)
        if diff < best_diff:
            best_diff = diff
            best_name = name
    return best_name


def measure_image(image_path: str | Path) -> dict[str, Any]:
    """
    Deterministically analyze an image file using Pillow.

    Returns a structured dictionary of physical optical metrics.
    """
    path = Path(image_path)
    if not path.is_file():
        logger.warning("Image file does not exist: %s", path)
        return {
            "exists": False,
            "error": f"File not found: {path}",
        }

    try:
        with Image.open(path) as img:
            rgb_img = img.convert("RGB")
            w, h = rgb_img.size

            # 1. Geometry & Aspect Ratio
            display_ratio = _classify_aspect_ratio(w, h)
            aspect_ratio_float = round(w / h, 3) if h else 1.0

            # 2. Luminance & RMS Contrast
            gray = rgb_img.convert("L")
            stat = ImageStat.Stat(gray)
            mean_luminance = round(stat.mean[0], 2)
            rms_contrast = round(stat.stddev[0], 2)

            # 3. Blur Estimate via Laplacian Variance
            # 3x3 Laplacian edge-detection kernel
            lap_kernel = ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1)
            lap_img = gray.filter(lap_kernel)
            lap_stat = ImageStat.Stat(lap_img)
            laplacian_var = round(lap_stat.var[0], 2)

            if laplacian_var > 450:
                blur_desc = "sharp"
            elif laplacian_var > 120:
                blur_desc = "moderate"
            else:
                blur_desc = "soft"

            # 4. Dominant Color Palette (5 colors)
            small = rgb_img.resize((150, 150))
            quantized = small.quantize(colors=5, method=Image.Quantize.FASTOCTREE)
            palette = quantized.getpalette() or []
            palette_hex: list[str] = []
            for i in range(0, min(15, len(palette)), 3):
                r, g, b = palette[i], palette[i + 1], palette[i + 2]
                palette_hex.append(f"#{r:02x}{g:02x}{b:02x}")

            # 5. EXIF Metadata
            raw_exif = img.getexif()
            exif_data: dict[str, Any] = {}
            if raw_exif:
                # Useful standard tags: Make (271), Model (272), DateTime (306)
                if 271 in raw_exif:
                    exif_data["make"] = str(raw_exif[271]).strip()
                if 272 in raw_exif:
                    exif_data["model"] = str(raw_exif[272]).strip()
                if 306 in raw_exif:
                    exif_data["datetime"] = str(raw_exif[306]).strip()

            # 6. Physical Summary String
            summary = (
                f"Aspect ratio {display_ratio} ({w}x{h}); "
                f"dominant colors: {', '.join(palette_hex[:5])}; "
                f"luminance {mean_luminance}/255; "
                f"RMS contrast {rms_contrast} (stddev); "
                f"focus definition {blur_desc} (Laplacian var {laplacian_var})"
            )

            return {
                "exists": True,
                "width": w,
                "height": h,
                "aspect_ratio": display_ratio,
                "aspect_ratio_float": aspect_ratio_float,
                "dominant_palette": palette_hex[:5],
                "mean_luminance": mean_luminance,
                "rms_contrast": rms_contrast,
                "laplacian_variance": laplacian_var,
                "sharpness_estimate": blur_desc,
                "exif": exif_data,
                "optical_summary": summary,
            }
    except Exception as e:
        logger.error("Failed to measure image %s: %s", path, e)
        return {
            "exists": True,
            "error": str(e),
        }
