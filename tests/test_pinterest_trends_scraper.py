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
async def test_get_trend_deep_dive():
    """Verify deep-dive structure has popular_pins, commonly_searched_for, and 0-100 metrics."""
    from app.services.pinterest_trends_scraper import get_trend_deep_dive

    data = await get_trend_deep_dive("casual blazer outfits", country="US", force_refresh=False)
    assert data["term"] == "casual blazer outfits"
    assert "commonly_searched_for" in data
    assert len(data["commonly_searched_for"]) > 0
    assert "popular_pins" in data
    assert len(data["popular_pins"]) > 0
    assert "sparkline" in data
    assert "timeline_dates" in data
    assert "indexing_window" in data

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


@pytest.mark.asyncio
async def test_scrape_popular_pins_distinct_images_and_hooks():
    """Verify popular pins for any custom term return unique images, distinct titles, and punchy hooks."""
    from app.services.pinterest_trends_scraper import scrape_popular_pins_for_term

    pins = await scrape_popular_pins_for_term("la place", count=8)
    assert len(pins) >= 4

    images = [p["image_url"] for p in pins]
    # No duplicate image URLs
    assert len(set(images)) == len(images), "Images must be 100% distinct, no repeated placeholders"

    # No broken URLs with 1500000000000
    assert not any("1500000000000" in img for img in images)

    # Every pin must have visual hook and non-empty title
    for p in pins:
        assert p.get("title") and len(p["title"]) > 3
        assert p.get("visual_hook")
        assert "Aesthetic Inspo Look #" not in p["title"] or len(set(p["title"] for p in pins)) == len(pins)



