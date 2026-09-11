"""
Official Pinterest Trends Scraper & Intelligence Service.

Uses Playwright headless browser to fetch real-time search momentum from
https://trends.pinterest.com/, including:
- Top Trends, Growing Trends, and Monthly/Seasonal Surges
- 52-Week search trajectory counts (normalized 0-100) for sparkline visualization
- MoM (month-over-month), WoW (week-over-week), and YoY growth metrics
- "20-Day Publishing Window" recommendation (since Pinterest pins take 2-4 weeks to index and peak)
- Intent classification: Viral Blog / Inspo (Nails, Hair, Outfits, DIY) vs Commercial Affiliate Products
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import subprocess
import sys
import urllib.parse
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger("pre.services.pinterest_trends")

# Semaphore to prevent multiple concurrent browser launches
_BROWSER_SEMAPHORE = asyncio.Semaphore(1)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# ── Event-loop guard: Playwright cannot spawn its driver on Windows ──────────
# SelectorEventLoop (which uvicorn installs with reload=True). In-process
# launches then raise bare NotImplementedError and every strategy degrades to
# [] — which is exactly the "empty Popular Pins everywhere" failure mode. When
# the running loop cannot spawn subprocesses, scraping is delegated to
# scripts/scrape_trends_worker.py in its own interpreter (Proactor policy).
_SELECTOR_LOOP_WARNED = False


def _loop_can_spawn_subprocess() -> bool:
    """True when Playwright can launch its driver in this process."""
    if sys.platform != "win32":
        return True
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return True
    proactor = getattr(asyncio, "ProactorEventLoop", None)
    return proactor is None or isinstance(loop, proactor)


def _parse_worker_output(cmd: str, completed: subprocess.CompletedProcess) -> Any | None:
    """Parse worker stdout JSON; None on any failure (fail-soft preserved)."""
    if completed.returncode != 0:
        logger.warning(
            "Trends worker %r exited %s: %s",
            cmd, completed.returncode, (completed.stderr or "")[-500:],
        )
        return None
    try:
        payload = json.loads((completed.stdout or "").strip())
    except Exception as e:
        logger.warning("Trends worker %r returned unparsable stdout: %s", cmd, e)
        return None
    if isinstance(payload, dict) and "error" in payload:
        logger.warning("Trends worker %r reported error: %s", cmd, payload["error"])
        return None
    return payload


async def _delegate_to_worker(cmd: str, args: list[str], timeout_s: int) -> Any | None:
    """Run a scrape_trends_worker command in a helper thread (any loop type).

    subprocess.run is blocking, so it executes in a thread — safe under both
    Selector and Proactor loops. The child sets its own Proactor policy.
    """
    global _SELECTOR_LOOP_WARNED
    if not _SELECTOR_LOOP_WARNED:
        _SELECTOR_LOOP_WARNED = True
        logger.warning(
            "Running loop cannot spawn subprocesses (uvicorn reload installs "
            "SelectorEventLoop on Windows) — delegating Pinterest scraping to "
            "scripts/scrape_trends_worker.py subprocess. Run the server without "
            "--reload for faster in-process scraping."
        )
    try:
        completed = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "scripts.scrape_trends_worker", cmd, *args],
            capture_output=True, text=True, timeout=timeout_s, cwd=str(_PROJECT_ROOT),
        )
    except subprocess.TimeoutExpired:
        logger.warning("Trends worker %r timed out after %ss", cmd, timeout_s)
        return None
    except Exception as e:
        logger.warning("Trends worker %r failed to launch: %s", cmd, e)
        return None
    return _parse_worker_output(cmd, completed)


async def _scrape_via_worker_if_needed(
    worker_cmd: str, worker_args: list[str], timeout_s: int
) -> tuple[bool, Any | None]:
    """Returns (delegated, result). When the loop is fine, (False, None) and
    the caller proceeds in-process."""
    if _loop_can_spawn_subprocess():
        return False, None
    async with _BROWSER_SEMAPHORE:
        return True, await _delegate_to_worker(worker_cmd, worker_args, timeout_s)

# ── Provenance markers ─────────────────────────────────────────────────────
# Every trend dict leaving get_official_pinterest_trends() carries:
#   "provenance": "live" | "curated_fallback",  "is_fallback": bool
# Live items are cached; the curated fallback is NEVER written to disk, so a
# failed scrape cannot poison the 6h cache (and the daily scheduler cannot
# re-poison it either). The cache key version is bumped so pre-fix cache
# files — which may hold curated data labeled as live — are ignored.
_OFFICIAL_CACHE_VERSION = "v2"


def _official_cache_key(preset: str, country: str) -> str:
    return f"official_{preset}_{country}_{_OFFICIAL_CACHE_VERSION}"


def _tag_live(trends: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**t, "provenance": "live", "is_fallback": False} for t in trends]


def _tag_curated(trends: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Copy: never mutate the CURATED_* globals with per-request markers.
    return [{**t, "provenance": "curated_fallback", "is_fallback": True} for t in trends]


def _stable_suffix(*parts: str) -> str:
    """Stable 12-hex id suffix. Never use salt-randomized hash() for ids —
    ids must survive restarts (React keys, cache dedup, imports)."""
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]


_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _shift_month(d: date, months_back: int) -> date:
    idx = d.year * 12 + (d.month - 1) - months_back
    return date(idx // 12, idx % 12 + 1, 1)


def _timeline_labels(end: date) -> list[str]:
    """'Mon YYYY' axis labels for the 52-week window ending at `end`.

    Derived from the real data window — never hardcoded calendar months.
    """
    return [f"{_MONTHS[_shift_month(end, m).month - 1]} {_shift_month(end, m).year}"
            for m in (9, 6, 3, 0)]


def _parse_end_date(value: Any) -> date:
    """Parse a YYYY-MM-DD window end; fall back to today (UTC)."""
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except Exception:
        return datetime.now(timezone.utc).date()


def _deep_dive_cache_key(term: str, country: str) -> str:
    # Versioned so pre-honesty cache payloads (fake charts/keywords/pins)
    # are ignored instead of served.
    return f"deep_dive_{term.lower().replace(' ', '_')}_{country}_v2"


def _cache_dir() -> Path:
    d = Path(settings.storage_path) / "pinterest_trends"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_cache(key: str, max_age_hours: int = 6) -> list[dict[str, Any]] | None:
    try:
        f = _cache_dir() / f"{key}.json"
        if not f.exists():
            return None
        payload = json.loads(f.read_text(encoding="utf-8"))
        raw_ts = payload.get("cached_at")
        if raw_ts:
            ts = datetime.fromisoformat(raw_ts)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
            if age_h <= max_age_hours:
                return payload.get("trends")
        return None
    except Exception as e:
        logger.warning("Failed to read Pinterest trends cache for %s: %s", key, e)
        return None


def _write_cache(key: str, trends: list[dict[str, Any]]) -> None:
    try:
        f = _cache_dir() / f"{key}.json"
        f.write_text(
            json.dumps({
                "cached_at": datetime.now(timezone.utc).isoformat(),
                "count": len(trends),
                "trends": trends,
            }, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("Failed to write Pinterest trends cache for %s: %s", key, e)


def classify_trend_intent(term: str) -> str:
    """
    Classify whether a trend is primarily for Viral Blog / Lookbook Inspo traffic
    or directly matchable to a Physical Commercial Affiliate Product.
    """
    t = term.lower()
    inspo_keywords = [
        "nail", "nails", "hair", "hairstyle", "haircut", "color", "outfit", "inspo",
        "aesthetic", "idea", "ideas", "makeup", "eyes", "tattoo", "tattoos", "wallpaper",
        "caption", "captions", "quote", "quotes", "diy", "decor", "recipe", "recipes",
        "look", "looks", "style", "theme", "design", "designs", "art", "costume",
        "drawing", "challenge", "glam", "vibe", "vibes", "routine"
    ]
    if any(k in t for k in inspo_keywords):
        return "viral_blog"
    return "commercial_product"


def calculate_indexing_window(counts: list[dict[str, Any]], mom_change: float | None) -> dict[str, Any]:
    """
    Pinterest pins take 15-30 days to index, rank, and gain viral traction.
    Calculate when the creator should publish this pin.
    """
    if not counts:
        return {
            "advice": "⏰ Pin NOW — Peaks in ~20–30 Days",
            "urgency": "high",
            "badge": "Early Indexing Window",
            "phase": "rising",
        }

    latest = counts[-1].get("normalizedCount", 0) if counts else 0
    mom = mom_change or 0.0

    if latest >= 80:
        return {
            "advice": "🔥 Active Search Peak — Immediate High Discovery",
            "urgency": "immediate",
            "badge": "Active Peak",
            "phase": "peaking",
        }
    elif mom >= 20.0 or latest >= 30:
        return {
            "advice": "⏰ Pin NOW — Expected Peak in 20–30 Days",
            "urgency": "high",
            "badge": "Prime Early Window",
            "phase": "rising",
        }
    elif mom > 0:
        return {
            "advice": "🌱 Emerging Trend — Pin Early for 30–45 Day Runway",
            "urgency": "medium",
            "badge": "Emerging Signal",
            "phase": "emerging",
        }
    else:
        return {
            "advice": "📌 Evergreen Topic — Consistent Year-Round Search",
            "urgency": "normal",
            "badge": "Evergreen",
            "phase": "steady",
        }


def _clean_growth_pct(val: Any) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace(",", "")
    m = re.search(r"[-+]?\d*\.?\d+", s)
    return float(m.group(0)) if m else 0.0


# ── Rich Fallback Data (Guarantees Instant Uptime) ───────────────────────────

CURATED_PINTEREST_TRENDS: list[dict[str, Any]] = [
    {
        "term": "fall nail colors 2026",
        "category": "beauty",
        "intent": "viral_blog",
        "mom_change": 3000.0,
        "wow_change": 200.0,
        "yoy_change": None,
        "search_count": 100,
        "sparkline": [1, 3, 7, 15, 31, 62, 100],
        "indexing_window": {
            "advice": "⏰ Pin NOW — Expected Peak in 20–30 Days",
            "urgency": "high",
            "badge": "Prime Early Window",
            "phase": "rising",
        },
        "recommended_board": "Autumn Nails & Gel Colors 2026",
        "monetization_angle": "Blog / Lookbook Gallery + Gel Polish Sets",
        "preview_images": [
            "https://images.unsplash.com/photo-1632345031435-8727f6897d53?w=500&q=80",
            "https://images.unsplash.com/photo-1604654894610-df63bc536371?w=500&q=80",
        ],
    },
    {
        "term": "september nails ideas 2026",
        "category": "beauty",
        "intent": "viral_blog",
        "mom_change": 10000.0,
        "wow_change": 200.0,
        "yoy_change": None,
        "search_count": 100,
        "sparkline": [0, 0, 2, 14, 32, 70, 100],
        "indexing_window": {
            "advice": "🔥 Active Search Peak — Immediate High Discovery",
            "urgency": "immediate",
            "badge": "Active Peak",
            "phase": "peaking",
        },
        "recommended_board": "September Nails & Fall Transitions",
        "monetization_angle": "Editorial Blog Post & Nail Art Inspo",
        "preview_images": [
            "https://images.unsplash.com/photo-1604654894610-df63bc536371?w=500&q=80",
        ],
    },
    {
        "term": "halloween nails",
        "category": "seasonal",
        "intent": "viral_blog",
        "mom_change": 200.0,
        "wow_change": 40.0,
        "yoy_change": 150.0,
        "search_count": 16,
        "sparkline": [3, 4, 6, 9, 11, 14, 16],
        "indexing_window": {
            "advice": "⏰ Pin NOW — Expected Peak in 25–30 Days (Pre-October)",
            "urgency": "high",
            "badge": "Prime Early Window",
            "phase": "rising",
        },
        "recommended_board": "Spooky Halloween Nails & Gothic Art",
        "monetization_angle": "Viral Traffic to Halloween Lookbook & Press-On Nails",
        "preview_images": [
            "https://images.unsplash.com/photo-1509198397868-475647b2a1e5?w=500&q=80",
        ],
    },
    {
        "term": "usa football theme outfit",
        "category": "fashion",
        "intent": "viral_blog",
        "mom_change": 5500.0,
        "wow_change": 100.0,
        "yoy_change": None,
        "search_count": 100,
        "sparkline": [1, 1, 2, 13, 50, 80, 100],
        "indexing_window": {
            "advice": "🔥 Active Search Peak — Fall Game Day Surge",
            "urgency": "immediate",
            "badge": "Active Peak",
            "phase": "peaking",
        },
        "recommended_board": "Game Day Outfits & Tailgate Style",
        "monetization_angle": "Outfit Moodboards + Amazon Varsity Jackets / Caps",
        "preview_images": [
            "https://images.unsplash.com/photo-1544441893-675973e31985?w=500&q=80",
        ],
    },
    {
        "term": "fall hair color 2026",
        "category": "beauty",
        "intent": "viral_blog",
        "mom_change": 100.0,
        "wow_change": 60.0,
        "yoy_change": None,
        "search_count": 36,
        "sparkline": [10, 12, 15, 20, 26, 32, 36],
        "indexing_window": {
            "advice": "⏰ Pin NOW — Peaks in ~20–30 Days",
            "urgency": "high",
            "badge": "Prime Early Window",
            "phase": "rising",
        },
        "recommended_board": "Autumn Hair Color & Warm Balayage",
        "monetization_angle": "Hair Care Routine & Color Inspo Blog",
        "preview_images": [
            "https://images.unsplash.com/photo-1522337360788-8b13dee7a37e?w=500&q=80",
        ],
    },
    {
        "term": "retro chic style",
        "category": "fashion",
        "intent": "viral_blog",
        "mom_change": 100.0,
        "wow_change": 100.0,
        "yoy_change": None,
        "search_count": 11,
        "sparkline": [2, 3, 4, 6, 8, 9, 11],
        "indexing_window": {
            "advice": "🌱 Emerging Trend — Early Adoption Advantage",
            "urgency": "medium",
            "badge": "Emerging Signal",
            "phase": "emerging",
        },
        "recommended_board": "Retro Chic & Vintage French Wardrobe",
        "monetization_angle": "Styling Guides + Vintage Accessories",
        "preview_images": [
            "https://images.unsplash.com/photo-1515886657613-9f3515b0c78f?w=500&q=80",
        ],
    },
    {
        "term": "vintage corduroy utility jacket",
        "category": "fashion",
        "intent": "commercial_product",
        "mom_change": 420.0,
        "wow_change": 50.0,
        "yoy_change": 210.0,
        "search_count": 55,
        "sparkline": [15, 18, 22, 29, 38, 45, 55],
        "indexing_window": {
            "advice": "⏰ Pin NOW — Autumn Outerwear Buying Cycle",
            "urgency": "high",
            "badge": "Commercial Surge",
            "phase": "rising",
        },
        "recommended_board": "Autumn Barn Jackets & Layers",
        "monetization_angle": "Amazon Affiliate Jacket & Boot Links",
        "preview_images": [
            "https://images.unsplash.com/photo-1544441893-675973e31985?w=500&q=80",
        ],
    },
    {
        "term": "sunset ambient projection lamp",
        "category": "home",
        "intent": "commercial_product",
        "mom_change": 280.0,
        "wow_change": 30.0,
        "yoy_change": 180.0,
        "search_count": 68,
        "sparkline": [20, 24, 30, 42, 50, 58, 68],
        "indexing_window": {
            "advice": "📌 Steady High Demand — High Amazon Conversion",
            "urgency": "normal",
            "badge": "Amazon High-EPC",
            "phase": "steady",
        },
        "recommended_board": "Cozy Bedroom & Mood Lighting",
        "monetization_angle": "Direct Amazon Ambient Lamp Product",
        "preview_images": [
            "https://images.unsplash.com/photo-1513506003901-1e6a229e2d15?w=500&q=80",
        ],
    },
]

CURATED_GROWING_TRENDS: list[dict[str, Any]] = [
    {
        "term": "minimalist capsule wardrobe 2026",
        "category": "fashion",
        "intent": "viral_blog",
        "mom_change": 450.0,
        "wow_change": 65.0,
        "yoy_change": 180.0,
        "search_count": 82,
        "sparkline": [15, 22, 34, 48, 60, 72, 82],
        "indexing_window": {
            "advice": "⏰ Pin NOW — Steady Autumn Fashion Growth",
            "urgency": "high",
            "badge": "Prime Early Window",
            "phase": "rising",
        },
        "recommended_board": "Capsule Wardrobe & Minimal Outfits",
        "monetization_angle": "Capsule Outfit Moodboard + Affiliate Essentials",
        "preview_images": [
            "https://images.unsplash.com/photo-1490481651871-ab68de25d43d?w=500&q=80",
            "https://images.unsplash.com/photo-1485230895905-ec40ba36b9bc?w=500&q=80",
        ],
    },
    {
        "term": "french tip chrome nails",
        "category": "beauty",
        "intent": "viral_blog",
        "mom_change": 380.0,
        "wow_change": 45.0,
        "yoy_change": 220.0,
        "search_count": 78,
        "sparkline": [18, 25, 36, 46, 58, 68, 78],
        "indexing_window": {
            "advice": "⏰ Pin NOW — High Save-to-Pin Ratio",
            "urgency": "high",
            "badge": "Prime Early Window",
            "phase": "rising",
        },
        "recommended_board": "Glazed & Chrome Nails 2026",
        "monetization_angle": "Viral Nail Art Guide + Chrome Powder Kits",
        "preview_images": [
            "https://images.unsplash.com/photo-1632345031435-8727f6897d53?w=500&q=80",
            "https://images.unsplash.com/photo-1604654894610-df63bc536371?w=500&q=80",
        ],
    },
    {
        "term": "scandi home interior styling",
        "category": "home",
        "intent": "viral_blog",
        "mom_change": 310.0,
        "wow_change": 30.0,
        "yoy_change": 140.0,
        "search_count": 65,
        "sparkline": [12, 18, 28, 38, 48, 56, 65],
        "indexing_window": {
            "advice": "🌱 Emerging Trend — High Evergreen Discovery",
            "urgency": "medium",
            "badge": "Emerging Signal",
            "phase": "emerging",
        },
        "recommended_board": "Nordic Living Room & Japandi Home",
        "monetization_angle": "Home Decor Inspo + Amazon Furniture Accents",
        "preview_images": [
            "https://images.unsplash.com/photo-1513506003901-1e6a229e2d15?w=500&q=80",
        ],
    },
    {
        "term": "espresso brown leather jacket",
        "category": "fashion",
        "intent": "commercial_product",
        "mom_change": 520.0,
        "wow_change": 80.0,
        "yoy_change": 290.0,
        "search_count": 90,
        "sparkline": [10, 16, 28, 44, 62, 78, 90],
        "indexing_window": {
            "advice": "🔥 Active Search Peak — Fall Outerwear Season",
            "urgency": "immediate",
            "badge": "Active Peak",
            "phase": "peaking",
        },
        "recommended_board": "Leather Jackets & Fall Layers",
        "monetization_angle": "Amazon Affiliate Faux Leather Bomber & Trench",
        "preview_images": [
            "https://images.unsplash.com/photo-1544441893-675973e31985?w=500&q=80",
        ],
    },
    {
        "term": "clean girl aesthetic makeup",
        "category": "beauty",
        "intent": "viral_blog",
        "mom_change": 260.0,
        "wow_change": 25.0,
        "yoy_change": 90.0,
        "search_count": 70,
        "sparkline": [22, 28, 36, 45, 52, 60, 70],
        "indexing_window": {
            "advice": "📌 Steady High Demand — High Clickthrough",
            "urgency": "normal",
            "badge": "Evergreen",
            "phase": "steady",
        },
        "recommended_board": "Dewy Makeup & Everyday Glow",
        "monetization_angle": "Beauty Routine Steps + Lip Tint & Tinted Serum Links",
        "preview_images": [
            "https://images.unsplash.com/photo-1522337360788-8b13dee7a37e?w=500&q=80",
        ],
    },
    {
        "term": "coastal grandmother autumn",
        "category": "fashion",
        "intent": "viral_blog",
        "mom_change": 290.0,
        "wow_change": 35.0,
        "yoy_change": 120.0,
        "search_count": 60,
        "sparkline": [14, 20, 28, 38, 46, 54, 60],
        "indexing_window": {
            "advice": "⏰ Pin NOW — Pre-Season Transition",
            "urgency": "high",
            "badge": "Prime Early Window",
            "phase": "rising",
        },
        "recommended_board": "Cozy Coastal Aesthetic & Linen Layers",
        "monetization_angle": "Linen & Cashmere Styling Guides",
        "preview_images": [
            "https://images.unsplash.com/photo-1515886657613-9f3515b0c78f?w=500&q=80",
        ],
    },
]

CURATED_TOP_TRENDS: list[dict[str, Any]] = [
    {
        "term": "autumn aesthetic wallpaper",
        "category": "seasonal",
        "intent": "viral_blog",
        "mom_change": 850.0,
        "wow_change": 120.0,
        "yoy_change": None,
        "search_count": 100,
        "sparkline": [5, 12, 25, 45, 68, 88, 100],
        "indexing_window": {
            "advice": "🔥 Active Search Peak — Maximum Viral Discovery",
            "urgency": "immediate",
            "badge": "Active Peak",
            "phase": "peaking",
        },
        "recommended_board": "Fall Aesthetic Phone Wallpapers & Lock Screens",
        "monetization_angle": "High Save Rate Pin Traffic to Digital Bundles",
        "preview_images": [
            "https://images.unsplash.com/photo-1509198397868-475647b2a1e5?w=500&q=80",
        ],
    },
    {
        "term": "fall outfit ideas 2026",
        "category": "fashion",
        "intent": "viral_blog",
        "mom_change": 920.0,
        "wow_change": 140.0,
        "yoy_change": None,
        "search_count": 100,
        "sparkline": [8, 15, 30, 50, 72, 90, 100],
        "indexing_window": {
            "advice": "🔥 Active Search Peak — Immediate Discovery",
            "urgency": "immediate",
            "badge": "Active Peak",
            "phase": "peaking",
        },
        "recommended_board": "Fall Outfits & Trendy Street Style 2026",
        "monetization_angle": "Lookbook Affiliate Links + Boots & Knitwear",
        "preview_images": [
            "https://images.unsplash.com/photo-1544441893-675973e31985?w=500&q=80",
            "https://images.unsplash.com/photo-1591047139829-d91aecb6caea?w=500&q=80",
        ],
    },
    {
        "term": "cozy living room decor",
        "category": "home",
        "intent": "commercial_product",
        "mom_change": 410.0,
        "wow_change": 40.0,
        "yoy_change": 160.0,
        "search_count": 85,
        "sparkline": [25, 32, 42, 55, 68, 76, 85],
        "indexing_window": {
            "advice": "⏰ Pin NOW — Peak Fall Home Renovation",
            "urgency": "high",
            "badge": "Prime Early Window",
            "phase": "rising",
        },
        "recommended_board": "Warm & Cozy Living Room Decor",
        "monetization_angle": "Amazon Affiliate Throws, Rugs & Warm Lamps",
        "preview_images": [
            "https://images.unsplash.com/photo-1513506003901-1e6a229e2d15?w=500&q=80",
        ],
    },
    {
        "term": "classy almond nails",
        "category": "beauty",
        "intent": "viral_blog",
        "mom_change": 280.0,
        "wow_change": 30.0,
        "yoy_change": 110.0,
        "search_count": 92,
        "sparkline": [35, 45, 55, 68, 76, 84, 92],
        "indexing_window": {
            "advice": "📌 Top Volume Evergreen — High Conversion",
            "urgency": "normal",
            "badge": "Evergreen",
            "phase": "steady",
        },
        "recommended_board": "Classy Nails & Almond Shape Art",
        "monetization_angle": "Press-On Nail Kits & Cuticle Oil Recommendations",
        "preview_images": [
            "https://images.unsplash.com/photo-1632345031435-8727f6897d53?w=500&q=80",
        ],
    },
    {
        "term": "easy weeknight dinner recipes",
        "category": "home",
        "intent": "viral_blog",
        "mom_change": 340.0,
        "wow_change": 50.0,
        "yoy_change": 130.0,
        "search_count": 88,
        "sparkline": [30, 38, 48, 60, 70, 80, 88],
        "indexing_window": {
            "advice": "⏰ Pin NOW — Back to School Meal Prep",
            "urgency": "high",
            "badge": "Prime Early Window",
            "phase": "rising",
        },
        "recommended_board": "30-Minute Dinners & Healthy Recipes",
        "monetization_angle": "Food Blog Ad Traffic & Kitchen Gadget Links",
        "preview_images": [
            "https://images.unsplash.com/photo-1490481651871-ab68de25d43d?w=500&q=80",
        ],
    },
]

CURATED_TRENDS_BY_PRESET: dict[str, list[dict[str, Any]]] = {
    "breakout": CURATED_PINTEREST_TRENDS,
    "growing": CURATED_GROWING_TRENDS,
    "top": CURATED_TOP_TRENDS,
}


# ── Core Playwright Scraping Logic ──────────────────────────────────────────

async def scrape_pinterest_trends_playwright(
    preset: str = "breakout",
    country: str = "US",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """
    Connect to trends.pinterest.com via Playwright, extract official trend terms,
    52-week search trajectory points, growth rates, and preview pins.
    """
    delegated, worker_result = await _scrape_via_worker_if_needed(
        "official_trends", [preset, country, str(limit)], timeout_s=240
    )
    if delegated:
        return worker_result if isinstance(worker_result, list) else []
    preset_map = {
        "breakout": "3",  # Monthly / Seasonal Surges
        "growing": "2",   # Consistent Growing Trends
        "top": "1",       # Top Search Volume Overall
    }
    ranking_map = {
        "breakout": "3",
        "growing": "2",
        "top": "1",
    }
    preset_code = preset_map.get(preset, "3")
    ranking_code = ranking_map.get(preset, "3")

    async with _BROWSER_SEMAPHORE:
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                    ]
                )
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                    locale="en-US",
                )
                await context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
                page = await context.new_page()

                # 1. Navigate to Pinterest Trends to initialize session & cookies
                await page.goto("https://trends.pinterest.com/", wait_until="domcontentloaded", timeout=25000)
                await asyncio.sleep(2.5)

                # 2. Get latest available date
                latest_res = await page.evaluate("async () => { try { const r = await fetch('/latest_available_date/'); return await r.json(); } catch (e) { return {}; } }")
                end_date = latest_res.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")

                # 3. Fetch top trends filtered
                filtered_url = (
                    f"/top_trends_filtered/?lookbackWindow=2&endDate={end_date}"
                    f"&rankingMethod={ranking_code}&country={country}"
                    f"&trendsPreset={preset_code}&numTermsToReturn={limit}"
                )
                trends_res = await page.evaluate(f"""
                    async () => {{
                        try {{
                            const r = await fetch('{filtered_url}');
                            return {{ status: r.status, data: await r.json() }};
                        }} catch (e) {{
                            return {{ error: e.toString() }};
                        }}
                    }}
                """)

                terms_data = trends_res.get("data", {}).get("values", [])
                if not terms_data:
                    logger.warning("No terms returned from Pinterest Trends filtered endpoint")
                    await browser.close()
                    return []

                # Extract terms list
                terms = [item["term"] for item in terms_data if "term" in item][:limit]
                terms_encoded = "%2C".join(urllib.parse.quote_plus(t) for t in terms)

                # 4. Fetch 52-week search trajectory points (/metrics/)
                metrics_url = (
                    f"/metrics/?terms={terms_encoded}&country={country}"
                    f"&end_date={end_date}&days=365&aggregation=2"
                    f"&normalize_against_group=false&predicted_days=0"
                )
                metrics_res = await page.evaluate(f"""
                    async () => {{
                        try {{
                            const r = await fetch('{metrics_url}');
                            return {{ status: r.status, data: await r.json() }};
                        }} catch (e) {{
                            return {{ error: e.toString() }};
                        }}
                    }}
                """)
                metrics_list = metrics_res.get("data", [])
                metrics_by_term = {m.get("term", "").lower(): m for m in metrics_list if isinstance(m, dict)}

                # 5. Fetch preview pin images (/term_images/) via official POST endpoint
                terms_payload = json.dumps({
                    "terms": terms,
                    "country": country,
                    "cacheTtlInSeconds": 86400,
                    "limit": 3,
                    "batchSize": 20,
                    "requestImageSize": "75x75"
                })
                img_res = await page.evaluate(f"""
                    async () => {{
                        try {{
                            const cookies = document.cookie.split('; ');
                            const csrfCookie = cookies.find(c => c.startsWith('csrftoken='));
                            const csrf = csrfCookie ? csrfCookie.split('=')[1] : '';
                            const r = await fetch('/term_images/', {{
                                method: 'POST',
                                headers: {{
                                    'content-type': 'application/json',
                                    'x-csrftoken': csrf
                                }},
                                body: JSON.stringify({terms_payload})
                            }});
                            if (r.status !== 200) return {{ status: r.status, data: {{}} }};
                            return {{ status: 200, data: await r.json() }};
                        }} catch (e) {{
                            return {{ error: e.toString(), data: {{}} }};
                        }}
                    }}
                """)
                images_by_term = img_res.get("data", {}) if isinstance(img_res.get("data"), dict) else {}

                await browser.close()

                # Assemble structured trend items
                results = []
                for item in terms_data:
                    term = item.get("term")
                    if not term:
                        continue
                    term_lower = term.lower()
                    m_data = metrics_by_term.get(term_lower, {})
                    growth = m_data.get("growth_rates", {})
                    counts = m_data.get("counts", [])

                    # 7-point sparkline from measured counts only. No counts →
                    # empty curve (never a synthesized ramp): the UI renders
                    # its "No curve data" state instead of a fake chart.
                    if counts:
                        sparkline = [c.get("normalizedCount", 0) for c in counts[-7:] if isinstance(c, dict)]
                    else:
                        sparkline = []

                    mom_val = _clean_growth_pct(item.get("mom_change", {}).get("value") or growth.get("mom_change"))
                    wow_val = _clean_growth_pct(item.get("wow_change", {}).get("value") or growth.get("wow_change"))
                    yoy_val = _clean_growth_pct(item.get("yoy_change", {}).get("value") or growth.get("yoy_change"))

                    intent = classify_trend_intent(term)
                    indexing_win = calculate_indexing_window(counts, mom_val)

                    # Extract real Pinterest images
                    raw_term_imgs = images_by_term.get(term) or images_by_term.get(term_lower, [])
                    preview_imgs: list[str] = []
                    if isinstance(raw_term_imgs, list):
                        for u in raw_term_imgs:
                            if isinstance(u, str) and "i.pinimg.com" in u:
                                high_res = u.replace("/75x75/", "/736x/").replace("/236x/", "/736x/").replace("/474x/", "/736x/")
                                preview_imgs.append(high_res)
                            elif isinstance(u, dict):
                                img_dict_url = u.get("images", {}).get("orig", {}).get("url") or u.get("image_url")
                                if img_dict_url:
                                    preview_imgs.append(img_dict_url)
                    if not preview_imgs:
                        preview_imgs = [
                            f"https://www.pinterest.com/search/pins/?q={urllib.parse.quote_plus(term)}"
                        ]

                    category = "beauty" if "nail" in term_lower or "hair" in term_lower or "makeup" in term_lower else (
                        "fashion" if "outfit" in term_lower or "style" in term_lower or "jacket" in term_lower else (
                            "home" if "decor" in term_lower or "lamp" in term_lower or "room" in term_lower else "seasonal"
                        )
                    )

                    results.append({
                        "term": term,
                        "category": category,
                        "intent": intent,
                        "mom_change": mom_val,
                        "wow_change": wow_val,
                        "yoy_change": yoy_val if yoy_val != 0 else None,
                        "search_count": item.get("normalizedCount", sparkline[-1] if sparkline else None),
                        "sparkline": sparkline,
                        "timeline_dates": _timeline_labels(_parse_end_date(end_date)),
                        "indexing_window": indexing_win,
                        "recommended_board": f"{term.title()} Inspo & Ideas",
                        "monetization_angle": (
                            "Viral Blog / Lookbook Gallery Traffic" if intent == "viral_blog"
                            else "Amazon Affiliate Product Matching"
                        ),
                        "preview_images": preview_imgs[:3],
                    })

                return results

        except Exception as e:
            logger.error("Playwright scraping of Pinterest Trends failed: %s", e)
            return []


# ── Custom Single-Keyword Search on Pinterest Trends ─────────────────────────

def _build_custom_metric_item(
    clean_q: str,
    target: dict[str, Any],
    img_data: Any,
    window_end: date | None = None,
) -> dict[str, Any] | None:
    """
    Build one custom-term metric item from raw /metrics + /term_images payloads.

    Returns None when Pinterest returned no trajectory counts — the caller
    surfaces "no data" instead of charting a fabricated sparkline.
    Pure function (no I/O) so the no-fabrication rule stays unit-testable.
    """
    growth = target.get("growth_rates", {}) if isinstance(target, dict) else {}
    counts = target.get("counts", []) if isinstance(target, dict) else []

    sparkline = [c.get("normalizedCount", 0) for c in counts[-8:] if isinstance(c, dict)]
    if not sparkline:
        logger.warning(
            "Custom Pinterest metrics for %r returned no trajectory counts — "
            "refusing to fabricate a sparkline",
            clean_q,
        )
        return None

    mom_val = _clean_growth_pct(growth.get("mom_change"))
    wow_val = _clean_growth_pct(growth.get("wow_change"))
    yoy_val = _clean_growth_pct(growth.get("yoy_change"))

    raw_pins = img_data.get(clean_q) or img_data.get(clean_q.lower()) or (list(img_data.values())[0] if img_data else [])
    preview_imgs = []
    if isinstance(raw_pins, list):
        for u in raw_pins:
            if isinstance(u, str) and "i.pinimg.com" in u:
                preview_imgs.append(u.replace("/75x75/", "/736x/").replace("/236x/", "/736x/"))
            elif isinstance(u, dict):
                img_u = u.get("images", {}).get("orig", {}).get("url") or u.get("image_url")
                if img_u:
                    preview_imgs.append(img_u)
    if not preview_imgs:
        preview_imgs = [f"https://www.pinterest.com/search/pins/?q={urllib.parse.quote_plus(clean_q)}"]

    intent = classify_trend_intent(clean_q)
    indexing_win = calculate_indexing_window(counts, mom_val)

    return {
        "term": clean_q,
        "category": "beauty" if "nail" in clean_q.lower() or "hair" in clean_q.lower() else "fashion",
        "intent": intent,
        "mom_change": mom_val,
        "wow_change": wow_val,
        "yoy_change": yoy_val if yoy_val != 0 else None,
        "search_count": sparkline[-1],
        "sparkline": sparkline,
        "timeline_dates": _timeline_labels(window_end or datetime.now(timezone.utc).date()),
        "indexing_window": indexing_win,
        "recommended_board": f"{clean_q.title()} Inspo & Ideas",
        "monetization_angle": (
            "Viral Blog / Lookbook Gallery Traffic" if intent == "viral_blog"
            else "Amazon Affiliate Product Matching"
        ),
        "preview_images": preview_imgs[:3],
    }


async def scrape_custom_pinterest_trend_metrics(
    query: str,
    country: str = "US",
) -> dict[str, Any] | None:
    """
    Query trends.pinterest.com specifically for any single custom keyword,
    fetching its exact 52-week search trajectory, growth rates, and preview pins.
    """
    clean_q = query.strip()
    if not clean_q:
        return None

    delegated, worker_result = await _scrape_via_worker_if_needed(
        "custom_metrics", [clean_q, country], timeout_s=180
    )
    if delegated:
        return worker_result if isinstance(worker_result, dict) else None

    async with _BROWSER_SEMAPHORE:
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
                )
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                    locale="en-US",
                )
                await context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
                page = await context.new_page()

                await page.goto("https://trends.pinterest.com/", wait_until="domcontentloaded", timeout=25000)
                await asyncio.sleep(2)

                date_res = await page.evaluate("async () => { try { const r = await fetch('/latest_available_date/'); return await r.json(); } catch(e) { return {}; } }")
                end_date = date_res.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")

                encoded_term = urllib.parse.quote_plus(clean_q)
                metrics_url = (
                    f"/metrics/?terms={encoded_term}&country={country}"
                    f"&end_date={end_date}&days=365&aggregation=2"
                    f"&normalize_against_group=false&predicted_days=0"
                )
                res = await page.evaluate(f"""
                    async () => {{
                        try {{
                            const r = await fetch('{metrics_url}');
                            return {{ status: r.status, data: await r.json() }};
                        }} catch (e) {{
                            return {{ error: e.toString() }};
                        }}
                    }}
                """)

                # Also get images via official POST /term_images/
                custom_term_payload = json.dumps({
                    "terms": [clean_q],
                    "country": country,
                    "cacheTtlInSeconds": 86400,
                    "limit": 5,
                    "batchSize": 20,
                    "requestImageSize": "75x75"
                })
                img_res = await page.evaluate(f"""
                    async () => {{
                        try {{
                            const cookies = document.cookie.split('; ');
                            const csrfCookie = cookies.find(c => c.startsWith('csrftoken='));
                            const csrf = csrfCookie ? csrfCookie.split('=')[1] : '';
                            const r = await fetch('/term_images/', {{
                                method: 'POST',
                                headers: {{
                                    'content-type': 'application/json',
                                    'x-csrftoken': csrf
                                }},
                                body: JSON.stringify({custom_term_payload})
                            }});
                            if (r.status !== 200) return {{ status: r.status, data: {{}} }};
                            return {{ status: 200, data: await r.json() }};
                        }} catch (e) {{
                            return {{ error: e.toString(), data: {{}} }};
                        }}
                    }}
                """)

                await browser.close()

                items = res.get("data", [])
                if not items or not isinstance(items, list):
                    return None

                target = items[0]

                img_data = img_res.get("data", {}) if isinstance(img_res.get("data"), dict) else {}

                return _build_custom_metric_item(
                    clean_q, target, img_data, window_end=_parse_end_date(end_date)
                )

        except Exception as e:
            logger.warning("Custom Pinterest metric search failed for %r: %s", clean_q, e)
            return None


# ── Popular Pins & Related Searches Intelligence ──────────────────────────

def get_commonly_searched_queries(term: str, category: str = "fashion") -> list[str]:
    """
    Generate related-search suggestions for a term (curated lists for known
    families, template variations otherwise).

    These are GENERATED suggestions for discovery/seeding — NOT measured
    Pinterest data. Callers must present them as such (see
    ``related_searches_provenance`` on the deep-dive payload).
    """
    t = term.lower()
    if "blazer" in t:
        return [
            "oversized blazer outfit",
            "black blazer outfit",
            "black blazer outfits for women",
            "blazer outfits casual",
            "blazer and jeans outfit",
            "brown blazer outfits for women",
            "cropped blazer outfit",
            "plaid blazer outfit",
            "tan blazer outfits women",
            "tan blazer outfit",
            "sleeveless blazer outfit",
            "blazer and jeans",
        ]
    if "nail" in t:
        return [
            "september nails ideas 2026",
            "fall nails 2026 trends",
            "transition nails summer to fall",
            "almost fall nails",
            "simple september nails",
            "nail inspoo",
            "fall chrome nails",
            "burgundy nails fall",
            "brown heart nails aesthetic",
            "autumn french tip nails",
            "gold leaf fall nails",
            "mocha nails aesthetic",
        ]
    if "halloween" in t:
        return [
            "halloween nail art 2026",
            "spooky ghost nails",
            "classy halloween nails",
            "black french tip halloween nails",
            "subtle halloween nails",
            "spiderweb nail designs",
            "pumpkin nail art",
            "witchy nails aesthetic",
            "halloween press on nails",
            "gothic fall nails",
        ]
    if "football" in t or "game day" in t:
        return [
            "game day outfits college",
            "football tailgate outfit",
            "vintage varsity jacket look",
            "oversized football jersey aesthetic",
            "cheerleader skirt game day",
            "casual sporty fall outfits",
            "red white blue outfit inspo",
        ]
    if "hair" in t:
        return [
            "fall hair colors 2026 warm tones",
            "espresso brunette hair",
            "cinnamon spice hair color",
            "autumn balayage highlights",
            "bob haircuts fall 2026",
            "curtain bangs long hair",
            "glossy dark chocolate hair",
        ]

    # Dynamic fallback generator for custom terms
    clean = re.sub(r"[^a-zA-Z0-9\s]", "", term).strip().lower()
    return [
        f"{clean} ideas",
        f"{clean} outfit",
        f"oversized {clean}",
        f"{clean} for women",
        f"casual {clean}",
        f"{clean} aesthetic 2026",
        f"simple {clean}",
        f"{clean} style formula",
        f"cute {clean}",
        f"how to style {clean}",
    ]


# Editorial overlay hooks for real scraped pins (clearly presentational copy,
# applied only to genuine Pinterest images — never to stand-ins).
_PIN_HOOKS = [
    "VIRAL LOOKBOOK",
    "STREETWEAR INSPO",
    "AESTHETIC FORMULA",
    "TRENDING NOW",
    "MUST-TRY STYLE",
    "PINTEREST SURGE",
    "CURATED MOODBOARD",
    "TOP PINNED",
    "MINIMALIST EDIT",
    "SEASONAL FAVORITE",
    "CHIC ESSENTIAL",
    "CREATIVE INSPIRATION",
]


def _clean_popular_pins(
    raw_pins: list[dict[str, Any]],
    *,
    clean_term: str,
    encoded_term: str,
    count: int,
) -> list[dict[str, Any]]:
    """
    Dedup + label raw scraped pins. Returns ONLY real scraped images
    (0..count) — never pads the gallery with stock photos. Fewer (or zero)
    pins is honest; the UI renders an empty state instead of fake pins.
    Pure function (no I/O) so the no-padding rule stays unit-testable.
    """
    title_templates = [
        f"{clean_term.title()} — Aesthetic Inspo & Style Guide",
        f"How to Style {clean_term.title()} Like an Influencer",
        f"Viral {clean_term.title()} Formula Trending on Pinterest",
        f"Minimalist {clean_term.title()} Capsule Inspiration",
        f"Chic & Effortless {clean_term.title()} Lookbook",
        f"{clean_term.title()} Street Style & Daily Fits",
        f"Ultimate {clean_term.title()} Aesthetic Moodboard",
        f"10 Best {clean_term.title()} Ideas to Save Right Now",
        f"Effortless {clean_term.title()} Visual Blueprint",
        f"Top Saved {clean_term.title()} Pins This Season",
    ]

    seen_images: set[str] = set()
    cleaned_pins: list[dict[str, Any]] = []

    for i, p in enumerate(raw_pins):
        img = p.get("image_url")
        if not img:
            continue
        # Vector/UI chrome is never a pin photo (e.g. skin-tone sprites served
        # from i.pinimg.com that slip through the interceptor).
        if img.split("?")[0].lower().endswith(".svg"):
            continue
        base_name = img.split("/")[-1]
        if base_name in seen_images:
            continue
        seen_images.add(base_name)

        title = (p.get("title") or "").strip()
        if not title or title.lower() in ["pin", "image", "pinterest", ""]:
            title = title_templates[i % len(title_templates)]

        hook = _PIN_HOOKS[i % len(_PIN_HOOKS)]
        _src = p.pop("_source", "trends_term_images")
        source_label = (
            "Pinterest Trends (Official)"
            if _src == "trends_term_images"
            else "Pinterest Live Search"
        )

        cleaned_pins.append({
            "pin_id": p.get("pin_id") or f"pin_{i}_{_stable_suffix(clean_term)}",
            "title": title,
            "visual_hook": hook,
            "overlay_text": hook,
            "image_url": img,
            "pin_url": p.get("pin_url") or f"https://www.pinterest.com/search/pins/?q={encoded_term}",
            "source": source_label,
        })
        if len(cleaned_pins) >= count:
            break

    return cleaned_pins


_CHROME_ARGS = ["--disable-blink-features=AutomationControlled", "--no-sandbox"]
_PINS_VIEWPORT = {"width": 1280, "height": 900}


def _extract_term_image_urls(data: Any) -> list[tuple[str, str]]:
    """Normalize /term_images/ responses to [(term, image_url)].

    Accepts both observed payload shapes: bare URL strings and pin objects
    ({"images": {"orig": {"url": ...}}} or {"image_url": ...}). Descends into
    a wrapping dict if Pinterest nests the map.
    """
    pairs: list[tuple[str, str]] = []
    if not isinstance(data, dict):
        return pairs

    def _walk(mapping: dict[str, Any]) -> None:
        for term_key, value in mapping.items():
            if isinstance(value, list):
                for item in value:
                    u = None
                    if isinstance(item, str):
                        u = item
                    elif isinstance(item, dict):
                        imgs = item.get("images") or {}
                        orig = imgs.get("orig") or {}
                        u = orig.get("url") or item.get("image_url")
                    if isinstance(u, str) and "i.pinimg.com" in u:
                        pairs.append((str(term_key), u))
            elif isinstance(value, dict):
                _walk(value)  # one nesting level, e.g. {"data": {term: [...]}}

    _walk(data)
    return pairs


def _profile_dir_if_authed(profile_id: str) -> Path | None:
    """Resolve a profile dir only when it plausibly holds a live session.

    Launching a persistent context on a missing dir makes Chromium mint a
    fresh logged-out profile — worse than skipping, because it burns a
    browser launch just to hit the login wall.
    """
    from app.services.pinterest_profiles import get_profile_dir

    profile_dir = get_profile_dir(profile_id)
    if not profile_dir.exists():
        return None
    try:
        from app.services.pinterest_profiles import _check_profile_dir_auth
        if not _check_profile_dir_auth(profile_dir):
            logger.info("profile %r has no session data — skipping", profile_id)
            return None
    except ImportError:
        pass  # older pinterest_profiles without the helper: existence is enough
    return profile_dir


async def scrape_popular_pins_for_term(
    term: str,
    count: int = 12,
    related_terms: list[str] | None = None,
    country: str = "US",
) -> list[dict[str, Any]]:
    """
    Extract authentic popular viral pins for any Pinterest trend keyword.

    Strategy 1: trends.pinterest.com /term_images/ (official Pinterest Trends POST API)
                leveraging saved business profile sessions (profile_2 -> default)
                or unauthenticated browser session.

    Strategy 2: pinterest.com/search BaseSearchResource network interception for
                real Pin IDs, titles, descriptions, and high-res pins.

    Reliability contract (why the gallery was empty before):
    - Both strategies run inside the logged-in persistent Pinterest profiles
      (same sessions the publisher uses). A cold logged-out browser hits the
      Pinterest login wall: BaseSearchResource never fires and the DOM renders
      no pin images, so the scrape silently returned zero pins.
    - Profile directories that don't exist (or hold no session) are skipped
      instead of letting Chromium mint a fresh logged-out profile.
    - Strategy 1 waits for the csrftoken cookie before POSTing — the old fixed
      1s sleep often raced the cookie, earning a 403 and an empty body.
    - /term_images/ entries are accepted as bare URL strings OR pin objects.

    Event-loop note: on a SelectorEventLoop (uvicorn --reload on Windows) this
    function delegates to the worker subprocess before reaching the strategies
    below (see _scrape_via_worker_if_needed) — same helpers, same contract.

    Returns only genuinely scraped pins (possibly zero) — never padded with
    stock photos; the UI renders an honest empty state instead.
    """
    clean_term = term.strip()
    encoded_term = urllib.parse.quote_plus(clean_term)

    delegated, worker_result = await _scrape_via_worker_if_needed(
        "popular_pins",
        [clean_term, str(count), country, json.dumps(related_terms or [])],
        timeout_s=300,
    )
    if delegated:
        return worker_result if isinstance(worker_result, list) else []

    raw_pins: list[dict[str, Any]] = []

    # Gather search terms: primary term + top related keywords for richer pin discovery
    query_terms = [clean_term]
    if related_terms:
        for rt in related_terms:
            rt_c = rt.strip()
            if rt_c and rt_c.lower() != clean_term.lower() and rt_c not in query_terms:
                query_terms.append(rt_c)
            if len(query_terms) >= 5:
                break

    # ── Strategy 1: trends.pinterest.com /term_images/ (Official Trends API) ──
    # Priority: profile_2 (Business account) -> default -> fresh browser
    try:
        from app.services.browser_utils import clean_stale_locks

        async def _harvest_term_images(page, payload: dict[str, Any]) -> None:
            # The csrftoken cookie is set during the initial trends page load; wait
            # for it before POSTing or /term_images/ answers 403 with an empty body.
            try:
                await page.wait_for_function(
                    "document.cookie.includes('csrftoken=')", timeout=8000
                )
            except Exception:
                pass
            img_res = await page.evaluate(
                """
                async (payload) => {
                    try {
                        const cookies = document.cookie.split('; ');
                        const csrfCookie = cookies.find(c => c.startsWith('csrftoken='));
                        const csrf = csrfCookie ? csrfCookie.split('=')[1] : '';
                        const r = await fetch('/term_images/', {
                            method: 'POST',
                            headers: { 'content-type': 'application/json', 'x-csrftoken': csrf },
                            body: JSON.stringify(payload)
                        });
                        if (r.status !== 200) return { status: r.status, data: {} };
                        return { status: 200, data: await r.json() };
                    } catch (e) {
                        return { error: e.toString(), data: {} };
                    }
                }
                """,
                payload,
            )
            img_data = img_res.get("data", {}) if isinstance(img_res.get("data"), dict) else {}
            found = _extract_term_image_urls(img_data)
            logger.info(
                "/term_images/ status=%s terms=%s pins=%d for %r",
                img_res.get("status", 0), list(img_data.keys()), len(found), clean_term,
            )
            for term_key, img_url in found:
                high_res = (
                    img_url.replace("/75x75/", "/736x/")
                    .replace("/236x/", "/736x/")
                    .replace("/474x/", "/736x/")
                )
                raw_pins.append({
                    "pin_id": f"trend_{_stable_suffix(high_res)}",
                    "title": f"{term_key.title()} — Trending Inspo",
                    "description": "",
                    "image_url": high_res,
                    "pin_url": f"https://www.pinterest.com/search/pins/?q={urllib.parse.quote_plus(term_key)}",
                    "_source": "trends_term_images",
                })

        payload = {
            "terms": query_terms,
            "country": country,
            "cacheTtlInSeconds": 86400,
            "limit": 5,
            "batchSize": 20,
            "requestImageSize": "75x75",
        }

        for _pid in ("profile_2", "default"):
            if raw_pins:
                break
            try:
                profile_dir = _profile_dir_if_authed(_pid)
                if profile_dir is None:
                    continue
                async with _BROWSER_SEMAPHORE:
                    from playwright.async_api import async_playwright
                    async with async_playwright() as p:
                        clean_stale_locks(profile_dir)
                        context = await p.chromium.launch_persistent_context(
                            user_data_dir=str(profile_dir),
                            headless=True,
                            viewport=_PINS_VIEWPORT,
                            args=_CHROME_ARGS,
                        )
                        try:
                            page = context.pages[0] if context.pages else await context.new_page()
                            await page.goto(
                                "https://trends.pinterest.com/",
                                wait_until="domcontentloaded",
                                timeout=20000,
                            )
                            await _harvest_term_images(page, payload)
                        finally:
                            await context.close()
            except Exception as _profile_err:
                logger.debug(
                    "trends /term_images/ profile=%r failed (will try next): %s", _pid, _profile_err
                )

        # Unauthenticated last resort for /term_images/ (trends site is partly public)
        if not raw_pins:
            try:
                async with _BROWSER_SEMAPHORE:
                    from playwright.async_api import async_playwright
                    async with async_playwright() as p:
                        browser = await p.chromium.launch(headless=True, args=_CHROME_ARGS)
                        try:
                            page = await browser.new_page()
                            await page.goto(
                                "https://trends.pinterest.com/",
                                wait_until="domcontentloaded",
                                timeout=20000,
                            )
                            await _harvest_term_images(page, payload)
                        finally:
                            await browser.close()
            except Exception as _unauth_err:
                logger.debug("trends /term_images/ unauth attempt failed: %s", _unauth_err)

        if raw_pins:
            logger.info(
                "trends.pinterest.com /term_images/ returned %d pins for %r",
                len(raw_pins), clean_term,
            )

    except Exception as e:
        logger.warning(
            "trends.pinterest.com /term_images/ scrape failed for %r: %s", clean_term, e
        )

    # ── Strategy 2: pinterest.com/search (BaseSearchResource interceptor) ─────
    # Run when Strategy 1 under-delivered; also enriches with real Pin IDs and
    # direct links. MUST run logged-in: logged-out search is a login wall.
    if len(raw_pins) < count:
        try:
            from app.services.browser_utils import clean_stale_locks

            async def _search_session(profile_id: str | None) -> list[dict[str, Any]]:
                pins: list[dict[str, Any]] = []
                async with _BROWSER_SEMAPHORE:
                    from playwright.async_api import async_playwright
                    async with async_playwright() as p:
                        context = None
                        browser = None
                        if profile_id:
                            profile_dir = _profile_dir_if_authed(profile_id)
                            if profile_dir is None:
                                return pins
                            clean_stale_locks(profile_dir)
                            context = await p.chromium.launch_persistent_context(
                                user_data_dir=str(profile_dir),
                                headless=True,
                                viewport=_PINS_VIEWPORT,
                                args=_CHROME_ARGS,
                            )
                            page = context.pages[0] if context.pages else await context.new_page()
                        else:
                            browser = await p.chromium.launch(headless=True, args=_CHROME_ARGS)
                            context = await browser.new_context(
                                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                                locale="en-US",
                            )
                            page = await context.new_page()

                        async def on_resp(response):
                            if "BaseSearchResource" in response.url and response.status == 200:
                                try:
                                    data = json.loads(await response.text())
                                    items = (
                                        data.get("resource_response", {})
                                        .get("data", {})
                                        .get("results", [])
                                    )
                                    for it in items:
                                        pid = it.get("id")
                                        imgs = it.get("images") or {}
                                        orig = (
                                            imgs.get("orig")
                                            or imgs.get("736x")
                                            or imgs.get("474x")
                                            or {}
                                        ).get("url")
                                        if orig and "i.pinimg.com" in orig:
                                            pins.append({
                                                "pin_id": str(pid),
                                                "title": it.get("title") or it.get("grid_title") or "",
                                                "description": it.get("description") or "",
                                                "image_url": orig,
                                                "pin_url": (
                                                    f"https://www.pinterest.com/pin/{pid}/"
                                                    if pid
                                                    else f"https://www.pinterest.com/search/pins/?q={encoded_term}"
                                                ),
                                                "_source": "search_intercept",
                                            })
                                except Exception:
                                    pass

                        try:
                            page.on("response", on_resp)
                            search_url = f"https://www.pinterest.com/search/pins/?q={encoded_term}"
                            await page.goto(search_url, wait_until="domcontentloaded", timeout=25000)

                            # Dismiss a possible signup/login modal so the grid can render
                            try:
                                await page.keyboard.press("Escape")
                            except Exception:
                                pass

                            # Wait for the first real search-results response
                            # instead of the old fixed 8x0.5s sleep loop.
                            try:
                                await page.wait_for_response(
                                    lambda r: "BaseSearchResource" in r.url and r.status == 200,
                                    timeout=15000,
                                )
                            except Exception:
                                pass

                            # Scroll to paginate more results into the interceptor
                            for _ in range(3):
                                if len(pins) >= count:
                                    break
                                await page.mouse.wheel(0, 2200)
                                await asyncio.sleep(1.2)

                            if not pins:
                                # DOM fallback: pin images already rendered in the grid
                                dom_imgs = await page.evaluate("""() => {
                                    const found = [];
                                    const imgs = Array.from(document.querySelectorAll('img[src*="i.pinimg.com"]'));
                                    for (const img of imgs) {
                                        if (img.src && !img.src.includes('75x75') && !img.src.includes('data:image')) {
                                            const highRes = img.src.replace('/236x/', '/736x/').replace('/474x/', '/736x/');
                                            found.push({ image_url: highRes, alt: img.alt || '' });
                                        }
                                    }
                                    return found;
                                }""")
                                for i, di in enumerate(dom_imgs):
                                    pins.append({
                                        "pin_id": f"dom_{i}_{_stable_suffix(clean_term)}",
                                        "title": di.get("alt") or "",
                                        "description": "",
                                        "image_url": di["image_url"],
                                        "pin_url": f"https://www.pinterest.com/search/pins/?q={encoded_term}",
                                        "_source": "search_dom",
                                    })
                        finally:
                            try:
                                if context is not None:
                                    await context.close()
                            except Exception:
                                pass
                            try:
                                if browser is not None:
                                    await browser.close()
                            except Exception:
                                pass
                return pins

            for _pid in ("profile_2", "default", None):
                if len(raw_pins) >= count:
                    break
                try:
                    intercepted_pins = await _search_session(_pid)
                except Exception as _search_err:
                    logger.debug(
                        "pinterest search scrape profile=%r failed for %r: %s",
                        _pid, clean_term, _search_err,
                    )
                    continue
                if intercepted_pins:
                    # Cross-enrich: attach real Pin IDs/titles to Strategy 1 images
                    inter_by_basename = {
                        ip["image_url"].split("/")[-1]: ip for ip in intercepted_pins
                    }
                    for rp in raw_pins:
                        base = rp["image_url"].split("/")[-1]
                        if base in inter_by_basename:
                            match = inter_by_basename[base]
                            if match.get("title"):
                                rp["title"] = match["title"]
                            if match.get("pin_id") and not match["pin_id"].startswith("trend_"):
                                rp["pin_id"] = match["pin_id"]
                                rp["pin_url"] = match["pin_url"]
                    raw_pins.extend(intercepted_pins)
                    logger.info(
                        "pinterest.com/search (profile=%r) returned %d pins for %r",
                        _pid or "unauth", len(intercepted_pins), clean_term,
                    )
                    break
        except Exception as e:
            logger.warning("Pinterest search scrape failed for %r: %s", clean_term, e)

    # ── Assemble final cleaned pin list: real scraped images only ─────────────
    # No stock-photo padding — fewer (or zero) pins is honest. The UI shows an
    # empty state instead of fake pins.
    return _clean_popular_pins(
        raw_pins, clean_term=clean_term, encoded_term=encoded_term, count=count
    )


async def get_trend_deep_dive(term: str, country: str = "US", force_refresh: bool = False) -> dict[str, Any]:
    """
    Consolidates the complete Trend Deep-Dive details for the interactive drawer:
    - 52-week search trajectory curve + window-derived date labels (when measured)
    - MoM growth rate (when measured; None + metric_provenance "unavailable" otherwise)
    - Editorial aesthetic description
    - Related-search suggestions (GENERATED, not Pinterest measurements)
    - Popular Pins gallery: real scraped Pinterest images only (possibly empty)
    - 20-day indexing recommendation (only when measured metrics exist)
    """
    clean_term = term.strip()
    cache_key = _deep_dive_cache_key(clean_term, country)
    if not force_refresh:
        cached = _read_cache(cache_key, max_age_hours=12)
        if cached and isinstance(cached, list) and len(cached) > 0:
            item = cached[0]
            # Ensure cache does not contain stale poisoned fallback data (repeated identical images)
            pins = item.get("popular_pins", [])
            has_bad_fallback = False
            if pins:
                img_urls = [p.get("image_url", "") for p in pins]
                # Any Unsplash mock fallback images invalidate cache
                if any("unsplash.com" in u for u in img_urls):
                    has_bad_fallback = True
                    logger.info("Invalidating deep dive cache for %r: contains Unsplash fallback images", cache_key)
                # Old known-bad image IDs
                elif any("1500000000000" in u for u in img_urls):
                    has_bad_fallback = True
                elif any("519014816548" in u for u in img_urls):
                    has_bad_fallback = True
                # Old static catalog (source label)
                elif any(p.get("source") == "Pinterest Popular Pins" for p in pins):
                    has_bad_fallback = True
                # Pure Unsplash fallback gallery (no real Pinterest images scraped)
                elif all(p.get("source") == "Pinterest Trends Gallery" for p in pins):
                    has_bad_fallback = True
                    logger.info("Invalidating deep dive cache for %r: all pins are Unsplash fallback", cache_key)
                # Too many duplicate images
                elif len(set(img_urls)) <= 2 and len(img_urls) > 2:
                    has_bad_fallback = True
                # Majority duplicates (pool cycling artefact)
                elif len(set(img_urls)) < len(img_urls) // 2 and len(img_urls) >= 6:
                    has_bad_fallback = True
                    logger.info("Invalidating deep dive cache for %r: too many duplicate fallback images", cache_key)

            if not has_bad_fallback:
                if "popular_pins" in item:
                    for p in item["popular_pins"]:
                        if "visual_hook" not in p and "overlay_text" in p:
                            p["visual_hook"] = p["overlay_text"]
                        elif "overlay_text" not in p and "visual_hook" in p:
                            p["overlay_text"] = p["visual_hook"]
                return item

    # Check if metric_info is already available from cached official trends
    clean_term_lower = clean_term.lower()
    metric_info = None
    if not force_refresh:
        for p in ["breakout", "growing", "top", "monthly", "seasonal"]:
            cached_trends = _read_cache(_official_cache_key(p, country))
            if cached_trends and isinstance(cached_trends, list):
                for tr in cached_trends:
                    if tr.get("term", "").lower() == clean_term_lower:
                        metric_info = tr
                        break
            if metric_info:
                break

    # If not found in cached trends, attempt custom scrape with a reasonable timeout
    if not metric_info:
        metric_info = await scrape_custom_pinterest_trend_metrics(clean_term, country=country)
    has_metric = metric_info is not None
    metric_provenance = "live" if has_metric else "unavailable"
    category = (metric_info.get("category", "fashion") if has_metric else "fashion")

    # Related-search suggestions (generated, not measured — see provenance flag).
    related_searches = get_commonly_searched_queries(clean_term, category=category)

    # Popular pins gallery (query official /term_images/ with term + related terms + search intercept)
    popular_pins = await scrape_popular_pins_for_term(
        clean_term,
        count=12,
        related_terms=related_searches[:4],
        country=country,
    )

    # Narrative description
    t = clean_term.lower()
    if "blazer" in t:
        description = (
            "Blazers are breaking free from the boardroom and stepping into weekend wardrobes with "
            "oversized cuts and cropped styles leading the way. Think soft fabrics brushing your skin "
            "paired with worn-in jeans for that perfectly imperfect vibe. Brands and creators, time to champion effortless cool and mix-and-match magic."
        )
    elif "nail" in t:
        description = (
            "Early autumn nail aesthetics are surging as pinners transition from summer pastels to deep mocha, "
            "warm amber, and metallic bronze chrome. Short squared ovals and subtle micro-french tips with gold foil "
            "are driving the highest save-to-click ratios."
        )
    elif "halloween" in t:
        description = (
            "Halloween searches begin peaking 45 days early on Pinterest. Pinners look for understated spooky chic: "
             "classy ghost nail art, matte velvet pumpkin textures, and dark celestial spiderwebs designed to wear all October long."
        )
    else:
        description = (
            f"Pinners are heavily saving and searching for {clean_term}, focusing on high-aesthetic lifestyle framing, "
            f"candid compositions, and curated visual formulas for the upcoming season."
        )

    # Timeline labels follow the measured window when we have one; no invented
    # calendar months when we don't.
    if has_metric:
        timeline_dates = metric_info.get("timeline_dates") or _timeline_labels(
            datetime.now(timezone.utc).date()
        )
    else:
        timeline_dates = []

    deep_dive_data = {
        "term": clean_term,
        "category": category,
        "metric_provenance": metric_provenance,
        "description": description,
        "mom_change": metric_info.get("mom_change") if has_metric else None,
        "wow_change": metric_info.get("wow_change") if has_metric else None,
        "yoy_change": metric_info.get("yoy_change") if has_metric else None,
        "search_count": metric_info.get("search_count") if has_metric else None,
        "sparkline": metric_info.get("sparkline", []) if has_metric else [],
        "timeline_dates": timeline_dates,
        "related_searches": related_searches,
        "related_searches_provenance": "generated",
        "popular_pins": popular_pins,
        "indexing_window": metric_info.get("indexing_window") if has_metric else None,
        "recommended_board": metric_info.get("recommended_board", f"{clean_term.title()} Inspo & Ideas") if has_metric else f"{clean_term.title()} Inspo & Ideas",
        "monetization_angle": metric_info.get("monetization_angle", "Viral Lookbook / Blog Traffic") if has_metric else "Viral Lookbook / Blog Traffic",
    }

    # Never cache a fully-empty result (no pins AND no measured metric): it is
    # indistinguishable from an outage, and caching it would serve 12h of
    # empty gallery. The next click retries live instead.
    if not popular_pins and metric_provenance == "unavailable":
        logger.info(
            "Not caching empty deep-dive for %r (no pins, no metric) — will retry live",
            clean_term,
        )
    else:
        _write_cache(cache_key, [deep_dive_data])
    return deep_dive_data


# ── Public High-Level Interface with Local Disk Cache ────────────────────────

async def get_official_pinterest_trends(
    preset: str = "breakout",
    intent: str = "all",
    country: str = "US",
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """
    Get official Pinterest Trends with live 52-week search momentum,
    filtered by preset and intent (viral_blog vs commercial_product).

    Provenance contract: returned dicts always carry "provenance" and
    "is_fallback". Live results are cached; the curated fallback is served
    honestly tagged and NEVER cached, so callers (API, scheduler) can tell
    live data from demo data and a failed scrape cannot poison the cache.
    """
    cache_key = _official_cache_key(preset, country)

    if not force_refresh:
        cached = _read_cache(cache_key)
        if cached:
            if intent != "all":
                return [t for t in cached if t.get("intent") == intent]
            return cached

    # Try live Playwright extraction
    live_trends = await scrape_pinterest_trends_playwright(preset=preset, country=country, limit=25)

    if live_trends:
        tagged = _tag_live(live_trends)
        _write_cache(cache_key, tagged)
        if intent != "all":
            return [t for t in tagged if t.get("intent") == intent]
        return tagged

    logger.warning(
        "Pinterest Trends live scrape returned empty for preset %r country %s — "
        "serving curated fallback (NOT cached)",
        preset, country,
    )
    fallback = _tag_curated(CURATED_TRENDS_BY_PRESET.get(preset, CURATED_PINTEREST_TRENDS))

    if intent != "all":
        return [t for t in fallback if t.get("intent") == intent]
    return fallback

