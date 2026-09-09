"""
Unit tests for Official Pinterest Trends Scraper & Intelligence Service.
"""

import pytest
from app.services.pinterest_trends_scraper import (
    classify_trend_intent,
    calculate_indexing_window,
    _clean_growth_pct,
    get_official_pinterest_trends,
    CURATED_PINTEREST_TRENDS,
)


def test_classify_trend_intent():
    """Verify that nail, hair, outfit, and wallpaper terms are classified as viral_blog."""
    assert classify_trend_intent("fall nail colors 2026") == "viral_blog"
    assert classify_trend_intent("halloween nails") == "viral_blog"
    assert classify_trend_intent("hairstyles headband") == "viral_blog"
    assert classify_trend_intent("usa football theme outfit") == "viral_blog"
    assert classify_trend_intent("autumn aesthetic wallpaper") == "viral_blog"

    # Physical buyable items
    assert classify_trend_intent("corduroy barn jacket") == "commercial_product"
    assert classify_trend_intent("projection lamp") == "commercial_product"


def test_calculate_indexing_window():
    """Verify 20-day indexing advice calculation based on search counts and growth."""
    # Low counts but high growth -> rising early window
    rising_counts = [
        {"normalizedCount": 2, "date": "2026-08-01"},
        {"normalizedCount": 5, "date": "2026-08-15"},
        {"normalizedCount": 16, "date": "2026-08-28"},
    ]
    res_rising = calculate_indexing_window(rising_counts, mom_change=150.0)
    assert "Pin NOW" in res_rising["advice"]
    assert res_rising["urgency"] == "high"

    # High count >= 80 -> peaking active
    peak_counts = [
        {"normalizedCount": 85, "date": "2026-08-28"},
    ]
    res_peak = calculate_indexing_window(peak_counts, mom_change=20.0)
    assert "Active" in res_peak["advice"] or "Peak" in res_peak["advice"]
    assert res_peak["urgency"] == "immediate"


def test_clean_growth_pct():
    """Verify string and numeric growth rate parsing."""
    assert _clean_growth_pct(100.0) == 100.0
    assert _clean_growth_pct("+3,000%") == 3000.0
    assert _clean_growth_pct("250.5%") == 250.5
    assert _clean_growth_pct(None) == 0.0


@pytest.mark.asyncio
async def test_get_official_pinterest_trends_filters():
    """Verify intent filtering and fallback returns."""
    # Test intent filter on curated data
    all_trends = await get_official_pinterest_trends(preset="breakout", intent="all", force_refresh=False)
    assert len(all_trends) > 0

    blog_trends = await get_official_pinterest_trends(preset="breakout", intent="viral_blog", force_refresh=False)
    assert all(t["intent"] == "viral_blog" for t in blog_trends)

    prod_trends = await get_official_pinterest_trends(preset="breakout", intent="commercial_product", force_refresh=False)
    assert all(t["intent"] == "commercial_product" for t in prod_trends)


@pytest.mark.asyncio
async def test_official_trends_fallback_tagged_and_not_cached(tmp_path, monkeypatch):
    """Curated fallback must be honestly tagged and NEVER written to cache."""
    import app.services.pinterest_trends_scraper as scraper
    from app.config import settings

    monkeypatch.setattr(settings, "storage_path", str(tmp_path))

    async def _empty(**kwargs):
        return []

    monkeypatch.setattr(scraper, "scrape_pinterest_trends_playwright", _empty)

    trends = await scraper.get_official_pinterest_trends(preset="breakout", force_refresh=True)
    assert len(trends) > 0
    assert all(t.get("is_fallback") is True for t in trends)
    assert all(t.get("provenance") == "curated_fallback" for t in trends)

    cache_dir = tmp_path / "pinterest_trends"
    assert not cache_dir.exists() or list(cache_dir.glob("*.json")) == []

    # Second call still falls back (nothing was cached) and globals are unmutated.
    trends2 = await scraper.get_official_pinterest_trends(preset="breakout", force_refresh=True)
    assert all(t.get("is_fallback") is True for t in trends2)
    assert all("is_fallback" not in t for t in scraper.CURATED_PINTEREST_TRENDS)


