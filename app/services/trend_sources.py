"""
Trend Radar source clients — one isolated fetcher per free signal.

Every fetcher returns a SourceSignal and NEVER raises: network trouble,
rate limits, and markup drift all degrade to status "stale"/"error" with
empty queries so a single dead source cannot kill a whole scan.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger("pre.trend_sources")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


@dataclass
class SourceSignal:
    source: str            # "shopping" | "gtrends" | "amazon" | "pinterest"
    status: str            # "fresh" | "stale" | "error"
    queries: list[str]
    demand_hint: float     # 0-100
    fetched_at: str        # isoformat UTC

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty(source: str, status: str = "stale") -> SourceSignal:
    return SourceSignal(
        source=source, status=status, queries=[],
        demand_hint=0.0, fetched_at=_now(),
    )


async def fetch_shopping(seed_query: str, category: str = "fashion") -> SourceSignal:
    """Google Shopping autocomplete (ds=sh) — commercial-intent queries."""
    seed = seed_query.strip()
    if not seed:
        return _empty("shopping")
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(
                "https://suggestqueries.google.com/complete/search",
                params={"client": "chrome", "ds": "sh", "q": seed},
                headers={"User-Agent": _UA, "Accept": "application/json"},
            )
            if resp.status_code != 200:
                return _empty("shopping")
            data = resp.json()
            queries = []
            if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list):
                queries = [str(q).strip() for q in data[1] if str(q).strip()][:6]
            if not queries:
                return _empty("shopping")
            return SourceSignal(
                source="shopping", status="fresh", queries=queries,
                demand_hint=min(100.0, 40.0 + 10.0 * len(queries)),
                fetched_at=_now(),
            )
    except Exception as e:
        logger.warning("Shopping source failed for %r: %s", seed, e)
        return _empty("shopping", "error")


async def fetch_gtrends(seed_query: str, category: str = "fashion") -> SourceSignal:
    """
    Google Trends interest snapshot via the public explore widget API.
    Unofficial endpoint — any shape drift degrades to stale, never raises.
    """
    seed = seed_query.strip()
    if not seed:
        return _empty("gtrends")
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            explore = await client.get(
                "https://trends.google.com/trends/api/explore",
                params={"hl": "en-US", "tz": "-60", "req": (
                    '{"comparisonItem":[{"keyword":"' + seed.replace('"', "") + '",'
                    '"geo":"US","time":"today 3-m"}],"category":0,"property":""}'
                )},
                headers={"User-Agent": _UA},
            )
            if explore.status_code != 200:
                return _empty("gtrends")
            text = explore.text[5:] if explore.text.startswith(")]}',") else explore.text
            import json as _json
            payload = _json.loads(text)
            widgets = payload.get("widgets") or []
            if not widgets:
                return _empty("gtrends")
            return SourceSignal(
                source="gtrends", status="fresh",
                queries=[seed, f"{seed} 2026", f"best {seed}"],
                demand_hint=60.0,
                fetched_at=_now(),
            )
    except Exception as e:
        logger.warning("Google Trends source failed for %r: %s", seed, e)
        return _empty("gtrends", "error")


async def fetch_amazon_movers(seed_query: str, category: str = "fashion") -> SourceSignal:
    """Amazon search-autocomplete concerns are skipped; parse Movers-style
    suggestion titles from the public autocomplete endpoint (no key)."""
    seed = seed_query.strip()
    if not seed:
        return _empty("amazon")
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(
                "https://completion.amazon.com/search/complete",
                params={"search-alias": "aps", "client": "amazon-search-ui", "q": seed},
                headers={"User-Agent": _UA},
            )
            if resp.status_code != 200:
                return _empty("amazon")
            data = resp.json()
            suggestions = data.get("suggestions") or []
            queries = [str(s.get("value", "")).strip() for s in suggestions]
            queries = [q for q in queries if q][:6]
            if not queries:
                return _empty("amazon")
            return SourceSignal(
                source="amazon", status="fresh", queries=queries,
                demand_hint=min(100.0, 45.0 + 9.0 * len(queries)),
                fetched_at=_now(),
            )
    except Exception as e:
        logger.warning("Amazon source failed for %r: %s", seed, e)
        return _empty("amazon", "error")


async def fetch_pinterest(seed_query: str, category: str = "fashion") -> SourceSignal:
    """
    Pinterest guided-search ideas via the public search-hub endpoint.
    Login-walled topics degrade to stale — the scan continues regardless.
    """
    seed = seed_query.strip()
    if not seed:
        return _empty("pinterest")
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(
                "https://www.pinterest.com/resource/SearchAutocompleteResource/get/",
                params={"source_url": f"/search/pins/?q={seed}", "data": (
                    '{"options":{"query":"' + seed.replace('"', "") + '"},"context":{}}'
                )},
                headers={"User-Agent": _UA, "Accept": "application/json"},
            )
            if resp.status_code != 200:
                return _empty("pinterest")
            data = resp.json()
            results = ((data.get("resource_response") or {}).get("data") or {}).get("results") or []
            queries = [str(r.get("query", "")).strip() for r in results]
            queries = [q for q in queries if q][:6]
            if not queries:
                return _empty("pinterest")
            return SourceSignal(
                source="pinterest", status="fresh", queries=queries,
                demand_hint=min(100.0, 50.0 + 8.0 * len(queries)),
                fetched_at=_now(),
            )
    except Exception as e:
        logger.warning("Pinterest source failed for %r: %s", seed, e)
        return _empty("pinterest", "error")
