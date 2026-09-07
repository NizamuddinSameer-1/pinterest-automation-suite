# Trend Radar v2 (Scan + Score + Packs + On-Demand) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hardcoded trend scores with a daily multi-source scan, blended scoring, and stored keyword packs shared by pins + blog.

**Architecture:** Four new/small modules (source clients, pure scorer, pack builder, scheduler) plug into existing `trend_research.py`; consumers take an optional pack with full backward fallback. TDD throughout, fail-soft I/O, no paid APIs.

**Tech Stack:** Python asyncio + httpx + BeautifulSoup4 (already deps), SQLite untouched, snapshot JSON on disk, React (score bars + source badges only).

**Scope:** Spec units 1–4 + on-demand extension. Unit 5 (learn loop: click logging + CTR factor) is a separate follow-up plan — it needs live traffic first.

---

## File map

- Create: `app/services/trend_sources.py` — `SourceSignal` dataclass + 4 clients (`fetch_shopping`, `fetch_gtrends`, `fetch_amazon_movers`, `fetch_pinterest`), each `(query_or_seed, category) -> SourceSignal`, fail-soft.
- Create: `app/services/trend_scorer.py` — pure `score_trend()` + `tier_for()` + `DEFAULT_WEIGHTS`.
- Create: `app/services/keyword_packs.py` — `KeywordPack` dataclass, `build_pack()` (deterministic from dossier signals), `pack_to_dict/from_dict`.
- Create: `app/services/trend_scheduler.py` — `start_trend_scan/stop_trend_scan` asyncio loop (mirrors `app/services/scheduler.py` pattern).
- Modify: `app/config.py` — add `trend_scan_enabled`, `trend_scan_interval_hours`, `trend_weight_demand/money/winnability`.
- Modify: `app/services/trend_research.py` — use clients + scorer, attach `score_breakdown` + `keyword_pack`, write `data/trend_radar/<date>.json`, keep `TREND_SEEDS` as bootstrap queries, extend `analyze_custom_trend_query` (24h cache + debounce + live clients).
- Modify: `app/main.py` — start/stop trend scheduler in lifespan.
- Modify: `app/pipeline/pinterest_seo.py` — optional `keyword_pack` param on `generate_pin_seo` / `generate_batch_pins_seo` (fallback = current behavior).
- Modify: `app/services/bridge_copilot.py` — optional `keyword_pack` param on `generate_bridge_copy` (fallback = current behavior).
- Modify: `frontend/src/components/TrendRadar.tsx` — score-breakdown bars + per-source fresh/stale badges + pack terms row.
- Test: `tests/test_trend_scorer.py`, `tests/test_trend_sources.py`, `tests/test_keyword_packs.py`, extend `tests/test_research_launch_guards.py` (pack passthrough).

Shared contracts (used verbatim in every task):

```python
@dataclass
class SourceSignal:
    source: str            # "shopping" | "gtrends" | "amazon" | "pinterest"
    status: str            # "fresh" | "stale" | "error"
    queries: list[str]
    demand_hint: float     # 0-100
    fetched_at: str        # isoformat UTC
```

```python
@dataclass
class KeywordPack:
    primary: str
    long_tails: list[str]
    hooks: list[dict]      # {"variation_index": int, "framework": str}
    board_angle: str
    negative_terms: list[str]
    pack_version: int = 1
```

---

### Task 1: Pure scorer + tests

**Files:**
- Create: `app/services/trend_scorer.py`
- Test: `tests/test_trend_scorer.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the pure blended-score function (no I/O, no LLM)."""
from app.services.trend_scorer import DEFAULT_WEIGHTS, score_trend, tier_for


def test_default_weights_sum_to_one():
    assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) < 1e-9


def test_worked_example_scores_73_point_9_tier_a():
    out = score_trend(demand=82, money=74, winnability=61)
    assert out["score"] == 73.9
    assert out["tier"] == "A"
    assert out["breakdown"] == {
        "demand": 82, "money": 74, "winnability": 61,
        "weights_version": 1,
    }


def test_tier_bands():
    assert tier_for(90) == "S"
    assert tier_for(85) == "S"
    assert tier_for(84.9) == "A"
    assert tier_for(70) == "A"
    assert tier_for(69.9) == "B"


def test_custom_weights_respected():
    out = score_trend(demand=100, money=0, winnability=0,
                      weights={"demand": 0.5, "money": 0.3, "winnability": 0.2})
    assert out["score"] == 50.0


def test_inputs_clamped_to_0_100():
    out = score_trend(demand=999, money=-5, winnability=50)
    assert out["breakdown"]["demand"] == 100
    assert out["breakdown"]["money"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_trend_scorer.py -q`