@pytest.mark.asyncio
async def test_official_trends_live_tagged_and_cached(tmp_path, monkeypatch):
    """Live scrape results must be tagged live, cached, and served from cache."""
    import app.services.pinterest_trends_scraper as scraper
    from app.config import settings

    monkeypatch.setattr(settings, "storage_path", str(tmp_path))

    live = [
        {"term": "live trend one", "intent": "viral_blog", "category": "beauty"},
        {"term": "live trend two", "intent": "commercial_product", "category": "fashion"},
    ]

    async def _live(**kwargs):
        return [dict(t) for t in live]

    monkeypatch.setattr(scraper, "scrape_pinterest_trends_playwright", _live)

    trends = await scraper.get_official_pinterest_trends(preset="breakout", force_refresh=True)
    assert len(trends) == 2
    assert all(t.get("is_fallback") is False for t in trends)
    assert all(t.get("provenance") == "live" for t in trends)
    assert len(list((tmp_path / "pinterest_trends").glob("*.json"))) == 1

    # Cache hit: scraper must not be called again.
    async def _boom(**kwargs):
        raise AssertionError("scraper called on cache hit")

    monkeypatch.setattr(scraper, "scrape_pinterest_trends_playwright", _boom)
    cached = await scraper.get_official_pinterest_trends(preset="breakout", force_refresh=False)
    assert len(cached) == 2
    assert all(t.get("is_fallback") is False for t in cached)

    # Intent filtering still works on live data.
    blog = await scraper.get_official_pinterest_trends(
        preset="breakout", intent="viral_blog", force_refresh=False
    )
    assert [t["term"] for t in blog] == ["live trend one"]


@pytest.mark.asyncio
async def test_official_trends_api_source_honest(monkeypatch):
    """API must report curated_fallback source when serving the fallback."""
    import app.api.research as research_mod

    async def _fallback(**kwargs):
        return [{"term": "demo", "intent": "viral_blog", "is_fallback": True,
                 "provenance": "curated_fallback"}]

    monkeypatch.setattr(research_mod, "get_official_pinterest_trends", _fallback)
    res = await research_mod.get_pinterest_official_trends(
        preset="breakout", intent="all", country="US", refresh=True
    )
    assert res["is_fallback"] is True
    assert res["source"] == "curated_fallback"

    async def _live(**kwargs):
        return [{"term": "real", "intent": "viral_blog", "is_fallback": False,
                 "provenance": "live"}]

    monkeypatch.setattr(research_mod, "get_official_pinterest_trends", _live)
    res2 = await research_mod.get_pinterest_official_trends(
        preset="breakout", intent="all", country="US", refresh=True
    )
    assert res2["is_fallback"] is False
    assert res2["source"] == "trends.pinterest.com"


@pytest.mark.asyncio
async def test_scheduler_does_not_cache_curated_fallback(tmp_path, monkeypatch):
    """Daily scheduler with a broken scraper must not write fallback into cache."""
    import app.services.trend_scheduler as sched
    import app.services.trend_research as research_svc
    import app.services.pinterest_trends_scraper as scraper
    from app.config import settings

    monkeypatch.setattr(settings, "storage_path", str(tmp_path))

    async def _no_dossiers(*args, **kwargs):
        return []

    async def _empty(**kwargs):
        return []

    monkeypatch.setattr(research_svc, "discover_trends_radar", _no_dossiers)
    monkeypatch.setattr(scraper, "scrape_pinterest_trends_playwright", _empty)

    await sched.run_scan_once()
    cache_dir = tmp_path / "pinterest_trends"
    assert not cache_dir.exists() or list(cache_dir.glob("official_*.json")) == []


def test_build_custom_metric_item_refuses_empty_counts():
    """No trajectory counts → None (never a fabricated sparkline)."""
    from app.services.pinterest_trends_scraper import _build_custom_metric_item

    assert _build_custom_metric_item("blue velvet sofa", {"growth_rates": {"mom_change": 12.0}, "counts": []}, {}) is None
    assert _build_custom_metric_item("blue velvet sofa", {"growth_rates": {}}, {}) is None
    assert _build_custom_metric_item("blue velvet sofa", {}, {}) is None


