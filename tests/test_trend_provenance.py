"""
Blanket provenance contract tests — the CI truth guard.

Rule: any trend payload carrying curated/synthetic data WITHOUT its
provenance flag fails here. Per-path behavior tests live with their
features; this module asserts the contract itself, so a NEW surface (or a
regression that drops a flag) goes red even if nobody wrote a test for it.
"""
from __future__ import annotations

import pytest

from app.services import trend_provenance as pv
from app.services import trend_research as tr


def _demo() -> frozenset:
    return tr.DEMO_ASINS


def _live_item(**kw):
    base = {
        "term": "real trend", "category": "fashion", "intent": "viral_blog",
        "mom_change": 42.0, "wow_change": 5.0, "search_count": 60,
        "sparkline": [3, 9, 30, 60], "timeline_dates": ["Jun 2026"],
        "preview_images": ["https://i.pinimg.com/736x/ab/cd.jpg"],
        "provenance": "live", "is_fallback": False,
    }
    base.update(kw)
    return base


def _live_pin(**kw):
    base = {
        "pin_id": "123", "title": "Real", "visual_hook": "H",
        "image_url": "https://i.pinimg.com/736x/ab/real.jpg",
        "pin_url": "https://www.pinterest.com/pin/123/",
        "source": "Pinterest Live Search",
    }
    base.update(kw)
    return base


def _live_product(**kw):
    base = {"asin": "B012345678", "title": "Live", "price": 49.99,
            "rating": 4.5, "review_count": 100,
            "image_url": "https://example.com/i.jpg",
            "affiliate_url": "https://amzn.to/x", "demo_only": False}
    base.update(kw)
    return base


def _dossier(**kw):
    base = {
        "id": "d1", "origin": "curated_seed", "heat_badge": "📈 Trending",
        "score_breakdown": {
            "demand": 60.0, "money": 50.0, "winnability": 46.0,
            "weights_version": 1,
            "demand_source": "autocomplete_breadth_proxy",
            "money_source": "neutral_no_data",
            "winnability_source": "angle_breadth_proxy",
        },
        "matched_products": [_live_product()],
    }
    base.update(kw)
    return base


def _deep_dive(**kw):
    base = {
        "term": "t", "metric_provenance": "live",
        "mom_change": 10.0, "wow_change": 2.0, "yoy_change": None,
        "search_count": 40, "sparkline": [5, 10, 20, 40],
        "timeline_dates": ["Sep 2026"],
        "indexing_window": {"advice": "x"},
        "related_searches": ["t ideas"], "related_searches_provenance": "generated",
        "popular_pins": [_live_pin()],
    }
    base.update(kw)
    return base


# ── Official items: labeled shapes pass ──────────────────────────────

def test_official_live_and_labeled_fallback_pass():
    assert pv.check_official_item(_live_item()) == []
    fb = _live_item(provenance="curated_fallback", is_fallback=True,
                    mom_change=3000.0, sparkline=[1, 3, 7, 15, 31, 62, 100],
                    preview_images=["https://images.unsplash.com/photo-1?w=500"])
    assert pv.check_official_item(fb) == []


def test_official_unlabeled_synthetic_fails():
    # Legacy v1 shape: no flags at all.
    assert pv.check_official_item({"term": "x", "mom_change": 3000.0}) != []
    # Stock photo without fallback flag.
    assert pv.check_official_item(_live_item(
        provenance="live", is_fallback=False,
        preview_images=["https://images.unsplash.com/photo-1?w=500"])) != []
    # Known placeholder sparkline without fallback flag.
    assert pv.check_official_item(_live_item(
        sparkline=[10, 20, 35, 50, 75, 100])) != []
    # Unknown provenance value.
    assert pv.check_official_item(_live_item(provenance="mystery")) != []