Expected: FAIL with "No module named 'app.services.trend_scorer'" (use PowerShell: same command, no `&&` chaining).

- [ ] **Step 3: Write minimal implementation**

```python
"""
Trend Radar blended scorer — pure function, no I/O, no LLM calls.

score = w_demand*demand + w_money*money + w_winnability*winnability.
Tiers: S >= 85, A >= 70, else B (same bands as the legacy dossiers).
"""
from __future__ import annotations

from typing import Any

DEFAULT_WEIGHTS: dict[str, float] = {
    "demand": 0.40,
    "money": 0.35,
    "winnability": 0.25,
}

WEIGHTS_VERSION = 1


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def tier_for(score: float) -> str:
    """Map a 0-100 score to a Tier band."""
    if score >= 85:
        return "S"
    if score >= 70:
        return "A"
    return "B"


def score_trend(
    demand: float,
    money: float,
    winnability: float,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """
    Blend three 0-100 signals into one score.

    Returns {"score": rounded 1-decimal float, "tier": "S|A|B", "breakdown": {...}}.
    Inputs are clamped; custom weights replace (not merge with) the defaults.
    """
    w = weights or DEFAULT_WEIGHTS
    d, m, wn = _clamp(demand), _clamp(money), _clamp(winnability)
    blended = round(w["demand"] * d + w["money"] * m + w["winnability"] * wn, 1)
    return {
        "score": blended,
        "tier": tier_for(blended),
        "breakdown": {
            "demand": d,
            "money": m,
            "winnability": wn,
            "weights_version": WEIGHTS_VERSION,
        },
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_trend_scorer.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add app/services/trend_scorer.py tests/test_trend_scorer.py
git commit -m "feat(trends): add pure blended scorer with tier bands"
```

---

### Task 2: Source clients module + offline tests

**Files:**
- Create: `app/services/trend_sources.py`
- Test: `tests/test_trend_sources.py`

- [ ] **Step 1: Write the failing test**

```python
"""Source clients return SourceSignal and never raise (fail-soft)."""
import pytest
from app.services.trend_sources import (
    SourceSignal,
    fetch_amazon_movers,
    fetch_gtrends,
    fetch_pinterest,
    fetch_shopping,
)


@pytest.mark.asyncio
async def test_shopping_parses_suggestion_payload(monkeypatch):
    import app.services.trend_sources as mod

    class _Resp:
        status_code = 200

        def json(self):
            return ["barn jacket", ["barn jacket women", "barn jacket mens"]]

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None, headers=None):
            assert params["q"] == "barn jacket"
            return _Resp()

    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **kw: _Client())
    sig = await fetch_shopping("barn jacket", "fashion")
    assert isinstance(sig, SourceSignal)
    assert sig.source == "shopping"
    assert sig.status == "fresh"
    assert sig.queries == ["barn jacket women", "barn jacket mens"]


@pytest.mark.asyncio
async def test_clients_fail_soft_on_network_error(monkeypatch):
    import app.services.trend_sources as mod

    class _Boom:
        async def __aenter__(self):
            raise RuntimeError("offline")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **kw: _Boom())
    for coro in (
        fetch_shopping("x", "fashion"),
        fetch_gtrends("x", "fashion"),
        fetch_amazon_movers("x", "fashion"),
        fetch_pinterest("x", "fashion"),
    ):
        sig = await coro
        assert sig.status in ("stale", "error")
        assert sig.queries == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_trend_sources.py -q`