def test_build_custom_metric_item_uses_real_counts():
    """Real counts flow through untouched — no placeholder values."""
    from app.services.pinterest_trends_scraper import _build_custom_metric_item

    target = {
        "growth_rates": {"mom_change": 42.5, "wow_change": 5.0, "yoy_change": 0},
        "counts": [{"normalizedCount": n} for n in (4, 9, 21, 44, 71)],
    }
    item = _build_custom_metric_item("emerald tufted headboard", target, {})
    assert item is not None
    assert item["sparkline"] == [4, 9, 21, 44, 71]
    assert item["sparkline"] != [10, 20, 35, 50, 75, 100]
    assert item["search_count"] == 71
    assert item["mom_change"] == 42.5


@pytest.mark.asyncio
async def test_query_official_trend_404_when_no_data(monkeypatch):
    """Empty scrape → honest 404, never success:true with invented numbers."""
    import app.api.research as research_mod
    from fastapi import HTTPException

    async def _none(**kwargs):
        return None

    monkeypatch.setattr(research_mod, "scrape_custom_pinterest_trend_metrics", _none)

    req = research_mod.OfficialPinterestTrendQueryRequest(query="zzz no such trend", country="US")
    with pytest.raises(HTTPException) as exc:
        await research_mod.query_pinterest_official_trend(req)
    assert exc.value.status_code == 404
    assert "zzz no such trend" in exc.value.detail


@pytest.mark.asyncio
async def test_query_official_trend_passthrough(monkeypatch):
    """Live item is returned verbatim — no injected fallback fields."""
    import app.api.research as research_mod

    live = {"term": "real term", "sparkline": [1, 2, 3], "mom_change": 9.0}

    async def _live(**kwargs):
        return dict(live)

    monkeypatch.setattr(research_mod, "scrape_custom_pinterest_trend_metrics", _live)

    req = research_mod.OfficialPinterestTrendQueryRequest(query="real term", country="US")
    res = await research_mod.query_pinterest_official_trend(req)
    assert res["success"] is True
    assert res["trend"] == live


def test_loop_can_spawn_subprocess_no_loop():
    """No running loop (plain threads) implies spawn-capable."""
    import asyncio
    import app.services.pinterest_trends_scraper as scraper

    assert scraper._loop_can_spawn_subprocess() is True


def test_loop_can_spawn_subprocess_selector(monkeypatch):
    """A non-Proactor running loop is detected (uvicorn --reload case)."""
    import asyncio
    import app.services.pinterest_trends_scraper as scraper

    monkeypatch.setattr(asyncio, "get_running_loop", lambda: object())
    assert scraper._loop_can_spawn_subprocess() is False


def test_parse_worker_output():
    """Worker stdout parsing: ok / error-dict / garbage / nonzero exit."""
    import subprocess
    import app.services.pinterest_trends_scraper as scraper

    def _completed(rc, out, err=""):
        return subprocess.CompletedProcess(args=["w"], returncode=rc, stdout=out, stderr=err)

    assert scraper._parse_worker_output("popular_pins", _completed(0, '[{"a": 1}]')) == [{"a": 1}]
    assert scraper._parse_worker_output("popular_pins", _completed(0, '{"error": "boom"}')) is None
    assert scraper._parse_worker_output("popular_pins", _completed(0, "not json")) is None
    assert scraper._parse_worker_output("popular_pins", _completed(1, "[]", "traceback")) is None


@pytest.mark.asyncio
async def test_selector_loop_delegates_to_worker(monkeypatch):
    """On a bad loop the public scrapers delegate instead of launching browsers."""
    import app.services.pinterest_trends_scraper as scraper

    async def _fake_delegate(cmd, args, timeout_s):
        assert cmd in ("official_trends", "custom_metrics", "popular_pins")
        return True, {"delegated": cmd}

    monkeypatch.setattr(scraper, "_scrape_via_worker_if_needed",
                        lambda *a, **k: _fake_delegate(*a, **k))

    # popular_pins/custom_metrics coerce non-list/dict worker output to empty.
    pins = await scraper.scrape_popular_pins_for_term("x", count=3)
    assert pins == []
    metric = await scraper.scrape_custom_pinterest_trend_metrics("x")
    assert metric == {"delegated": "custom_metrics"}
    trends = await scraper.scrape_pinterest_trends_playwright(preset="breakout")
    assert trends == []


