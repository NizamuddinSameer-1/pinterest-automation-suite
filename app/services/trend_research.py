"""
Global Trend Radar & Product Research Engine.

Discovers real-time market trends, seasonal surges, and high-demand products:
- Scans Google Shopping Autocomplete (ds=sh) for commercial intent queries.
- Classifies trends into Breakout (🔥), Rising (📈), and Evergreen (🌲).
- Calculates Commercial EPC & Opportunity Scores (Tier S / A / B).
- Recommends 2026 Outfit Formulas, Scene Aesthetics, and Target Pinterest Boards.
- Automatically connects trends to high-rated Amazon affiliate products.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import urllib.parse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import httpx

from app.config import settings
from app.services.affiliate_router import build_smart_redirect_url
from app.services.amazon_paapi import paapi_client
from app.services.trend_sources import SourceSignal, fetch_amazon_movers, fetch_gtrends, fetch_pinterest, fetch_shopping
from app.services.trend_scorer import score_trend
from app.services.keyword_packs import build_pack

logger = logging.getLogger("pre.trend_research")

GOOGLE_SHOPPING_SUGGEST_URL = "https://suggestqueries.google.com/complete/search"

_SCAN_SEMAPHORE = asyncio.Semaphore(4)


def _weights_fingerprint(weights: dict[str, float]) -> str:
    src = f"{weights.get('demand')}|{weights.get('money')}|{weights.get('winnability')}"
    return hashlib.sha1(src.encode("utf-8")).hexdigest()[:8]


def _current_weights() -> dict[str, float]:
    """Single source for scoring weights — keeps dossiers, cache keys and
    snapshots fingerprinted consistently by construction."""
    return {
        "demand": settings.trend_weight_demand,
        "money": settings.trend_weight_money,
        "winnability": settings.trend_weight_winnability,
    }


def _current_weights_fingerprint() -> str:
    return _weights_fingerprint(_current_weights())


# Snapshot payload version. Bump when the dossier contract changes so stale
# files (old scores, missing provenance) trigger a rescan instead of serving.
SNAPSHOT_VERSION = 2


@dataclass
class ResearchedProduct:
    asin: str
    title: str
    price: float
    currency: str = "USD"
    rating: float = 4.5
    review_count: int = 250
    image_url: str = ""
    affiliate_url: str = ""
    smart_url: str = ""
    commission_rate: str = "4.0% – 8.0%"
    prime_eligible: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TrendDossier:
    id: str
    title: str
    category: str
    heat_level: str  # breakout | rising | emerging | steady | evergreen
    heat_badge: str  # display label only — never carries invented percentages
    opportunity_score: int  # 0 to 100
    tier: str  # Tier S | Tier A | Tier B
    aesthetic_vibe: str
    outfit_or_scene: str
    recommended_board: str
    related_queries: list[str] = field(default_factory=list)
    matched_products: list[dict[str, Any]] = field(default_factory=list)
    discovered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    origin: str = "curated_seed"  # curated_seed | pinterest_live | custom_query

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Curated Seed Taxonomy for Autonomous Scanning ─────────────────────────
TREND_SEEDS: dict[str, list[dict[str, Any]]] = {
    "fashion": [
        {
            "id": "barn_jacket_heritage",
            "title": "Corduroy Barn Jacket & Heritage Workwear",
            "seed_query": "barn jacket",
            "category": "fashion",
            "heat_level": "breakout",
            "heat_badge": "🔥 Breakout",
            "opportunity_score": 96,
            "tier": "Tier S",
            "aesthetic_vibe": "Countryside English Heritage meets Modern Raw Denim",
            "outfit_or_scene": "Corduroy-collar canvas utility jacket + cream chunky knit + straight-leg raw denim + lug-sole boots",
            "recommended_board": "Autumn Barn Jackets & Casual Layers",
            "fallback_products": [
                {
                    "asin": "B0DG12BARN",
                    "title": "Vintage Corduroy Collar Waxed Canvas Utility Jacket",
                    "price": 54.99,
                    "rating": 4.6,
                    "review_count": 840,
                    "image_url": "https://images.unsplash.com/photo-1544441893-675973e31985?w=500&q=80",
                },
                {
                    "asin": "B0CG23BOOT",
                    "title": "Water-Resistant Chunky Lug-Sole Chelsea Boots",
                    "price": 46.99,
                    "rating": 4.5,
                    "review_count": 1250,
                    "image_url": "https://images.unsplash.com/photo-1543163521-1bf539c55dd2?w=500&q=80",
                },
            ],
        },
        {
            "id": "capsule_knitwear",
            "title": "Oversized Waffle Chunky Knit Cardigan",
            "seed_query": "chunky cardigan sweater",
            "category": "fashion",
            "heat_level": "evergreen",
            "heat_badge": "🌲 Evergreen Staple",
            "opportunity_score": 92,
            "tier": "Tier S",
            "aesthetic_vibe": "Quiet Luxury French Minimalist Layering",
            "outfit_or_scene": "Slouchy oatmeal fisherman cardigan + tailored pleated trousers + minimalist gold hoops + latte cup",
            "recommended_board": "Cozy Fall Knitwear & Layering",
            "fallback_products": [
                {
                    "asin": "B0BG77KNIT",
                    "title": "Slouchy Button-Down Chunky Cable Knit Cardigan",
                    "price": 38.99,
                    "rating": 4.5,
                    "review_count": 2100,
                    "image_url": "https://images.unsplash.com/photo-1584273143981-41c073dfe8f8?w=500&q=80",
                },
                {
                    "asin": "B0C99PANTS",
                    "title": "High-Waisted Wide Leg Pleated Drape Trousers",
                    "price": 34.99,
                    "rating": 4.4,
                    "review_count": 920,
                    "image_url": "https://images.unsplash.com/photo-1509631179647-0177331693ae?w=500&q=80",
                },
            ],
        },
        {
            "id": "dark_academia_trench",
            "title": "Double-Breasted Wool Blend Trench Coat",
            "seed_query": "wool trench coat women",
            "category": "fashion",
            "heat_level": "rising",
            "heat_badge": "📈 Rising Wave",
            "opportunity_score": 88,
            "tier": "Tier A",
            "aesthetic_vibe": "Dark Academia London Streetstyle",
            "outfit_or_scene": "Tailored charcoal trench + black turtleneck + plaid pleated midi skirt + leather messenger bag",
            "recommended_board": "Dark Academia Outfits & Aesthetic",
            "fallback_products": [
                {
                    "asin": "B0BF55TRCH",
                    "title": "Classic Double-Breasted Long Wool Trench Overcoat",
                    "price": 69.99,
                    "rating": 4.6,
                    "review_count": 560,
                    "image_url": "https://images.unsplash.com/photo-1539533018447-63fcce667883?w=500&q=80",
                },
            ],
        },
    ],
    "home": [
        {
            "id": "japandi_living_decor",
            "title": "Warm Japandi Textured Stoneware & Fluted Vases",
            "seed_query": "fluted ceramic vase",
            "category": "home",
            "heat_level": "evergreen",
            "heat_badge": "🌲 Evergreen Aesthetic",
            "opportunity_score": 94,
            "tier": "Tier S",
            "aesthetic_vibe": "Minimalist Organic Wabi-Sabi Sanctuary",
            "outfit_or_scene": "Matte ribbed beige stoneware vase on raw oak coffee table, morning low-angle sun rays, dried pampas",
            "recommended_board": "Japandi Living Room & Organic Decor",
            "fallback_products": [
                {
                    "asin": "B0C1VASE01",
                    "title": "Handmade Ceramic Fluted Donut Vase Matte Finish",
                    "price": 28.99,
                    "rating": 4.8,
                    "review_count": 1400,
                    "image_url": "https://images.unsplash.com/photo-1612196808214-b8e1d6145a8c?w=500&q=80",
                },
                {
                    "asin": "B0C9COFF02",
                    "title": "Modern Nordic Travertine Coasters Set of 4",
                    "price": 22.99,
                    "rating": 4.7,
                    "review_count": 480,
                    "image_url": "https://images.unsplash.com/photo-1586023492125-27b2c045efd7?w=500&q=80",
                },
            ],
        },
        {
            "id": "ambient_bedroom_lighting",
            "title": "Sunset Ambient Projection Lamp & Mood Glow",
            "seed_query": "sunset projection lamp",
            "category": "home",
            "heat_level": "rising",
            "heat_badge": "📈 Rising Demand",
            "opportunity_score": 89,
            "tier": "Tier A",
            "aesthetic_vibe": "Warm Sunset Golden Hour Dream Bedroom",
            "outfit_or_scene": "Warm golden gradient glow against textured bedroom linen wall, bedside book and acoustic candle",
            "recommended_board": "Cozy Bedroom Aesthetic & Lighting",
            "fallback_products": [
                {
                    "asin": "B08ZLAMP99",
                    "title": "360° Rotation Halo Sunset Projection Ambient Lamp",
                    "price": 21.99,
                    "rating": 4.4,
                    "review_count": 3200,
                    "image_url": "https://images.unsplash.com/photo-1513506003901-1e6a229e2d15?w=500&q=80",
                },
            ],
        },
    ],
    "kitchen": [
        {
            "id": "aesthetic_barista_coffee",
            "title": "Minimalist Countertop Coffee Bar & Matcha Setup",
            "seed_query": "matcha whisk set bamboo",
            "category": "kitchen",
            "heat_level": "breakout",
            "heat_badge": "🔥 Breakout",
            "opportunity_score": 95,
            "tier": "Tier S",
            "aesthetic_vibe": "Artisanal Home Cafe & Morning Rituals",
            "outfit_or_scene": "Speckled ceramic matcha bowl with bamboo chasen, frothy emerald green pour, clean butcher block counter",
            "recommended_board": "Coffee Bar Station & Kitchen Inspo",
            "fallback_products": [
                {
                    "asin": "B09MATCHA1",
                    "title": "Traditional Japanese Handmade Bamboo Matcha Whisk & Bowl Set",
                    "price": 32.99,
                    "rating": 4.8,
                    "review_count": 1850,
                    "image_url": "https://images.unsplash.com/photo-1576092768241-dec231879fc3?w=500&q=80",
                },
                {
                    "asin": "B0B8GLASS2",
                    "title": "Ribbed Vintage Iced Coffee Glassware with Glass Straws",
                    "price": 24.99,
                    "rating": 4.7,
                    "review_count": 2900,
                    "image_url": "https://images.unsplash.com/photo-1514432324607-a09d9b4aefdd?w=500&q=80",
                },
            ],
        },
    ],
    "tech": [
        {
            "id": "minimal_desk_setup",
            "title": "Clean Desk Setup: Felt Wool Pad & Monitor Bar Light",
            "seed_query": "felt desk pad",
            "category": "tech",
            "heat_level": "evergreen",
            "heat_badge": "🌲 Evergreen Productivity",
            "opportunity_score": 91,
            "tier": "Tier S",
            "aesthetic_vibe": "Distraction-Free Scandinavian Desk Sanctuary",
            "outfit_or_scene": "Dark grey merino wool felt desk mat, aluminum mechanical keyboard, warm monitor bar glow, brass pen tray",
            "recommended_board": "Minimalist Desk Setup & Tech Space",
            "fallback_products": [
                {
                    "asin": "B09DESKPAD",
                    "title": "Large Merino Wool Felt Desk Pad Mat Non-Slip",
                    "price": 29.99,
                    "rating": 4.6,
                    "review_count": 1100,
                    "image_url": "https://images.unsplash.com/photo-1527443224154-c4a3942d3acf?w=500&q=80",
                },
                {
                    "asin": "B08SCRNBAR",
                    "title": "Auto-Dimming USB Screenbar Monitor Reading LED Light",
                    "price": 42.99,
                    "rating": 4.5,
                    "review_count": 4300,
                    "image_url": "https://images.unsplash.com/photo-1587829741301-dc798b83add3?w=500&q=80",
                },
            ],
        },
    ],
    "seasonal": [
        {
            "id": "pumpkin_patch_autumn",
            "title": "Pumpkin Patch Outfits & Cozy Farm Layering",
            "seed_query": "pumpkin patch outfit women",
            "category": "seasonal",
            "heat_level": "breakout",
            "heat_badge": "🔥 Season Peak",
            "opportunity_score": 98,
            "tier": "Tier S",
            "aesthetic_vibe": "Autumn Harvest Farm Aesthetic in Golden Hour",
            "outfit_or_scene": "Oversized rust cable knit sweater + corduroy A-line skirt + knee-high suede boots against rustic barn backdrop",
            "recommended_board": "Pumpkin Patch Outfits",
            "fallback_products": [
                {
                    "asin": "B08PUMPKIN",
                    "title": "Chunky Turtleneck Oversized Cable Knit Sweater Dress",
                    "price": 42.99,
                    "rating": 4.5,
                    "review_count": 3100,
                    "image_url": "https://images.unsplash.com/photo-1509551388413-e18d0ac5d495?w=500&q=80",
                },
                {
                    "asin": "B07SUEDEBT",
                    "title": "Knee High Faux Suede Slouchy Autumn Riding Boots",
                    "price": 58.99,
                    "rating": 4.4,
                    "review_count": 1600,
                    "image_url": "https://images.unsplash.com/photo-1543163521-1bf539c55dd2?w=500&q=80",
                },
            ],
        },
    ],
}


# ── Google Shopping Autocomplete Client ───────────────────────────────────

async def fetch_shopping_suggestions(seed_query: str, max_results: int = 6) -> list[str]:
    """
    Fetch real-time shopping autocomplete queries from Google's Shopping engine (ds=sh).
    Completely free, fast, and reveals high-commercial-intent search queries.
    """
    clean_seed = seed_query.strip()
    if not clean_seed:
        return []

    params = {
        "client": "chrome",
        "ds": "sh",  # Domain Service = Shopping
        "q": clean_seed,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*",
    }

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(GOOGLE_SHOPPING_SUGGEST_URL, params=params, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list):
                    queries = [str(q).strip() for q in data[1] if str(q).strip()]
                    return queries[:max_results]
    except Exception as e:
        logger.warning("Google Shopping suggestion fetch failed for %r: %s", clean_seed, e)

    return []


# ── Demo ASIN registry ────────────────────────────────────────────────────
# The TREND_SEEDS fallback_products below carry invented ASINs (e.g. B0DG12BARN)
# that are NOT real Amazon listings. They exist so the Trend Radar UI can render
# something useful while PA-API is offline. They must NEVER be ingested as real
# Products — launch-campaign rejects them (see app/api/research.py).
# Synthetic last-resort ASINs emitted by the matcher itself (B0SEARCH01 for the
# query-shaped placeholder, B0DEMOASIN1 for asin-less fallbacks) are blocked too —
# they are not seed data, so they are listed explicitly, not collected.
_SYNTHETIC_ASINS = frozenset({"B0SEARCH01", "B0DEMOASIN1"})


def _collect_demo_asins() -> frozenset[str]:
    demo: set[str] = set(_SYNTHETIC_ASINS)
    for seeds in TREND_SEEDS.values():
        for seed in seeds:
            for item in seed.get("fallback_products") or []:
                asin = str(item.get("asin") or "").strip().upper()
                if asin:
                    demo.add(asin)
    return frozenset(demo)


DEMO_ASINS: frozenset[str] = _collect_demo_asins()


# ── Live Amazon Product Matcher ───────────────────────────────────────────

def _clean_price(val: Any, default: float = 39.99) -> float:
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val) if val > 0 else default
    cleaned = re.sub(r"[^\d.]", "", str(val))
    if not cleaned:
        return default
    try:
        if cleaned.count(".") > 1:
            parts = cleaned.split(".")
            cleaned = "".join(parts[:-1]) + "." + parts[-1]
        v = float(cleaned)
        return v if v > 0 else default
    except ValueError:
        return default


def _clean_rating(val: Any, default: float = 4.5) -> float:
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val) if 0 < val <= 5.0 else default
    cleaned = re.sub(r"[^\d.]", "", str(val))
    if not cleaned:
        return default
    try:
        r = float(cleaned)
        return r if 0 < r <= 5.0 else default
    except ValueError:
        return default


def _clean_reviews(val: Any, default: int = 350) -> int:
    if val is None:
        return default
    if isinstance(val, int):
        return val if val >= 0 else default
    if isinstance(val, float):
        return int(val)
    cleaned = re.sub(r"[^\d]", "", str(val))
    if not cleaned:
        return default
    try:
        return int(cleaned)
    except ValueError:
        return default


async def match_amazon_products_for_trend(
    query: str,
    category: str = "fashion",
    fallback_items: list[dict[str, Any]] | None = None,
    item_count: int = 2,
) -> list[dict[str, Any]]:
    """
    Search Amazon for top-converting affiliate products matching a trending topic.
    Uses PA-API 5.0 / Amazon Product Engine with real pricing, ratings, and affiliate link generation.
    Falls back gracefully to curated high-converting products if offline.
    """
    results: list[dict[str, Any]] = []

    # Map PRE category to Amazon search index
    index_map = {
        "fashion": "Fashion",
        "home": "HomeGarden",
        "kitchen": "HomeGarden",
        "tech": "All",
        "seasonal": "Fashion",
    }
    search_index = index_map.get(category, "All")

    try:
        raw_items = await paapi_client.search_items(
            keywords=query,
            search_index=search_index,
            item_count=item_count,
            sort_by="AvgCustomerReviews",
            country="US",
        )
        for item in raw_items:
            asin = item.get("asin")
            if not asin:
                continue
            title = item.get("title") or query.title()
            # Support both price_amount (float) and price (string or float)
            price_raw = item.get("price_amount") if item.get("price_amount") is not None else item.get("price")
            price = _clean_price(price_raw, 39.99)
            # Support both primary_image_url and image_url
            image_url = item.get("primary_image_url") or item.get("image_url") or ""
            # Support both star_rating and rating
            rating_raw = item.get("star_rating") if item.get("star_rating") is not None else item.get("rating")
            rating = _clean_rating(rating_raw, 4.5)
            review_count = _clean_reviews(item.get("review_count"), 350)

            # Build smart affiliate link
            smart_url = build_smart_redirect_url(
                asin=asin,
                title=title,
                asin_in=item.get("asin_in"),
            )

            results.append({
                "asin": asin,
                "title": title,
                "price": price,
                "currency": item.get("currency") or "USD",
                "rating": rating,
                "review_count": review_count,
                "image_url": image_url,
                "affiliate_url": item.get("affiliate_url") or smart_url,
                "smart_url": smart_url,
                "commission_rate": "4.0% – 8.0%",
                "prime_eligible": bool(item.get("is_prime", True)),
                "demo_only": False,
            })
    except Exception as e:
        logger.warning("PA-API search failed for trend %r (%s): %s", query, category, e)

    # If PA-API yielded few or no results, use rich curated fallbacks with smart affiliate links.
    # These are DEMO-ONLY placeholders (invented ASINs, Unsplash photos, illustrative
    # prices/ratings) — flagged so launch-campaign refuses to ingest them as real Products.
    if not results and fallback_items:
        for f in fallback_items:
            asin = f.get("asin", "B0DEMOASIN1")
            title = f.get("title", query.title())
            smart_url = build_smart_redirect_url(asin=asin, title=title)
            results.append({
                "asin": asin,
                "title": title,
                "price": _clean_price(f.get("price"), 39.99),
                "currency": "USD",
                "rating": _clean_rating(f.get("rating"), 4.6),
                "review_count": _clean_reviews(f.get("review_count"), 500),
                "image_url": f.get("image_url", ""),
                "affiliate_url": smart_url,
                "smart_url": smart_url,
                "commission_rate": "4.5% – 8.0%",
                "prime_eligible": True,
                "demo_only": True,
            })

    # If still empty (e.g. custom search without seeds when scraper is rate-limited):
    if not results:
        smart_url = build_smart_redirect_url(asin=None, title=query)
        results.append({
            "asin": "B0SEARCH01",
            "title": f"Top Rated {query.title()} on Amazon",
            "price": 34.99,
            "currency": "USD",
            "rating": 4.6,
            "review_count": 520,
            "image_url": "https://images.unsplash.com/photo-1441986300917-64674bd600d8?w=500&q=80",
            "affiliate_url": smart_url,
            "smart_url": smart_url,
            "commission_rate": "4.0% – 8.0%",
            "prime_eligible": True,
            "demo_only": True,
        })

    return results[:item_count]


def _write_snapshot(dossiers: list[dict[str, Any]], prune_missing_origin: str | None = None) -> None:
    """Persist the daily snapshot, merging existing dossiers by id so single-category scans don't wipe others.

    When prune_missing_origin is set (full scans only), previously stored
    dossiers with that origin but absent from this batch are evicted — this
    keeps dynamic entries (e.g. yesterday's Pinterest terms) from lingering
    in the snapshot forever.
    """
    try:
        snap_dir = Path(settings.storage_path) / "trend_radar"
        snap_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        snap_file = snap_dir / f"{stamp}.json"

        merged_map: dict[str, dict[str, Any]] = {}
        if snap_file.exists():
            try:
                existing_payload = json.loads(snap_file.read_text(encoding="utf-8"))
                for d in existing_payload.get("dossiers") or []:
                    if "id" in d:
                        merged_map[d["id"]] = d
            except Exception:
                pass

        for d in dossiers:
            if "id" in d:
                merged_map[d["id"]] = d

        if prune_missing_origin:
            incoming_ids = {d["id"] for d in dossiers if "id" in d}
            for did in [k for k, v in merged_map.items()
                        if v.get("origin") == prune_missing_origin and k not in incoming_ids]:
                del merged_map[did]

        all_dossiers = list(merged_map.values())
        all_dossiers.sort(key=lambda x: x.get("opportunity_score", 0), reverse=True)

        snap_file.write_text(
            json.dumps({
                "snapshot_version": SNAPSHOT_VERSION,
                "weights_fingerprint": _current_weights_fingerprint(),
                "scanned_at": datetime.now(timezone.utc).isoformat(),
                "count": len(all_dossiers),
                "dossiers": all_dossiers,
            }, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("Trend snapshot write failed: %s", e)


def select_snapshot_dossiers(
    payload: dict[str, Any] | None,
    category: str | None,
    max_age_s: float = 3600,
    scanned_at_s: float | None = None,
    now_s: float | None = None,
) -> list[dict[str, Any]] | None:
    """Validate a radar snapshot payload; return category-filtered dossiers or None.

    Returns None (caller rescans live) when the payload is version-stale,
    was computed under different scoring weights, is older than max_age_s,
    or holds no rows for the requested category. Pure function for testability
    (pass scanned_at_s/now_s to avoid clock dependence).
    """
    try:
        if not isinstance(payload, dict):
            return None
        if payload.get("snapshot_version") != SNAPSHOT_VERSION:
            return None
        if payload.get("weights_fingerprint") != _current_weights_fingerprint():
            return None
        if scanned_at_s is not None and now_s is not None and (now_s - scanned_at_s) > max_age_s:
            return None
        dossiers = payload.get("dossiers") or []
        if category and category != "all":
            dossiers = [d for d in dossiers if d.get("category") == category]
        return dossiers if dossiers else None
    except Exception:
        return None


# ── Full Trend Discovery & Radar Generator ────────────────────────────────

# Pinterest's own categories vs the radar's buckets: beauty content is
# commerce-adjacent (nails, hair, cosmetics), so it maps to fashion. The raw
# Pinterest category is preserved on the dossier as pinterest_category.
_PINTEREST_CATEGORY_MAP = {"beauty": "fashion"}


def _map_pinterest_category(raw: Any) -> str:
    cat = str(raw or "fashion").strip().lower() or "fashion"
    return _PINTEREST_CATEGORY_MAP.get(cat, cat)


def _heat_for_mom(mom: Any) -> tuple[str, str]:
    """Heat level/badge from measured MoM growth — thresholds only, no invented percentages."""
    try:
        m = float(mom or 0.0)
    except (TypeError, ValueError):
        m = 0.0
    if m >= 300:
        return "breakout", "🔥 Breakout"
    if m >= 50:
        return "rising", "📈 Trending"
    if m > 0:
        return "emerging", "🌱 Emerging"
    return "steady", "📌 Evergreen"


async def _fetch_pinterest_discovery(category_filter: str | None = None, limit: int = 6) -> list[dict[str, Any]]:
    """Pull today's measured Pinterest trends (cache-first) for radar ingestion.

    Reads the snapshot cache the daily scheduler warms — never forces a live
    scrape from the radar path. Curated demo entries are never ingested as
    discovery. Fail-soft per preset; raises only if the import itself fails.
    """
    from app.services.pinterest_trends_scraper import get_official_pinterest_trends

    seen: set[str] = set()
    collected: list[dict[str, Any]] = []
    for preset in ("breakout", "growing", "top"):
        try:
            trends = await get_official_pinterest_trends(preset=preset, intent="all", force_refresh=False)
        except Exception as e:
            logger.warning("Pinterest discovery fetch failed for preset %r: %s", preset, e)
            continue
        for t in trends or []:
            if not isinstance(t, dict) or t.get("is_fallback"):
                continue
            term = (t.get("term") or "").strip()
            key = term.lower()
            if not term or key in seen:
                continue
            seen.add(key)
            collected.append(t)

    if category_filter and category_filter != "all":
        collected = [t for t in collected
                     if _map_pinterest_category(t.get("category", "fashion")) == category_filter]

    def _strength(t: dict[str, Any]) -> tuple[int, float]:
        sc = t.get("search_count")
        try:
            return (1, float(sc)) if sc is not None else (0, 0.0)
        except (TypeError, ValueError):
            return (0, 0.0)

    collected.sort(key=_strength, reverse=True)
    return collected[:max(0, limit)]


async def _build_pinterest_dossier(item: dict[str, Any]) -> dict[str, Any] | None:
    """Build a radar dossier from one measured Pinterest trend.

    Demand comes from Pinterest's measured 0-100 search_count when present;
    only then does the breakdown claim demand_source "pinterest_measured".
    Otherwise it degrades honestly to the autocomplete breadth proxy.
    """
    from app.config import settings as _settings

    term = (item.get("term") or "").strip()
    if not term:
        return None
    category = _map_pinterest_category(item.get("category", "fashion"))

    signals = await _scan_seed_signals(term, category)
    related = sorted(
        {q for s in signals for q in s.queries},
        key=lambda q: (len(q), q),
    )[:8] or [term, f"{term} ideas", f"{term} 2026"]

    # No curated fallbacks: offline/unknown terms simply match nothing.
    matched_prods = await match_amazon_products_for_trend(query=term, category=category, item_count=2)

    measured = item.get("search_count")
    try:
        measured_demand = max(0.0, min(100.0, float(measured))) if measured is not None else None
    except (TypeError, ValueError):
        measured_demand = None
    proxy = _blend_signals(signals, products=matched_prods, related=related)
    if measured_demand is None:
        demand, demand_source = proxy["demand"], "autocomplete_breadth_proxy"
    else:
        demand, demand_source = measured_demand, "pinterest_measured"

    _weights = _current_weights()
    scored = score_trend(demand, proxy["money"], proxy["winnability"], weights=_weights)
    scored["breakdown"]["weights_fingerprint"] = _weights_fingerprint(_weights)
    scored["breakdown"]["demand_source"] = demand_source
    scored["breakdown"]["money_source"] = proxy["money_source"]
    scored["breakdown"]["winnability_source"] = proxy["winnability_source"]

    heat_level, heat_badge = _heat_for_mom(item.get("mom_change"))
    pack = build_pack(
        primary=term, related_queries=related,
        board_angle=item.get("recommended_board") or f"{term.title()} Ideas",
        variations_count=4,
    )
    slug = re.sub(r"[^a-z0-9]+", "_", term.lower()).strip("_")
    dossier = TrendDossier(
        id=f"pin-trend-{slug}", title=term.title(), category=category,
        heat_level=heat_level, heat_badge=heat_badge,
        opportunity_score=int(scored["score"]),
        tier=f"Tier {scored['tier']}",
        aesthetic_vibe=f"Trending Pinterest {category.title()} Aesthetic",
        outfit_or_scene=f"Natural lifestyle setting featuring {term}",
        recommended_board=item.get("recommended_board") or f"{term.title()} Ideas",
        related_queries=related, matched_products=matched_prods,
        origin="pinterest_live",
    )
    out = dossier.to_dict()
    out["score_breakdown"] = scored["breakdown"]
    out["keyword_pack"] = pack.to_dict()
    out["sources"] = [s.to_dict() for s in signals]
    out["mom_change"] = item.get("mom_change")
    out["wow_change"] = item.get("wow_change")
    out["search_count"] = item.get("search_count")
    out["sparkline"] = item.get("sparkline") or []
    out["timeline_dates"] = item.get("timeline_dates") or []
    out["pinterest_category"] = item.get("category")
    out["provenance"] = "live"
    return out


async def discover_trends_radar(
    category_filter: str | None = None,
    include_pinterest: bool = True,
    pinterest_limit: int = 6,
) -> list[dict[str, Any]]:
    """
    Generate the full Trend Radar feed: curated seeds re-measured against
    live autocomplete signals PLUS today's actually-trending Pinterest terms
    ingested with their measured search momentum.

    Pinterest ingestion is cache-first (the daily scheduler warms it) and
    fail-soft — a broken scraper degrades to seeds-only, never to demo data.
    """
    categories = [category_filter] if category_filter and category_filter != "all" else list(TREND_SEEDS.keys())

    async def _gated(seed: dict[str, Any]) -> dict[str, Any]:
        async with _SCAN_SEMAPHORE:
            return await _build_trend_dossier(seed)

    tasks = []

    for cat in categories:
        seeds = TREND_SEEDS.get(cat, [])
        for seed in seeds:
            tasks.append(_gated(seed))

    results = await asyncio.gather(*tasks, return_exceptions=False)

    if include_pinterest:
        try:
            pin_items = await _fetch_pinterest_discovery(category_filter, limit=pinterest_limit)
        except Exception as e:
            logger.warning("Pinterest discovery failed, continuing seeds-only: %s", e)
            pin_items = []

        async def _gated_pin(item: dict[str, Any]) -> dict[str, Any] | None:
            async with _SCAN_SEMAPHORE:
                return await _build_pinterest_dossier(item)

        pin_dossiers = await asyncio.gather(
            *(_gated_pin(i) for i in pin_items), return_exceptions=False
        )
        results.extend(d for d in pin_dossiers if d)

    # Sort by opportunity score descending (Tier S first)
    sorted_dossiers = sorted(results, key=lambda x: x.get("opportunity_score", 0), reverse=True)
    full_scan = not category_filter or category_filter == "all"
    _write_snapshot(
        sorted_dossiers,
        prune_missing_origin="pinterest_live" if full_scan else None,
    )
    return sorted_dossiers


async def _scan_seed_signals(seed_query: str, category: str) -> list[SourceSignal]:
    """Fan out to all four source clients; each is fail-soft by contract."""
    results = await asyncio.gather(
        fetch_shopping(seed_query, category),
        fetch_gtrends(seed_query, category),
        fetch_amazon_movers(seed_query, category),
        fetch_pinterest(seed_query, category),
    )
    return list(results)


def _money_from_products(products: list[dict[str, Any]] | None) -> tuple[float, str]:
    """Monetization score from LIVE matched products only (demo placeholders excluded).

    Composite of buyer approval (avg rating / 5) and commercial validation
    (log-scaled review volume). No live products → neutral 50.0, explicitly
    sourced as "neutral_no_data" rather than presented as measured.
    """
    import math

    live = [p for p in (products or []) if isinstance(p, dict) and not p.get("demo_only")]
    if not live:
        return 50.0, "neutral_no_data"

    def _num(p: dict[str, Any], key: str) -> float:
        try:
            return max(0.0, float(p.get(key) or 0))
        except (TypeError, ValueError):
            return 0.0

    ratings = [_num(p, "rating") for p in live]
    ratings = [r for r in ratings if 0 < r <= 5.0]
    rating_score = (sum(ratings) / len(ratings) / 5.0 * 100.0) if ratings else 50.0
    total_reviews = sum(_num(p, "review_count") for p in live)
    volume_score = min(100.0, 20.0 * math.log10(1.0 + total_reviews))
    return round(0.5 * rating_score + 0.5 * volume_score, 1), "live_products"


def _winnability_from_angles(related: Sequence[str] | None) -> float:
    """Angle-breadth proxy: distinct long-tail variations ≈ distinct
    low-competition entry angles for a small creator. Labeled as a proxy,
    not a measured competition rate (no competition API is available)."""
    n = len(related or [])
    return round(min(100.0, 30.0 + 8.0 * n), 1)


def _blend_signals(
    signals: list[SourceSignal],
    products: list[dict[str, Any]] | None = None,
    related: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Blend three 0-100 signals with per-input provenance.

    Demand = mean of fresh hints (0 when all stale) — an autocomplete-BREADTH
    proxy (formulas of suggestion counts), NOT a measured demand rate, unless
    the caller overrides it with measured data. Money is computed from live
    matched products; winnability from angle breadth. No input is a silent
    constant anymore: each carries a *_source label into the breakdown.
    """
    fresh = [s.demand_hint for s in signals if s.status == "fresh"]
    demand = sum(fresh) / len(fresh) if fresh else 0.0
    money, money_source = _money_from_products(products)
    return {
        "demand": round(demand, 1),
        "money": money,
        "money_source": money_source,
        "winnability": _winnability_from_angles(related),
        "winnability_source": "angle_breadth_proxy",
    }


async def _build_trend_dossier(seed: dict[str, Any]) -> dict[str, Any]:
    """Enrich one seed with multi-source signals, blended score, pack, products."""
    from app.config import settings as _settings

    seed_query = seed.get("seed_query", seed["title"])
    category = seed.get("category", "fashion")

    signals = await _scan_seed_signals(seed_query, category)
    related = sorted(
        {q for s in signals for q in s.queries},
        key=lambda q: (len(q), q),
    )[:8] or [seed_query, f"{seed_query} aesthetic", f"{seed_query} 2026"]

    matched_prods = await match_amazon_products_for_trend(
        query=related[0], category=category,
        fallback_items=seed.get("fallback_products"), item_count=2,
    )
    blended = _blend_signals(signals, products=matched_prods, related=related)
    _weights = _current_weights()
    scored = score_trend(
        blended["demand"], blended["money"], blended["winnability"],
        weights=_weights,
    )
    scored["breakdown"]["weights_fingerprint"] = _weights_fingerprint(_weights)
    scored["breakdown"]["demand_source"] = "autocomplete_breadth_proxy"
    scored["breakdown"]["money_source"] = blended["money_source"]
    scored["breakdown"]["winnability_source"] = blended["winnability_source"]
    pack = build_pack(
        primary=related[0], related_queries=related,
        board_angle=seed.get("recommended_board", ""),
        variations_count=4,
    )
    dossier = TrendDossier(
        id=seed["id"], title=seed["title"], category=category,
        heat_level=seed.get("heat_level", "rising"),
        heat_badge=seed.get("heat_badge", "📈 Rising"),
        opportunity_score=int(scored["score"]),
        tier=f"Tier {scored['tier']}",
        aesthetic_vibe=seed.get("aesthetic_vibe", "Modern Aesthetic"),
        outfit_or_scene=seed.get("outfit_or_scene", "High-conversion styling setup"),
        recommended_board=seed.get("recommended_board", "Aesthetic Finds"),
        related_queries=related, matched_products=matched_prods,
    )
    out = dossier.to_dict()
    out["score_breakdown"] = scored["breakdown"]
    out["keyword_pack"] = pack.to_dict()
    out["sources"] = [s.to_dict() for s in signals]
    return out


# ── Custom On-Demand Keyword Trend Deep-Dive (24h disk cache + live clients) ─

def _trend_cache_dir() -> Path:
    d = Path(settings.storage_path) / "trend_radar" / "custom_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_custom_cache(key: str, max_age_hours: int = 24) -> dict[str, Any] | None:
    try:
        file = _trend_cache_dir() / f"{key}.json"
        if not file.exists():
            return None
        payload = json.loads(file.read_text(encoding="utf-8"))
        raw_ts = payload.get("cached_at")
        if raw_ts:
            ts = datetime.fromisoformat(raw_ts)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = datetime.min.replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
        return payload.get("dossier") if age_h <= max_age_hours else None
    except Exception:
        return None


def _write_custom_cache(key: str, dossier: dict[str, Any]) -> None:
    try:
        (_trend_cache_dir() / f"{key}.json").write_text(
            json.dumps({"cached_at": datetime.now(timezone.utc).isoformat(),
                        "dossier": dossier}, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("Custom trend cache write failed: %s", e)


async def analyze_custom_trend_query(query: str, category: str = "fashion", refresh: bool = False) -> dict[str, Any]:
    """
    Run on-demand deep trend analysis for any user-entered keyword.

    Same dossier shape as `_build_trend_dossier` (score_breakdown,
    keyword_pack, sources, "Tier X", int opportunity_score). Results are
    cached per query+category for 24h; cache failures only warn. The
    seasonal heat rule affects display fields only — the score is computed.
    """
    from app.config import settings as _settings

    clean_q = query.strip()
    if not clean_q:
        raise ValueError("Search query cannot be empty")

    # Fingerprint in the key: weight changes must not serve stale scores,
    # and old key formats are ignored rather than migrated.
    key = (
        re.sub(r"[^a-z0-9]+", "_", clean_q.lower()).strip("_")
        + f"__{re.sub(r'[^a-z0-9]+', '_', category.lower()).strip('_')}"
        + f"__{_current_weights_fingerprint()}"
    )
    if not refresh:
        cached = _read_custom_cache(key)
        if cached is not None:
            return cached

    # 1. Live multi-source scan for related angles.
    signals = await _scan_seed_signals(clean_q, category)
    related = sorted(
        {q for s in signals for q in s.queries},
        key=lambda q: (len(q), q),
    )[:8] or [clean_q, f"{clean_q} aesthetic", f"{clean_q} 2026", f"best {clean_q} amazon"]

    # 2. Live Amazon match (fail-soft inside; returns [] when offline), then
    # blended score with real money/winnability inputs (settings weights).
    products = await match_amazon_products_for_trend(clean_q, category=category, item_count=3)
    blended = _blend_signals(signals, products=products, related=related)
    _weights = _current_weights()
    scored = score_trend(
        blended["demand"], blended["money"], blended["winnability"],
        weights=_weights,
    )
    scored["breakdown"]["weights_fingerprint"] = _weights_fingerprint(_weights)
    scored["breakdown"]["demand_source"] = "autocomplete_breadth_proxy"
    scored["breakdown"]["money_source"] = blended["money_source"]
    scored["breakdown"]["winnability_source"] = blended["winnability_source"]

    # 3. Deterministic keyword pack + seasonal display rule (display only).
    title = clean_q.title()
    pack = build_pack(
        primary=related[0], related_queries=related,
        board_angle=f"{title} Ideas",
        variations_count=4,
    )
    q_lower = clean_q.lower()
    is_seasonal = any(k in q_lower for k in ("fall", "autumn", "halloween", "holiday", "christmas", "summer", "spring"))
    heat_level = "breakout" if is_seasonal else "rising"
    # Display-only seasonal hint. Demand here is a 0-100 autocomplete blend —
    # no measured growth percentage exists — so the badge must not invent one.
    heat_badge = "🔥 Seasonal Breakout" if is_seasonal else "📈 Trending"

    dossier = TrendDossier(
        id=re.sub(r"[^a-z0-9]+", "_", clean_q.lower()).strip("_"),
        title=title,
        category=category,
        heat_level=heat_level,
        heat_badge=heat_badge,
        opportunity_score=int(scored["score"]),
        tier=f"Tier {scored['tier']}",
        aesthetic_vibe=f"Trending 2026 {title} Commercial Aesthetic",
        outfit_or_scene=f"Natural unposed lifestyle setting featuring {clean_q}, soft lighting, candid perspective",
        recommended_board=f"{title} Ideas",
        related_queries=related,
        matched_products=products,
        origin="custom_query",
    )

    out = dossier.to_dict()
    out["score_breakdown"] = scored["breakdown"]
    out["keyword_pack"] = pack.to_dict()
    out["sources"] = [s.to_dict() for s in signals]
    _write_custom_cache(key, out)
    return out
