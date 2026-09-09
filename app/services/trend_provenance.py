"""
Provenance contract for trend data — the CI truth guard.

Every trend payload served to the UI must carry explicit provenance flags so
fabricated numbers can never ship unlabeled again. ``check_*()`` helpers take
a payload and return a list of violation strings; an empty list means clean.

This module is deliberately dependency-free (no imports from the app) so the
contract itself can never break because a service module changed. Callers pass
in the demo-ASIN registry explicitly.

Covered surfaces:
- official trend list items + list responses (is_fallback / provenance)
- dossiers incl. score-breakdown sources, heat badges, matched products
- deep-dives (metric_provenance, related-searches provenance, pins)
- popular pins (Pinterest source + real pinimg URL)
- products (demo_only flag + registry membership for demos)
"""
from __future__ import annotations

from typing import Any, FrozenSet

OFFICIAL_PROVENANCES = frozenset({"live", "curated_fallback"})
DOSSIER_ORIGINS = frozenset({"curated_seed", "pinterest_live", "custom_query"})
DEMAND_SOURCES = frozenset({"pinterest_measured", "autocomplete_breadth_proxy"})
MONEY_SOURCES = frozenset({"live_products", "neutral_no_data"})
WINNABILITY_SOURCES = frozenset({"angle_breadth_proxy"})
METRIC_PROVENANCES = frozenset({"live", "unavailable"})
PIN_SOURCES = ("Pinterest Trends (Official)", "Pinterest Live Search")

# Sparkline shapes that were historically hardcoded placeholders. A live item
# carrying one of these without a fallback flag is lying about its chart.
PLACEHOLDER_SPARKLINES = frozenset({
    (10, 20, 35, 50, 75, 100),
    (10, 15, 20, 28, 38, 50, 65, 80),
    (5, 8, 12, 22, 45, 80, 100),
    (5, 8, 12, 25, 50, 80, 100),
})