def test_worker_custom_metrics_kwarg(monkeypatch, tmp_path, capsys):
    """Worker custom_metrics must call the scraper with query= (was clean_query=).

    Sync test on purpose: the worker entrypoint uses asyncio.run(), which
    refuses to run inside an already-running event loop.
    """
    import sys
    import runpy
    import app.services.pinterest_trends_scraper as scraper

    seen = {}

    async def _capture(query, country="US"):
        seen["query"] = query
        seen["country"] = country
        return {"term": query}

    monkeypatch.setattr(scraper, "scrape_custom_pinterest_trend_metrics", _capture)
    monkeypatch.setattr(sys, "argv", ["scrape_trends_worker", "custom_metrics", "my term", "US"])
    runpy.run_path("scripts/scrape_trends_worker.py", run_name="__main__")
    assert seen == {"query": "my term", "country": "US"}


@pytest.mark.asyncio
async def test_deep_dive_fully_empty_not_cached(tmp_path, monkeypatch):
    """No pins + no metric → served but never written (no 12h empty poison)."""
    import app.services.pinterest_trends_scraper as scraper
    from app.config import settings

    monkeypatch.setattr(settings, "storage_path", str(tmp_path))

    async def _empty(*args, **kwargs):
        return []

    async def _none(*args, **kwargs):
        return None

    monkeypatch.setattr(scraper, "scrape_popular_pins_for_term", _empty)
    monkeypatch.setattr(scraper, "scrape_custom_pinterest_trend_metrics", _none)

    data = await scraper.get_trend_deep_dive("ghost term xyz", country="US", force_refresh=True)
    assert data["popular_pins"] == []
    assert data["metric_provenance"] == "unavailable"
    cache_dir = tmp_path / "pinterest_trends"
    assert not cache_dir.exists() or list(cache_dir.glob("*.json")) == []


def test_extract_term_image_urls_shapes():
    """Normalizes bare strings, pin objects, nesting; drops non-pinimg."""
    from app.services.pinterest_trends_scraper import _extract_term_image_urls as ex

    assert ex(None) == []
    assert ex("nope") == []
    data = {
        "nails": ["https://i.pinimg.com/736x/a/1.jpg", "https://example.com/x.jpg"],
        "hair": [
            {"images": {"orig": {"url": "https://i.pinimg.com/736x/b/2.jpg"}}},
            {"image_url": "https://i.pinimg.com/736x/c/3.jpg"},
            {"nope": 1},
        ],
        "wrap": {"data": {"deep": ["https://i.pinimg.com/736x/d/4.jpg"]}},
    }
    pairs = ex(data)
    assert len(pairs) == 4
    by_term = {}
    for term_key, url in pairs:
        by_term.setdefault(term_key, []).append(url)
    assert by_term["nails"] == ["https://i.pinimg.com/736x/a/1.jpg"]
    assert len(by_term["hair"]) == 2
    assert by_term["deep"] == ["https://i.pinimg.com/736x/d/4.jpg"]
    assert all("i.pinimg.com" in u for _, u in pairs)


def test_profile_dir_if_authed_skips_missing_and_logged_out(tmp_path, monkeypatch):
    """Missing dirs and session-less dirs are skipped, not minted into."""
    import app.services.pinterest_profiles as profiles
    import app.services.pinterest_trends_scraper as scraper

    monkeypatch.setattr(profiles, "get_profile_dir", lambda pid: tmp_path / "nope")
    assert scraper._profile_dir_if_authed("profile_2") is None

    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(profiles, "get_profile_dir", lambda pid: empty)
    assert scraper._profile_dir_if_authed("profile_2") is None

    authed = tmp_path / "authed"
    (authed / "Default").mkdir(parents=True)
    (authed / "Default" / "Cookies").write_bytes(b"x")
    monkeypatch.setattr(profiles, "get_profile_dir", lambda pid: authed)
    assert scraper._profile_dir_if_authed("profile_2") == authed


