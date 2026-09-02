"""
Shared Visual Specs & Physical Grounding Module.

Extracts, filters, and ranks physical product specifications from merchant listings
(Amazon Product Overview, Item Specs, Material registries) so prompts and Product Truth
focus strictly on what can be captured in a genuine photograph.
"""

from __future__ import annotations

import re
from typing import Any

#: Keys that indicate how an object looks, in the order they should be phrased.
_VISUAL_SPEC_ORDER = (
    "colour", "color",
    "fabric", "material",
    "pattern",
    "neck", "collar",
    "sleeve",
    "fit", "style",
    "closure",
    "heel",
    "finish",
    "cut",
)

#: Keys that sound like visual specs but describe non-photographic metadata.
_SKIP_SPEC_KEYS = (
    "care", "wash", "origin", "country", "generic", "department",
    "number", "model", "asin", "upc", "ean", "package", "item package",
    "batteries", "warranty", "shipping", "manufacturer", "importer",
    "packer", "age range", "target audience", "occasion", "theme",
    "unit count", "net quantity", "included components",
)

#: Scale instructions kept apart from visual look.
_MEASUREMENT_KEYS = ("dimension", "weight", "capacity", "volume", "diameter", "size")

#: Maximum characters in a valid physical spec value.
_MAX_SPEC_VALUE_CHARS = 90


def normalize_fact(text: str) -> str:
    """Lowercased, punctuation-light form used to compare two facts."""
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def spec_rank(key: str) -> int:
    """Position in `_VISUAL_SPEC_ORDER`, or the end of the queue."""
    low = key.lower()
    for index, token in enumerate(_VISUAL_SPEC_ORDER):
        if token in low:
            return index
    return len(_VISUAL_SPEC_ORDER)


def extract_visual_specs(specs: Any) -> list[tuple[str, str]]:
    """
    Extract the rows of a spec table that describe how the product actually looks.

    Filters out metadata that cannot be photographed (e.g., "Net Quantity: 1 Count").
    Returns sorted (key, value) pairs.
    """
    if not isinstance(specs, dict):
        return []
    rows: list[tuple[str, str]] = []
    for raw_key, raw_value in specs.items():
        key = str(raw_key).strip().rstrip(":")
        value = str(raw_value).strip().rstrip(".")
        if not key or not value or len(value) > _MAX_SPEC_VALUE_CHARS:
            continue
        low = key.lower()
        if any(skip in low for skip in _SKIP_SPEC_KEYS):
            continue
        if any(m in low for m in _MEASUREMENT_KEYS):
            continue
        if spec_rank(key) == len(_VISUAL_SPEC_ORDER):
            continue
        rows.append((key, value))
    rows.sort(key=lambda row: spec_rank(row[0]))
    return rows


def extract_measurements(specs: Any) -> list[str]:
    """
    Extract physical dimensions and weight (e.g., "31.8 x 25.9 x 1.4 cm").
    """
    if not isinstance(specs, dict):
        return []
    out: list[str] = []
    for raw_key, raw_value in specs.items():
        low = str(raw_key).lower()
        value = str(raw_value).strip().rstrip(".")
        if not value or len(value) > _MAX_SPEC_VALUE_CHARS:
            continue
        if not any(m in low for m in _MEASUREMENT_KEYS):
            continue
        if any(value in kept or kept in value for kept in out):
            continue
        out.append(value)
    return out[:2]


def derive_must_preserve(
    overview: dict[str, Any] | None = None,
    specs: dict[str, Any] | None = None,
    materials: list[str] | None = None,
    about_this_item: list[str] | None = None,
    selected_color: str | None = None,
    title: str = "",
) -> list[str]:
    """
    Derive the must_preserve list of authentic physical product features.

    Avoids keyword-stuffed title strings in favor of concrete physical specs:
    materials, exact colorway, neckline/collar, sleeve, silhouette, and tactile finish.
    """
    must_preserve: list[str] = []
    seen: set[str] = set()

    def _add(fact: str) -> None:
        clean = fact.strip().rstrip(".;,")
        norm = normalize_fact(clean)
        if norm and norm not in seen and len(clean) > 4:
            seen.add(norm)
            must_preserve.append(clean)

    # 1. Colorway
    if selected_color and selected_color.strip():
        _add(f"Authentic colorway: {selected_color.strip()}")

    # 2. Material & composition
    if materials:
        clean_mats = [m.strip() for m in materials if m.strip() and len(m) < 40]
        if clean_mats:
            _add(f"Exact material composition: {', '.join(clean_mats[:3])}")

    # 3. Visual specs from overview and technical specs
    combined_specs = {}
    if isinstance(overview, dict):
        combined_specs.update(overview)
    if isinstance(specs, dict):
        combined_specs.update(specs)

    visual_rows = extract_visual_specs(combined_specs)
    for key, value in visual_rows:
        if len(must_preserve) >= 6:
            break
        _add(f"{key}: {value}")

    # 4. Bullet points (only substantive physical points, not marketing guarantees)
    if about_this_item:
        marketing_blockers = (
            "warranty", "guarantee", "customer service", "return",
            "satisfaction", "gift", "perfect for", "best choice",
            "easy to clean", "machine wash", "imported",
        )
        for bullet in about_this_item:
            b_clean = bullet.strip().rstrip(".")
            low = b_clean.lower()
            if any(blk in low for blk in marketing_blockers):
                continue
            # Keep concise physical descriptor (often before a colon, e.g. "DESIGN: High-waisted seamless")
            if ":" in b_clean:
                prefix, rest = b_clean.split(":", 1)
                if len(prefix) < 30 and len(rest) > 10:
                    _add(f"{prefix.strip()}: {rest.strip()[:60]}")
                    continue
            if len(b_clean) < 70:
                _add(b_clean)
            if len(must_preserve) >= 7:
                break

    # 5. Clean fallback if no specs were present (never keyword-stuffed title)
    if not must_preserve:
        clean_title = re.sub(r"[,\-|].*$", "", title).strip()
        if clean_title and len(clean_title) <= 50:
            _add(f"Original physical form and proportions of {clean_title}")
        else:
            _add("Original physical silhouette, authentic materials, and hardware construction")
        _add("Authentic surface textures, seams, and tactile finish without invented features")

    return must_preserve[:8]