def _images_of(item: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for key in ("preview_images",):
        val = item.get(key)
        if isinstance(val, list):
            urls.extend(u for u in val if isinstance(u, str))
    single = item.get("image_url")
    if isinstance(single, str):
        urls.append(single)
    return urls


def check_official_item(item: Any) -> list[str]:
    """Validate one official-trends list entry."""
    errs: list[str] = []
    if not isinstance(item, dict):
        return ["official item is not a dict"]
    is_fb = item.get("is_fallback")
    prov = item.get("provenance")
    if not isinstance(is_fb, bool):
        errs.append("official item missing bool 'is_fallback'")
    if prov not in OFFICIAL_PROVENANCES:
        errs.append(f"official item has unknown provenance {prov!r}")
    if is_fb is not True:
        for url in _images_of(item):
            if "unsplash.com" in url:
                errs.append(f"official item serves stock photo unlabeled: {url[:80]}")
                break
        spark = item.get("sparkline")
        if isinstance(spark, list) and tuple(spark) in PLACEHOLDER_SPARKLINES:
            errs.append(f"official item serves placeholder sparkline unlabeled: {spark}")
    return errs


def check_official_list_response(payload: Any) -> list[str]:
    """Validate GET /pinterest-official-trends response envelope + items."""
    errs: list[str] = []
    if not isinstance(payload, dict):
        return ["official list response is not a dict"]
    is_fb = payload.get("is_fallback")
    source = payload.get("source")
    if not isinstance(is_fb, bool):
        errs.append("official list response missing bool 'is_fallback'")
    if not isinstance(source, str) or not source:
        errs.append("official list response missing 'source'")
    if isinstance(is_fb, bool) and isinstance(source, str) and source:
        if is_fb and source != "curated_fallback":
            errs.append(f"fallback response claims source {source!r}")
        if not is_fb and source != "trends.pinterest.com":
            errs.append(f"live response claims source {source!r}")
    trends = payload.get("trends")
    if not isinstance(trends, list):
        errs.append("official list response missing 'trends' list")
    else:
        for i, t in enumerate(trends):
            errs.extend(f"trends[{i}]: {e}" for e in check_official_item(t))
    return errs


def check_product(prod: Any, demo_asins: FrozenSet[str]) -> list[str]:
    """Validate one matched product: flag always present, demos registered."""
    errs: list[str] = []
    if not isinstance(prod, dict):
        return ["product is not a dict"]
    demo = prod.get("demo_only")
    if not isinstance(demo, bool):
        errs.append(f"product {prod.get('asin')!r} missing bool 'demo_only'")
        return errs
    if demo:
        asin = str(prod.get("asin") or "").strip().upper()
        if asin not in demo_asins:
            errs.append(f"demo product {asin!r} not in demo-ASIN registry (ingestible!)")
    return errs


def check_dossier(dossier: Any, demo_asins: FrozenSet[str]) -> list[str]:
    """Validate one radar dossier: origin, breakdown sources, badge, products."""
    errs: list[str] = []
    if not isinstance(dossier, dict):
        return ["dossier is not a dict"]
    if dossier.get("origin") not in DOSSIER_ORIGINS:
        errs.append(f"dossier {dossier.get('id')!r} has unknown origin {dossier.get('origin')!r}")
    badge = dossier.get("heat_badge")
    if isinstance(badge, str) and "%" in badge:
        errs.append(f"dossier {dossier.get('id')!r} badge invents a percentage: {badge!r}")
    bd = dossier.get("score_breakdown")
    if not isinstance(bd, dict):
        errs.append(f"dossier {dossier.get('id')!r} missing 'score_breakdown'")
    else:
        if bd.get("demand_source") not in DEMAND_SOURCES:
            errs.append(f"dossier {dossier.get('id')!r} has unknown demand_source {bd.get('demand_source')!r}")
        if bd.get("money_source") not in MONEY_SOURCES:
            errs.append(f"dossier {dossier.get('id')!r} has unknown money_source {bd.get('money_source')!r}")
        if bd.get("winnability_source") not in WINNABILITY_SOURCES:
            errs.append(f"dossier {dossier.get('id')!r} has unknown winnability_source {bd.get('winnability_source')!r}")
    prods = dossier.get("matched_products")
    if not isinstance(prods, list):
        errs.append(f"dossier {dossier.get('id')!r} missing 'matched_products' list")
    else:
        for i, p in enumerate(prods):
            errs.extend(f"matched_products[{i}]: {e}" for e in check_product(p, demo_asins))
    return errs


def check_pin(pin: Any) -> list[str]:
    """Validate one popular pin: Pinterest source + real pinimg URL."""
    errs: list[str] = []
    if not isinstance(pin, dict):
        return ["pin is not a dict"]
    if pin.get("source") not in PIN_SOURCES:
        errs.append(f"pin {pin.get('pin_id')!r} has non-Pinterest source {pin.get('source')!r}")
    url = pin.get("image_url")
    if not isinstance(url, str) or "i.pinimg.com" not in url:
        errs.append(f"pin {pin.get('pin_id')!r} has non-Pinterest image URL {url!r}")
    return errs


def check_deep_dive(data: Any, demo_asins: FrozenSet[str]) -> list[str]:
    """Validate one deep-dive payload, including the strict unavailable shape."""
    errs: list[str] = []
    if not isinstance(data, dict):
        return ["deep-dive is not a dict"]
    prov = data.get("metric_provenance")
    if prov not in METRIC_PROVENANCES:
        errs.append(f"deep-dive {data.get('term')!r} has unknown metric_provenance {prov!r}")
    if prov == "unavailable":
        if data.get("mom_change") is not None:
            errs.append("unavailable deep-dive carries mom_change")
        if data.get("wow_change") is not None:
            errs.append("unavailable deep-dive carries wow_change")
        if data.get("search_count") is not None:
            errs.append("unavailable deep-dive carries search_count")
        if data.get("sparkline") not in (None, []):
            errs.append(f"unavailable deep-dive carries sparkline {data.get('sparkline')!r}")
        if data.get("indexing_window") is not None:
            errs.append("unavailable deep-dive carries indexing_window")
        if data.get("timeline_dates") not in (None, []):
            errs.append("unavailable deep-dive carries timeline_dates")
    if data.get("related_searches_provenance") != "generated":
        errs.append("deep-dive related searches missing 'generated' provenance")
    if not isinstance(data.get("related_searches"), list):
        errs.append("deep-dive missing 'related_searches' list")
    pins = data.get("popular_pins")
    if not isinstance(pins, list):
        errs.append("deep-dive missing 'popular_pins' list")
    else:
        for i, p in enumerate(pins):
            errs.extend(f"popular_pins[{i}]: {e}" for e in check_pin(p))
    return errs


def check_detail_response(payload: Any, demo_asins: FrozenSet[str]) -> list[str]:
    """Validate GET .../detail response envelope."""
    if not isinstance(payload, dict):
        return ["detail response is not a dict"]
    if "data" not in payload:
        return ["detail response missing 'data'"]
    return [f"data: {e}" for e in check_deep_dive(payload.get("data"), demo_asins)]