def test_timeline_labels_derive_from_window():
    """Date labels follow the real window end — never hardcoded months."""
    from datetime import date
    from app.services.pinterest_trends_scraper import _timeline_labels

    assert _timeline_labels(date(2026, 9, 9)) == ["Dec 2025", "Mar 2026", "Jun 2026", "Sep 2026"]
    assert _timeline_labels(date(2026, 1, 15)) == ["Apr 2025", "Jul 2025", "Oct 2025", "Jan 2026"]


def test_clean_popular_pins_never_pads_and_stable_ids():
    """Only real images returned (no stock padding); ids stable across runs."""
    from app.services.pinterest_trends_scraper import _clean_popular_pins

    raw = [
        {"image_url": "https://i.pinimg.com/736x/aa/one.jpg", "title": "", "_source": "trends_term_images"},
        {"image_url": "https://i.pinimg.com/736x/bb/two.jpg", "title": "Linen Blazer Street Look", "_source": "search_dom"},
        {"image_url": "https://i.pinimg.com/736x/cc/one.jpg", "title": "dupe basename", "_source": "search_dom"},
        {"image_url": "", "title": "no image"},
    ]
    once = _clean_popular_pins([dict(p) for p in raw], clean_term="la place", encoded_term="la+place", count=8)
    twice = _clean_popular_pins([dict(p) for p in raw], clean_term="la place", encoded_term="la+place", count=8)
    # 2 real unique images — NOT padded up to count=8
    assert len(once) == 2
    assert all("unsplash.com" not in p["image_url"] for p in once)
    assert all("Pinterest Trends Gallery" != p["source"] for p in once)
    assert [p["pin_id"] for p in once] == [p["pin_id"] for p in twice]
    assert len({p["pin_id"] for p in once}) == 2
    assert all(p["visual_hook"] and len(p["title"]) > 3 for p in once)
    # Junk titles get term-derived replacements, real titles kept
    assert once[1]["title"] == "Linen Blazer Street Look"

    assert _clean_popular_pins([], clean_term="la place", encoded_term="la+place", count=8) == []

    # UI-chrome vectors are not pin photos, even on pinimg hosts.
    svg_only = _clean_popular_pins(
        [{"image_url": "https://i.pinimg.com/incl-prod/default_skintone.svg", "title": "x"}],
        clean_term="la place", encoded_term="la+place", count=8,
    )
    assert svg_only == []


@pytest.mark.asyncio
async def test_deep_dive_metric_provenance(tmp_path, monkeypatch):
    """No metrics → nulls + 'unavailable' (never invented numbers); live passes through."""
    import app.services.pinterest_trends_scraper as scraper
    from app.config import settings

    monkeypatch.setattr(settings, "storage_path", str(tmp_path))

    async def _no_pins(*args, **kwargs):
        return []

    monkeypatch.setattr(scraper, "scrape_popular_pins_for_term", _no_pins)

    async def _none(*args, **kwargs):
        return None

    monkeypatch.setattr(scraper, "scrape_custom_pinterest_trend_metrics", _none)
    missing = await scraper.get_trend_deep_dive("some obscure term xyz", country="US", force_refresh=True)
    assert missing["metric_provenance"] == "unavailable"
    assert missing["mom_change"] is None
    assert missing["wow_change"] is None
    assert missing["search_count"] is None
    assert missing["sparkline"] == []
    assert missing["timeline_dates"] == []
    assert missing["indexing_window"] is None
    assert missing["popular_pins"] == []
    assert len(missing["related_searches"]) > 0
    assert missing["related_searches_provenance"] == "generated"

    async def _live(term, country="US"):
        return {"term": term, "category": "fashion", "mom_change": 10.0,
                "wow_change": 2.0, "yoy_change": None, "search_count": 40,
                "sparkline": [5, 10, 20, 40],
                "timeline_dates": ["Dec 2025", "Mar 2026", "Jun 2026", "Sep 2026"],
                "indexing_window": {"advice": "x", "urgency": "high", "badge": "b", "phase": "rising"},
                "recommended_board": "B", "monetization_angle": "M"}

    monkeypatch.setattr(scraper, "scrape_custom_pinterest_trend_metrics", _live)
    live = await scraper.get_trend_deep_dive("another term xyz", country="US", force_refresh=True)
    assert live["metric_provenance"] == "live"
    assert live["sparkline"] == [5, 10, 20, 40]
    assert live["timeline_dates"] == ["Dec 2025", "Mar 2026", "Jun 2026", "Sep 2026"]
    assert live["indexing_window"]["badge"] == "b"