def test_official_response_envelope_and_consistency():
    good = {"success": True, "source": "trends.pinterest.com",
            "is_fallback": False, "trends": [_live_item()]}
    assert pv.check_official_list_response(good) == []
    good_fb = {"success": True, "source": "curated_fallback",
               "is_fallback": True, "trends": []}
    assert pv.check_official_list_response(good_fb) == []
    # Lie in either direction fails.
    assert pv.check_official_list_response({**good, "source": "curated_fallback"}) != []
    assert pv.check_official_list_response({**good_fb, "source": "trends.pinterest.com"}) != []
    # Missing flags fail.
    assert pv.check_official_list_response({"success": True, "trends": []}) != []
    # Bad item inside a good envelope fails.
    assert pv.check_official_list_response(
        {**good, "trends": [{"term": "x"}]}) != []


# ── Dossiers ─────────────────────────────────────────────────────────

def test_dossier_contract_passes():
    assert pv.check_dossier(_dossier(), _demo()) == []


def test_dossier_violations_fail():
    assert pv.check_dossier({**_dossier(), "origin": "mystery"}, _demo()) != []
    assert pv.check_dossier({k: v for k, v in _dossier().items() if k != "origin"}, _demo()) != []
    assert pv.check_dossier(_dossier(heat_badge="🔥 Breakout (+420% Surge)"), _demo()) != []
    bd = dict(_dossier()["score_breakdown"])
    del bd["money_source"]
    assert pv.check_dossier(_dossier(score_breakdown=bd), _demo()) != []
    bd2 = dict(_dossier()["score_breakdown"], demand_source="measured!!!")
    assert pv.check_dossier(_dossier(score_breakdown=bd2), _demo()) != []
    assert pv.check_dossier(_dossier(matched_products=[{"asin": "B0EVIL01"}]), _demo()) != []


# ── Pins & products ──────────────────────────────────────────────────

def test_pin_contract():
    assert pv.check_pin(_live_pin()) == []
    # Unsplash stock, wrong source, non-pinimg URL all fail.
    assert pv.check_pin(_live_pin(
        image_url="https://images.unsplash.com/photo-1?w=736",
        source="Pinterest Trends Gallery")) != []
    assert pv.check_pin(_live_pin(source="Pinterest Popular Pins")) != []
    assert pv.check_pin({"pin_id": "x"}) != []


def test_product_contract_and_registry_drift():
    assert pv.check_product(_live_product(), _demo()) == []
    demo = _live_product(asin="B0SEARCH01", demo_only=True)
    assert pv.check_product(demo, _demo()) == []
    # Unregistered demo ASIN = ingestible = fail (catches registry drift).
    assert pv.check_product(_live_product(asin="B0EVIL01", demo_only=True), _demo()) != []
    # Missing flag fails even for live-looking rows.
    assert pv.check_product(
        {k: v for k, v in _live_product().items() if k != "demo_only"}, _demo()) != []


# ── Deep dives ───────────────────────────────────────────────────────

def test_deep_dive_live_passes():
    assert pv.check_deep_dive(_deep_dive(), _demo()) == []


def test_deep_dive_unavailable_shape_passes():
    missing = _deep_dive(
        metric_provenance="unavailable", mom_change=None, wow_change=None,
        search_count=None, sparkline=[], timeline_dates=[], indexing_window=None,
        popular_pins=[],
    )
    assert pv.check_deep_dive(missing, _demo()) == []


def test_deep_dive_violations_fail():
    # Unavailable carrying numbers (the old estimated-fallback shape).
    assert pv.check_deep_dive(_deep_dive(
        metric_provenance="unavailable", mom_change=3000.0,
        sparkline=[5, 8, 12, 22, 45, 80, 100]), _demo()) != []
    # Unknown provenance.
    assert pv.check_deep_dive(_deep_dive(metric_provenance="estimated"), _demo()) != []
    # Keywords without the generated label.
    bad_kw = _deep_dive(related_searches_provenance="official")
    assert pv.check_deep_dive(bad_kw, _demo()) != []
    no_kw = {k: v for k, v in _deep_dive().items() if k != "related_searches_provenance"}
    assert pv.check_deep_dive(no_kw, _demo()) != []
    # Fake pin smuggled into the gallery.
    bad_pins = _deep_dive(popular_pins=[_live_pin(
        image_url="https://images.unsplash.com/photo-1?w=736",
        source="Pinterest Trends Gallery")])
    assert pv.check_deep_dive(bad_pins, _demo()) != []


