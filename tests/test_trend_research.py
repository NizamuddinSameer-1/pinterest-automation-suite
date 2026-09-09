"""
Unit and integration tests for Trend Research System.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import httpx
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import Job, Product, Reference
from app.services import trend_research as tr
from app.api.research import LaunchTrendCampaignRequest, launch_campaign_from_trend


@pytest.mark.asyncio
async def test_fetch_shopping_suggestions_parsing():
    """Verify Google Shopping suggestion payload parsing."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        "knit cardigan",
        ["knit cardigan fall", "knit cardigan outfit", "knit cardigan aesthetic"],
    ]

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        results = await tr.fetch_shopping_suggestions("knit cardigan", max_results=3)

        assert len(results) == 3
        assert "knit cardigan fall" in results
        assert "knit cardigan outfit" in results


@pytest.mark.asyncio
async def test_fetch_shopping_suggestions_fallback_on_error():
    """Verify graceful fallback when network fails."""
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.RequestError("Network error")
        results = await tr.fetch_shopping_suggestions("linen dress")

        assert results == []


@pytest.mark.asyncio
async def test_match_amazon_products_for_trend():
    """Verify Amazon PA-API product matching."""
    mock_item = {
        "asin": "B08TEST123",
        "title": "Oversized Cable Knit Cardigan Sweater",
        "price": 34.99,
        "image_url": "https://m.media-amazon.com/images/I/71test.jpg",
        "rating": 4.6,
        "review_count": 1200,
    }

    with patch("app.services.amazon_paapi.paapi_client.search_items", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = [mock_item]
        products = await tr.match_amazon_products_for_trend("knit cardigan", category="fashion", item_count=2)

        assert len(products) >= 1
        prod = products[0]
        assert prod["asin"] == "B08TEST123"
        assert prod["price"] == 34.99
        assert prod["rating"] == 4.6
        assert "B08TEST123" in prod["affiliate_url"]


@pytest.mark.asyncio
async def test_discover_trends_radar():
    """Verify trend radar discovery and category filtering (fully hermetic, no network)."""
    import datetime as _dt
    from app.services.trend_sources import SourceSignal

    async def _fake_scan(seed_query, category):
        return [SourceSignal(
            source="shopping", status="fresh",
            queries=[seed_query, f"{seed_query} aesthetic"],
            demand_hint=75.0,
            fetched_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
        )]

    async def _fake_match(query, category, fallback_items=None, item_count=2):
        return []

    with patch.object(tr, "_scan_seed_signals", new_callable=AsyncMock) as mock_scan, \
         patch.object(tr, "match_amazon_products_for_trend", new_callable=AsyncMock) as mock_match, \
         patch.object(tr, "_write_snapshot", return_value=None):

        mock_scan.side_effect = _fake_scan
        mock_match.side_effect = _fake_match

        fashion_dossiers = await tr.discover_trends_radar(category_filter="fashion")
        assert len(fashion_dossiers) > 0
        for d in fashion_dossiers:
            assert d["category"] == "fashion"
            assert "title" in d
            assert "matched_products" in d
            assert isinstance(d["matched_products"], list)


@pytest.mark.asyncio
async def test_analyze_custom_trend_query(tmp_path):
    """Verify custom query deep scan produces complete dossier."""
    import datetime as _dt
    from app.services.trend_sources import SourceSignal

    async def _fake_scan(seed_query, category):
        return [SourceSignal(
            source="shopping", status="fresh",
            queries=["ceramic pour over stand", "japandi coffee bar aesthetic"],
            demand_hint=90.0,
            fetched_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
        )]

    with patch.object(tr, "_scan_seed_signals", new_callable=AsyncMock) as mock_scan, \
         patch.object(tr, "match_amazon_products_for_trend", new_callable=AsyncMock) as mock_match, \
         patch.object(tr, "_trend_cache_dir", return_value=tmp_path / "custom_cache"):

        mock_scan.side_effect = _fake_scan
        mock_match.return_value = [{
            "asin": "B09COFFEE1",
            "title": "Minimalist Ceramic Pour Over Stand",
            "price": 38.00,
            "image_url": "https://m.media-amazon.com/images/I/coffee.jpg",
            "affiliate_url": "https://amazon.com/dp/B09COFFEE1?tag=test-20",
            "rating": 4.8,
            "review_count": 150,
        }]

        dossier = await tr.analyze_custom_trend_query("japandi coffee bar", category="kitchen")
        assert dossier["title"] == "Japandi Coffee Bar"
        # Computed score only (hardcoded 87/92 floor removed in Task 7):
        # 0.40*90 + 0.35*50 + 0.25*50 = 66. Ceiling is 70 while
        # money/winnability stay heuristic at 50.
        assert dossier["opportunity_score"] >= 60
        assert dossier["category"] == "kitchen"
        assert len(dossier["related_queries"]) > 0
        assert len(dossier["matched_products"]) > 0
        assert "recommended_board" in dossier


@pytest.mark.asyncio
async def test_launch_campaign_creates_records(tmp_path):
    """Test campaign launch creating Product and Job against a real Reference.

    Launch requires a reference library (fail-loud 409 otherwise), so seed one
    with a matching trend_label first — no placeholder pixels allowed.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    req = LaunchTrendCampaignRequest(
        asin="B09TESTASI",
        title="Retro Floral Maxi Dress",
        price=42.50,
        category="fashion",
        trend_label="Vintage Summer Outfits",
        scene_setting="Vintage sun-drenched afternoon in a wildflower field",
        board_name="Vintage Summer Outfits",
    )

    async with async_session() as session:
        session.add(Reference(
            id="ref-launch-test",
            image_path="test_ref.jpg",
            trend_label="Vintage Summer Outfits",
            category="fashion",
            status="analyzed",
        ))
        await session.commit()

        res = await launch_campaign_from_trend(req, db=session)
        assert res["status"] == "success"
        job_id = res["job_id"]
        prod_id = res["product_id"]

        # Check job in DB
        job = await session.get(Job, job_id)
        assert job is not None
        assert job.current_state == "DRAFT"
        assert job.reference_id == "ref-launch-test"
        scene_data = json.loads(job.scene_json)
        assert "Vintage sun-drenched" in scene_data["setting"]
        assert job.product_id == prod_id

        # Check product in DB
        prod = await session.get(Product, prod_id)
        assert prod is not None
        assert prod.name == "Retro Floral Maxi Dress"
        assert prod.price == 42.50
        assert prod.category == "Fashion"

    await engine.dispose()