@pytest.mark.asyncio
async def test_launch_inspo_campaign_creates_job_and_product(tmp_path):
    """Verify launch_inspo_campaign creates a DRAFT job with blog URL and editorial product."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from app.models.models import Base, Reference, Job, Product
    from app.api.research import LaunchInspoCampaignRequest, launch_inspo_campaign

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/inspo_test.db")
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as db:
        # Seed an aesthetic reference
        ref = Reference(
            id="ref_inspo_1",
            image_path="ref_test.jpg",
            trend_label="fall nails",
            category="beauty",
            status="analyzed",
        )
        db.add(ref)
        await db.commit()

        req = LaunchInspoCampaignRequest(
            term="fall nail colors 2026",
            category="beauty",
            board_name="Fall Nails 2026 Inspo",
        )
        res = await launch_inspo_campaign(req, db)
        assert res["status"] == "success"
        assert res["job_id"]
        assert res["product_id"]

        # Verify product created
        prod = await db.get(Product, res["product_id"])
        assert prod is not None
        assert "Fall Nail Colors 2026" in prod.name
        assert "pinterest-lookbooks" in prod.affiliate_url

        # Verify job created in DRAFT state
        job = await db.get(Job, res["job_id"])
        assert job is not None
        assert job.current_state == "DRAFT"
        assert job.reference_id == "ref_inspo_1"


def test_get_commonly_searched_queries():
    """Verify keyword expansion matches screenshot patterns (blazers, nails, etc.)."""
    from app.services.pinterest_trends_scraper import get_commonly_searched_queries

    blazer_tags = get_commonly_searched_queries("casual blazer outfits", category="fashion")
    assert len(blazer_tags) >= 8
    assert "oversized blazer outfit" in blazer_tags
    assert "black blazer outfit" in blazer_tags

    nail_tags = get_commonly_searched_queries("september nails ideas 2026", category="beauty")
    assert len(nail_tags) >= 8
    assert any("fall nails" in tag for tag in nail_tags)


@pytest.mark.asyncio
async def test_get_trend_deep_dive(tmp_path, monkeypatch):
    """Hermetic deep-dive: honest shape with live metric + real pins, no fabrication."""
    import app.services.pinterest_trends_scraper as scraper
    from app.config import settings

    monkeypatch.setattr(settings, "storage_path", str(tmp_path))

    async def _live_metric(term, country="US"):
        return {"term": term, "category": "fashion", "mom_change": 120.0,
                "wow_change": 15.0, "yoy_change": None, "search_count": 88,
                "sparkline": [10, 20, 40, 88],
                "timeline_dates": ["Dec 2025", "Mar 2026", "Jun 2026", "Sep 2026"],
                "indexing_window": {"advice": "Pin NOW", "urgency": "high", "badge": "Prime Early Window", "phase": "rising"},
                "recommended_board": "Blazer Inspo", "monetization_angle": "M"}

    async def _pins(*args, **kwargs):
        return [{
            "pin_id": "123",
            "title": "Real pin",
            "visual_hook": "HOOK",
            "overlay_text": "HOOK",
            "image_url": "https://i.pinimg.com/736x/ab/real.jpg",
            "pin_url": "https://www.pinterest.com/pin/123/",
            "source": "Pinterest Live Search",
        }]

    monkeypatch.setattr(scraper, "scrape_custom_pinterest_trend_metrics", _live_metric)
    monkeypatch.setattr(scraper, "scrape_popular_pins_for_term", _pins)

    data = await scraper.get_trend_deep_dive("casual blazer outfits", country="US", force_refresh=True)
    assert data["term"] == "casual blazer outfits"
    assert data["metric_provenance"] == "live"
    assert len(data["related_searches"]) > 0
    assert data["related_searches_provenance"] == "generated"
    assert len(data["popular_pins"]) == 1
    assert data["sparkline"] == [10, 20, 40, 88]
    assert data["timeline_dates"] == ["Dec 2025", "Mar 2026", "Jun 2026", "Sep 2026"]
    assert data["indexing_window"]["badge"] == "Prime Early Window"

    # Check pin fields
    pin = data["popular_pins"][0]
    assert "pin_id" in pin
    assert "image_url" in pin
    assert "pin_url" in pin
    assert "visual_hook" in pin


@pytest.mark.asyncio
async def test_import_pin_reference_endpoint(tmp_path, monkeypatch):
    """Verify 1-click import of a popular pin creates a Reference with Visual DNA."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from app.models.models import Base, Reference, VisualDNA
    from app.api.research import ImportPinReferenceRequest, import_pin_reference
    from app.config import settings
    monkeypatch.setattr(settings, "storage_path", str(tmp_path))

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/pin_ref_test.db")
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Mock httpx download of image
    import httpx

    class MockStreamResponse:
        status_code = 200
        headers = {"content-type": "image/jpeg"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def aiter_bytes(self, chunk_size=65536):
            yield b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00"

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def stream(self, method, url, **kwargs):
            return MockStreamResponse()

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    # Mock analyze_reference to avoid remote LLM timeout
    async def mock_analyze(path):
        return {
            "subject": {"primary_category": "fashion"},
            "scene": {"scene_type": "street_style"},
            "lighting": {"source": "natural_window"},
            "composition": {"framing": "medium"},
            "materials": {"primary_textures": ["linen"]},
            "ugc_signals": {"casual_authenticity": "high"},
            "psychology": {"aspirational_score": 8},
            "product_facts": ["Oversized neutral blazer"],
        }

    import app.pipeline.reference_analyst
    monkeypatch.setattr(app.pipeline.reference_analyst, "analyze_reference", mock_analyze)

    async with async_session() as db:
        req = ImportPinReferenceRequest(
            image_url="https://i.pinimg.com/236x/2c/3e/ab/2c3eab366cfcbdfcb49cfb6cf9dbfbb5.jpg",
            pin_title="Oversized Linen Blazer Look",
            trend_label="casual blazer outfits",
            category="fashion",
            source_pin_url="https://www.pinterest.com/pin/123456789/",
        )
        res = await import_pin_reference(req, db)
        assert res["status"] == "success"
        assert res["reference_id"]
        assert res["has_visual_dna"] is True

        # Verify reference created in DB
        ref = await db.get(Reference, res["reference_id"])
        assert ref is not None
        assert ref.trend_label == "casual blazer outfits"
        assert ref.status == "analyzed"


def test_scrape_popular_pins_distinct_images_and_hooks():
    """Hermetic pin cleaning: unique real images, hooks, no stock padding.

    (Previously live-scraped 'la place' and passed via Unsplash padding —
    the padding it relied on no longer exists, so this now tests the
    pure cleaning step directly.)
    """
    from app.services.pinterest_trends_scraper import _clean_popular_pins

    raw = [
        {"image_url": f"https://i.pinimg.com/736x/{c}/p{i}.jpg", "title": "", "_source": "trends_term_images"}
        for i, c in enumerate(["aa", "bb", "cc", "dd", "ee", "ff"])
    ]
    pins = _clean_popular_pins(raw, clean_term="la place", encoded_term="la+place", count=8)
    assert len(pins) == 6

    images = [p["image_url"] for p in pins]
    # No duplicate image URLs
    assert len(set(images)) == len(images), "Images must be 100% distinct, no repeated placeholders"

    # No stock-photo padding, no fake gallery source
    assert not any("unsplash.com" in img for img in images)
    assert not any("1500000000000" in img for img in images)
    assert all(p["source"] in ("Pinterest Trends (Official)", "Pinterest Live Search") for p in pins)

    # Every pin must have visual hook and non-empty title
    for p in pins:
        assert p.get("title") and len(p["title"]) > 3
        assert p.get("visual_hook")