def test_detail_response_envelope():
    assert pv.check_detail_response({"success": True, "data": _deep_dive()}, _demo()) == []
    assert pv.check_detail_response({"success": True}, _demo()) != []
    assert pv.check_detail_response("nope", _demo()) != []


# ── End-to-end: dead backend must still validate clean ───────────────

@pytest.mark.asyncio
async def test_dead_backend_validates_clean(tmp_path, monkeypatch):
    """Every surface, fully failed over, through the contract: zero violations."""
    import datetime as _dt
    from app.config import settings
    import app.services.pinterest_trends_scraper as scraper
    from app.services.trend_sources import SourceSignal

    monkeypatch.setattr(settings, "storage_path", str(tmp_path))

    async def _empty(*args, **kwargs):
        return []

    async def _none(*args, **kwargs):
        return None

    async def _fake_scan(seed_query, category):
        return [SourceSignal(
            source="shopping", status="fresh", queries=[seed_query],
            demand_hint=50.0,
            fetched_at=_dt.datetime.now(_dt.timezone.utc).isoformat())]

    async def _no_match(*args, **kwargs):
        return []

    monkeypatch.setattr(scraper, "scrape_pinterest_trends_playwright", _empty)
    monkeypatch.setattr(scraper, "scrape_popular_pins_for_term", _empty)
    monkeypatch.setattr(scraper, "scrape_custom_pinterest_trend_metrics", _none)
    monkeypatch.setattr(tr, "_scan_seed_signals", _fake_scan)
    monkeypatch.setattr(tr, "match_amazon_products_for_trend", _no_match)
    monkeypatch.setattr(tr, "_write_snapshot", lambda *a, **k: None)

    official = await scraper.get_official_pinterest_trends(preset="breakout", force_refresh=True)
    assert official, "fallback must still serve"
    for t in official:
        assert pv.check_official_item(t) == []

    dive = await scraper.get_trend_deep_dive("dead term xyz", country="US", force_refresh=True)
    assert pv.check_deep_dive(dive, _demo()) == []

    dossiers = await tr.discover_trends_radar(include_pinterest=True)
    assert dossiers, "seeds-only must still serve"
    for d in dossiers:
        assert pv.check_dossier(d, _demo()) == [], d.get("id")


@pytest.mark.asyncio
async def test_live_backend_validates_clean(tmp_path, monkeypatch):
    """Labeled live shapes through the contract: zero violations."""
    import app.services.pinterest_trends_scraper as scraper
    from app.config import settings

    monkeypatch.setattr(settings, "storage_path", str(tmp_path))

    async def _live_scrape(**kwargs):
        return [{"term": "real trend", "category": "fashion", "intent": "viral_blog",
                 "mom_change": 42.0, "wow_change": 5.0, "search_count": 60,
                 "sparkline": [3, 9, 30, 60]}]

    async def _live_pins(*args, **kwargs):
        return [_live_pin()]

    async def _live_metric(term, country="US"):
        return {"term": term, "category": "fashion", "mom_change": 42.0,
                "wow_change": 5.0, "search_count": 60, "sparkline": [3, 9, 30, 60],
                "timeline_dates": ["Sep 2026"],
                "indexing_window": {"advice": "x"},
                "recommended_board": "B", "monetization_angle": "M"}

    monkeypatch.setattr(scraper, "scrape_pinterest_trends_playwright", _live_scrape)
    monkeypatch.setattr(scraper, "scrape_popular_pins_for_term", _live_pins)
    monkeypatch.setattr(scraper, "scrape_custom_pinterest_trend_metrics", _live_metric)

    official = await scraper.get_official_pinterest_trends(preset="breakout", force_refresh=True)
    for t in official:
        assert pv.check_official_item(t) == []

    dive = await scraper.get_trend_deep_dive("real trend", country="US", force_refresh=True)
    assert pv.check_deep_dive(dive, _demo()) == []