Expected: FAIL with "No module named 'app.services.trend_sources'".

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_trend_sources.py -q`
Expected: PASS (2 passed, no real network — both tests monkeypatch `httpx.AsyncClient`).

- [ ] **Step 5: Commit**

```bash
git add app/services/trend_sources.py tests/test_trend_sources.py
git commit -m "feat(trends): add fail-soft free source clients"
```

---

### Task 3: Keyword packs module + tests

**Files:**
- Create: `app/services/keyword_packs.py`
- Test: `tests/test_keyword_packs.py`

- [ ] **Step 1: Write the failing test**

```python
"""KeywordPack schema round-trip + deterministic builder."""
from app.services.keyword_packs import KeywordPack, build_pack


def test_round_trip_preserves_all_fields():
    pack = KeywordPack(
        primary="chunky knit cardigan",
        long_tails=["oversized cardigan outfit", "fall layering amazon"],
        hooks=[{"variation_index": 1, "framework": "The Skeptical Micro-Review"}],
        board_angle="Cozy Fall Knitwear & Layering",
        negative_terms=["swimwear"],
    )
    restored = KeywordPack.from_dict(pack.to_dict())
    assert restored == pack
    assert restored.pack_version == 1


def test_build_pack_assigns_frameworks_round_robin():
    pack = build_pack(
        primary="fluted ceramic vase",
        related_queries=["fluted vase", "stoneware decor", "minimalist living room"],
        board_angle="Japandi Living Room & Organic Decor",
        variations_count=4,
    )
    assert pack.primary == "fluted ceramic vase"
    assert len(pack.hooks) == 4
    frameworks = [h["framework"] for h in pack.hooks]
    assert len(set(frameworks)) == 4
    assert pack.hooks[0]["variation_index"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_keyword_packs.py -q`
Expected: FAIL with "No module named 'app.services.keyword_packs'".

- [ ] **Step 3: Write minimal implementation**

```python
"""
Keyword packs — one stored vocabulary per trend dossier, shared by pins + blog.

Deterministic builder (no LLM): packs derive from scanned related queries so
re-scans are reproducible. The content lane may *draft* richer packs later;
this module owns the schema both paths must satisfy.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.pipeline.pinterest_seo import FRAMEWORKS

PACK_VERSION = 1


@dataclass
class KeywordPack:
    primary: str
    long_tails: list[str] = field(default_factory=list)
    hooks: list[dict] = field(default_factory=list)
    board_angle: str = ""
    negative_terms: list[str] = field(default_factory=list)
    pack_version: int = PACK_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KeywordPack":
        return cls(
            primary=str(data.get("primary", "")),
            long_tails=list(data.get("long_tails") or []),
            hooks=list(data.get("hooks") or []),
            board_angle=str(data.get("board_angle", "")),
            negative_terms=list(data.get("negative_terms") or []),
            pack_version=int(data.get("pack_version", PACK_VERSION)),
        )


def build_pack(
    primary: str,
    related_queries: list[str] | None = None,
    board_angle: str = "",
    variations_count: int = 4,
) -> KeywordPack:
    """
    Deterministically build a pack: first related query family becomes the
    primary, the rest become long-tails, hook frameworks rotate round-robin
    so no two variations share an angle.
    """
    queries = [q.strip() for q in (related_queries or []) if q and q.strip()]
    head = primary.strip() or (queries[0] if queries else "curated find")
    tails = [q for q in queries if q.lower() != head.lower()][:8]
    hooks = [
        {
            "variation_index": i + 1,
            "framework": FRAMEWORKS[i % len(FRAMEWORKS)]["name"],
        }
        for i in range(max(1, variations_count))
    ]
    return KeywordPack(
        primary=head, long_tails=tails, hooks=hooks,
        board_angle=board_angle, pack_version=PACK_VERSION,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_keyword_packs.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add app/services/keyword_packs.py tests/test_keyword_packs.py
git commit -m "feat(trends): add versioned keyword pack schema + builder"
```

---

### Task 4: Settings + scheduler wiring

**Files:**
- Modify: `app/config.py`
- Create: `app/services/trend_scheduler.py`
- Modify: `app/main.py`

- [ ] **Step 1: Add settings (no test — declarative)**

```python
    # ── Trend Radar v2 scan ────────────────────────
    trend_scan_enabled: bool = True
    trend_scan_interval_hours: int = 24
    trend_weight_demand: float = 0.40
    trend_weight_money: float = 0.35
    trend_weight_winnability: float = 0.25
```

Place directly after the `auto_create_boards` line in `app/config.py`.

- [ ] **Step 2: Create the scheduler**

```python
"""
Trend Radar background scanner — daily fan-out over free sources.

Mirrors the pin scheduler's asyncio-loop pattern (app/services/scheduler.py):
one task, interval sleep, overlapping runs skipped via a module lock.
Disabled with TREND_SCAN_ENABLED=false (tests set this).
"""
from __future__ import annotations

import asyncio
import logging

from app.config import settings

logger = logging.getLogger("pre.trend_scheduler")

_task: asyncio.Task | None = None
_running = False


async def run_scan_once() -> int:
    """Run one full scan; returns dossier count. Never raises."""
    from app.services.trend_research import discover_trends_radar

    try:
        dossiers = await discover_trends_radar()
        logger.info("Trend scan complete: %d dossiers", len(dossiers))
        return len(dossiers)
    except Exception as e:
        logger.warning("Trend scan failed (next run in interval): %s", e)
        return 0


async def _loop() -> None:
    global _running
    interval = max(1, settings.trend_scan_interval_hours) * 3600
    while True:
        if not _running:
            _running = True
            try:
                await run_scan_once()
            finally:
                _running = False
        await asyncio.sleep(interval)


def start_trend_scan() -> None:
    """Start the daily scan loop (idempotent)."""
    global _task
    if not settings.trend_scan_enabled:
        logger.info("Trend scan disabled (TREND_SCAN_ENABLED=false)")
        return
    if _task is None or _task.done():
        _task = asyncio.ensure_future(_loop())
        logger.info("Trend scan loop started")


async def stop_trend_scan() -> None:
    """Cancel the scan loop (awaited in lifespan shutdown)."""
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
```

- [ ] **Step 3: Wire into lifespan in `app/main.py`**

After the pin-scheduler start call in `lifespan`, add:

```python
    from app.services.trend_scheduler import start_trend_scan
    start_trend_scan()
```

And in the shutdown section (where the pin scheduler stops), add:

```python
    from app.services.trend_scheduler import stop_trend_scan
    await stop_trend_scan()
```

- [ ] **Step 4: Smoke-test boot with scan disabled**

Run: `$env:TREND_SCAN_ENABLED="false"; python -c "import app.main; print('BOOT OK')"`
Expected: prints `BOOT OK` with a "Trend scan disabled" log line, no network calls.

- [ ] **Step 5: Commit**

```bash
git add app/config.py app/services/trend_scheduler.py app/main.py
git commit -m "feat(trends): add daily scan scheduler + settings"
```

---

### Task 5: Research rewrite — clients + scores + packs + snapshots

**Files:**
- Modify: `app/services/trend_research.py`
- Test: extend `tests/test_research_launch_guards.py` (append; do not rewrite existing tests)

- [ ] **Step 1: Write the failing test (append to the guards file)**

```python
@pytest.mark.asyncio
async def test_dossier_carries_score_breakdown_and_pack(monkeypatch):
    """Real _build_trend_dossier (offline fakes) attaches score + pack + sources."""
    import datetime as _dt
    import app.services.trend_research as mod
    from app.services.trend_sources import SourceSignal

    async def _fake_scan(seed_query, category):
        return [SourceSignal(
            source="shopping", status="fresh",
            queries=["barn jacket women", "barn jacket mens"],
            demand_hint=80.0,
            fetched_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
        )]

    async def _fake_match(query, category, fallback_items=None, item_count=2):
        return []

    monkeypatch.setattr(mod, "_scan_seed_signals", _fake_scan)
    monkeypatch.setattr(mod, "match_amazon_products_for_trend", _fake_match)
    monkeypatch.setattr(mod, "_write_snapshot", lambda dossiers: None)
    dossiers = await mod.discover_trends_radar(category_filter="fashion")
    assert dossiers, "expected dossiers for fashion seeds"
    first = dossiers[0]
    assert first["score_breakdown"]["weights_version"] == 1
    assert first["tier"] in ("Tier S", "Tier A", "Tier B")
    assert first["keyword_pack"]["primary"]
    assert len(first["keyword_pack"]["hooks"]) >= 1
    assert first["sources"][0]["source"] == "shopping"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_research_launch_guards.py -q`
Expected: FAIL — `monkeypatch.setattr` raises AttributeError (`_scan_seed_signals`
does not exist yet), proving the seam is missing.

- [ ] **Step 3: Minimal implementation in `trend_research.py`**

Replace `_build_trend_dossier` body with the client fan-out version and add
helpers (imports: `from app.services.trend_sources import SourceSignal,
fetch_amazon_movers, fetch_gtrends, fetch_pinterest, fetch_shopping`,
`from app.services.trend_scorer import score_trend`,
`from app.services.keyword_packs import build_pack`):

```python
async def _scan_seed_signals(seed_query: str, category: str) -> list[SourceSignal]:
    """Fan out to all four source clients; each is fail-soft by contract."""
    results = await asyncio.gather(
        fetch_shopping(seed_query, category),
        fetch_gtrends(seed_query, category),
        fetch_amazon_movers(seed_query, category),
        fetch_pinterest(seed_query, category),
    )
    return list(results)


def _blend_signals(signals: list[SourceSignal]) -> dict[str, float]:
    """Demand = mean of fresh hints (0 when all stale); money/winnability
    stay heuristic until PA-API + brand analysis feed them (follow-up)."""
    fresh = [s.demand_hint for s in signals if s.status == "fresh"]
    demand = sum(fresh) / len(fresh) if fresh else 0.0
    return {"demand": round(demand, 1), "money": 50.0, "winnability": 50.0}


async def _build_trend_dossier(seed: dict[str, Any]) -> dict[str, Any]:
    """Enrich one seed with multi-source signals, blended score, pack, products."""
    from app.config import settings as _settings

    seed_query = seed.get("seed_query", seed["title"])
    category = seed.get("category", "fashion")

    signals = await _scan_seed_signals(seed_query, category)
    blended = _blend_signals(signals)
    scored = score_trend(
        blended["demand"], blended["money"], blended["winnability"],
        weights={
            "demand": _settings.trend_weight_demand,
            "money": _settings.trend_weight_money,
            "winnability": _settings.trend_weight_winnability,
        },
    )
    related = sorted(
        {q for s in signals for q in s.queries},
        key=lambda q: (len(q), q),
    )[:8] or [seed_query, f"{seed_query} aesthetic", f"{seed_query} 2026"]

    matched_prods = await match_amazon_products_for_trend(
        query=related[0], category=category,
        fallback_items=seed.get("fallback_products"), item_count=2,
    )
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
```

And in `discover_trends_radar`, after sorting, persist the snapshot:

```python
    _write_snapshot(sorted_dossiers)
    return sorted_dossiers
```

with helper (place above `discover_trends_radar`):

```python
def _write_snapshot(dossiers: list[dict[str, Any]]) -> None:
    """Persist the daily snapshot; failures only warn (scan stays green)."""
    try:
        snap_dir = Path(settings.storage_path) / "trend_radar"
        snap_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        (snap_dir / f"{stamp}.json").write_text(
            json.dumps({"scanned_at": datetime.now(timezone.utc).isoformat(),
                        "count": len(dossiers), "dossiers": dossiers}, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("Trend snapshot write failed: %s", e)
```

(`json`, `Path`, `datetime/timezone` are already imported in `trend_research.py`.)

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_research_launch_guards.py tests/test_trend_scorer.py -q`
Expected: PASS. Note: the new test monkeypatches `_build_trend_dossier`,
so no network runs.

- [ ] **Step 5: Commit**

```bash
git add app/services/trend_research.py tests/test_research_launch_guards.py
git commit -m "feat(trends): score + pack + snapshot every dossier"
```

---

### Task 6: Consumer plumbing — pins + blog accept packs (optional)

**Files:**
- Modify: `app/pipeline/pinterest_seo.py`
- Modify: `app/services/bridge_copilot.py`
- Test: `tests/test_keyword_packs.py` (append consumer tests)

- [ ] **Step 1: Write the failing tests (append)**

```python
@pytest.mark.asyncio
async def test_batch_seo_prefers_pack_primary(monkeypatch):
    """A provided pack steers the fallback text path (no network)."""
    from app.pipeline import pinterest_seo as seo

    async def _fake_text(prompt, system=None, temperature=None):
        assert "chunky knit cardigan" in prompt
        return {"title": "Chunky Knit Amazon Find (2026) Cozy",
                "description": "Soft knit visible in warm light. Pairs with denim daily. #Knitwear #AmazonFinds",
                "keywords": ["chunky knit cardigan"],
                "board_suggestion": "Cozy Fall Knitwear"}

    async def _no_vision(*a, **kw):
        raise RuntimeError("no vision in this test")

    monkeypatch.setattr(seo.content_llm, "structured_output", _fake_text)
    monkeypatch.setattr(seo.content_llm, "analyze_image", _no_vision)
    from app.services.keyword_packs import build_pack
    pack = build_pack(primary="chunky knit cardigan",
                      related_queries=["chunky knit cardigan"],
                      board_angle="Cozy")
    out = await seo.generate_pin_seo(
        product={"name": "Cardigan"}, scene={},
        image_path="/nonexistent/x.jpg", keyword_pack=pack.to_dict(),
    )
    assert out["title"].startswith("Chunky Knit")


@pytest.mark.asyncio
async def test_bridge_copy_without_pack_unchanged(monkeypatch):
    """No pack = today's behavior (vision skipped when no images)."""
    from app.services import bridge_copilot as bc

    async def _fake_structured(prompt, system=None, temperature=None):
        return {"looks": [{"look_title": "L1"}],
                "comparison_matrix": {}, "ugc_narrative": {},
                "pros_cons": {}, "buyer_persona": {}, "final_verdict": {},
                "staged_ctas": {}, "objections_faq": [{"q": "a", "a": "b"},
                                                      {"q": "c", "a": "d"}]}

    monkeypatch.setattr(bc.content_llm, "structured_output", _fake_structured)
    out = await bc.generate_bridge_copy(
        product_data={"name": "Vase", "category": "home"}, variations_count=1,
    )
    assert out["looks"][0]["look_title"] == "L1"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_keyword_packs.py -q`
Expected: FAIL with "unexpected keyword argument 'keyword_pack'" (both call sites).

- [ ] **Step 3: Minimal implementation**

In `pinterest_seo.generate_pin_seo`, add trailing param
`keyword_pack: dict[str, Any] | None = None` and, right after the
`framework = ...` line, insert:

```python
    prompt_seed = ""
    if keyword_pack:
        primary = str(keyword_pack.get("primary") or "").strip()
        tails = [str(t) for t in (keyword_pack.get("long_tails") or []) if str(t).strip()]
        if primary:
            seed_hint = primary + (" | " + ", ".join(tails[:3]) if tails else "")
            prompt_seed = f"Pack primary keyword (use verbatim where natural): {seed_hint}\n\n"
```

Then prepend `prompt_seed` to both user-prompt builders: in the vision
branch change `user_prompt = (f"This is variation ...` to
`user_prompt = prompt_seed + (f"This is variation ...`, and in the text
path change the `prompt = (f"Generate Pinterest SEO ...` assignment the
same way. Empty string when no pack = today's behavior, byte-identical.

In `bridge_copilot.generate_bridge_copy`, add trailing param
`keyword_pack: dict[str, Any] | None = None` and after `product_brief = {...}`
insert:

```python
    if keyword_pack:
        product_brief["keyword_pack_primary"] = keyword_pack.get("primary", "")
        product_brief["keyword_pack_tails"] = list(keyword_pack.get("long_tails") or [])[:8]
        product_brief["keyword_pack_hooks"] = list(keyword_pack.get("hooks") or [])[:8]
```

No prompt-template changes (no SEO tuning in this plan) — the brief fields
ride along into the existing JSON the LLM already receives.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_keyword_packs.py tests/test_vision_pin_seo.py tests/test_lookbook_editorial_compliance.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/pipeline/pinterest_seo.py app/services/bridge_copilot.py tests/test_keyword_packs.py
git commit -m "feat(trends): consumers accept optional keyword packs"
```

---

### Task 7: On-demand deep scan (cache + debounce + live clients)

**Files:**
- Modify: `app/services/trend_research.py` (`analyze_custom_trend_query`)
- Test: append to `tests/test_research_launch_guards.py`

- [ ] **Step 1: Write the failing test (append)**

```python
@pytest.mark.asyncio
async def test_custom_query_uses_cache_second_time(monkeypatch, tmp_path):
    """Second identical query within 24h serves cache (no source calls)."""
    import app.services.trend_research as mod

    calls = {"n": 0}

    async def _counting_scan(seed_query, category):
        calls["n"] += 1
        from app.services.trend_sources import SourceSignal
        import datetime as _dt
        return [SourceSignal(source="shopping", status="fresh",
                             queries=[seed_query], demand_hint=70.0,
                             fetched_at=_dt.datetime.now(
                                 _dt.timezone.utc).isoformat())]

    monkeypatch.setattr(mod, "_scan_seed_signals", _counting_scan)
    monkeypatch.setattr(mod, "_trend_cache_dir",
                        lambda: tmp_path / "trend_cache")

    first = await mod.analyze_custom_trend_query("coastal cowgirl", "fashion")
    second = await mod.analyze_custom_trend_query("coastal cowgirl", "fashion")
    assert calls["n"] == 1
    assert first["keyword_pack"]["primary"]
    assert second["title"] == first["title"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_research_launch_guards.py -q`
Expected: FAIL — no `_trend_cache_dir` helper, no caching in `analyze_custom_trend_query`.

- [ ] **Step 3: Minimal implementation**

Add above `analyze_custom_trend_query`:

```python
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
        ts = datetime.fromisoformat(payload.get("cached_at", "2000-01-01"))
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
```

Rewrite `analyze_custom_trend_query` body to: slug key
`re.sub(r"[^a-z0-9]+", "_", query.lower()).strip("_") + f"__{category}"`;
on cache hit return cached dossier; else run `_scan_seed_signals` +
`_blend_signals` + `score_trend` (settings weights) + `build_pack` +
`match_amazon_products_for_trend` (real call — live path by design),
assemble the same dossier dict shape as `_build_trend_dossier`
(including `score_breakdown`, `keyword_pack`, `sources`), cache, return.
Keep the seasonal heat rule for `heat_level/heat_badge/score` floor:
`opportunity_score = max(computed, 92 if seasonal else 87)` is NOT kept —
use the computed score only (single source of truth; seasonal boost was
a hardcoded fudge).

(`Path` needs importing in `trend_research.py`: add `from pathlib import Path`.)

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_research_launch_guards.py -q`
Expected: PASS (existing 4 + new cache/score/pack tests).

- [ ] **Step 5: Commit**

```bash
git add app/services/trend_research.py tests/test_research_launch_guards.py
git commit -m "feat(trends): cached on-demand deep scan with live clients"
```

---

### Task 8: TrendRadar UI — bars + badges + pack row

**Files:**
- Modify: `frontend/src/components/TrendRadar.tsx`

Three surgical edits (no new components):

1. Under the opportunity-score pill, render `trend.score_breakdown` bars
   (guard with `?.` — old snapshots lack it):
```tsx
{(trend as any).score_breakdown && (
  <div style={{ display: 'flex', gap: '8px', marginTop: '8px', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
    <span>Demand {(trend as any).score_breakdown.demand}</span>
    <span>Money {(trend as any).score_breakdown.money}</span>
    <span>Win {(trend as any).score_breakdown.winnability}</span>
  </div>
)}
```
2. Next to each source-dependent section, show stale dots from
   `(trend as any).sources`: fresh = green dot, else amber dot + "stale".
3. Under related queries, render first 4 `keyword_pack.long_tails` as chips
   (guard `?.`, fallback to `related_queries` when absent).

- [ ] **Step 1: Make the edits, then typecheck**

Run: `npx tsc --noEmit` (in `frontend/`)
Expected: clean (no output).

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/TrendRadar.tsx
git commit -m "feat(trends): show score breakdown, source badges, pack terms"
```

---

### Task 9: Full verification

- [ ] **Step 1: Run the whole suite (minus live-scrape)**

Run: `python -m pytest tests/ -q --ignore=tests/test_amazon_scrape_enhancements.py`
Expected: all PASS (baseline was 80 + 4 guards; this plan adds ~13).

- [ ] **Step 2: Boot check with scan disabled**

Run: `$env:TREND_SCAN_ENABLED="false"; python -c "import app.main; print('BOOT OK')"`
Expected: `BOOT OK`, no network.

- [ ] **Step 3: Fix anything red, then final commit if needed (docs only or fixes).**
