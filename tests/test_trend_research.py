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

    async def _no_pinterest(*args, **kwargs):
        return []

    with patch.object(tr, "_scan_seed_signals", new_callable=AsyncMock) as mock_scan, \
         patch.object(tr, "match_amazon_products_for_trend", new_callable=AsyncMock) as mock_match, \
         patch.object(tr, "_fetch_pinterest_discovery", new_callable=AsyncMock) as mock_pin, \
         patch.object(tr, "_write_snapshot", return_value=None):

        mock_scan.side_effect = _fake_scan
        mock_match.side_effect = _fake_match
        mock_pin.side_effect = _no_pinterest

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
async def test_custom_badge_has_no_fabricated_percentages(tmp_path):
    """Custom dossier badges must not invent growth percentages."""
    import datetime as _dt
    from app.services.trend_sources import SourceSignal

    async def _fake_scan(seed_query, category):
        return [SourceSignal(
            source="shopping", status="fresh",
            queries=[seed_query, f"{seed_query} aesthetic"],
            demand_hint=80.0,
            fetched_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
        )]

    with patch.object(tr, "_scan_seed_signals", new_callable=AsyncMock) as mock_scan, \
         patch.object(tr, "match_amazon_products_for_trend", new_callable=AsyncMock) as mock_match, \
         patch.object(tr, "_trend_cache_dir", return_value=tmp_path / "custom_cache"):
        mock_scan.side_effect = _fake_scan
        mock_match.return_value = []

        plain = await tr.analyze_custom_trend_query("japandi coffee bar", category="kitchen")
        assert "%" not in plain["heat_badge"]
        assert "180" not in plain["heat_badge"] and "350" not in plain["heat_badge"]

        seasonal = await tr.analyze_custom_trend_query("fall porch decor", category="home")
        assert "%" not in seasonal["heat_badge"]
        assert seasonal["heat_level"] == "breakout"
        assert plain["heat_level"] == "rising"


@pytest.mark.asyncio
async def test_build_pinterest_dossier_measured_demand():
    """Pinterest ingestion scores measured search_count and labels provenance."""
    import datetime as _dt
    from app.services.trend_sources import SourceSignal

    async def _fake_scan(seed_query, category):
        return [SourceSignal(
            source="shopping", status="fresh",
            queries=[seed_query, f"{seed_query} aesthetic"],
            demand_hint=70.0,
            fetched_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
        )]

    item = {
        "term": "chrome french tip nails",
        "category": "beauty",
        "mom_change": 420.0,
        "wow_change": 30.0,
        "search_count": 88,
        "sparkline": [4, 12, 40, 88],
        "timeline_dates": ["Dec 2025", "Mar 2026", "Jun 2026", "Sep 2026"],
        "recommended_board": "Chrome Nails",
        "provenance": "live",
        "is_fallback": False,
    }

    with patch.object(tr, "_scan_seed_signals", new_callable=AsyncMock) as mock_scan, \
         patch.object(tr, "match_amazon_products_for_trend", new_callable=AsyncMock) as mock_match:
        mock_scan.side_effect = _fake_scan
        mock_match.return_value = []

        d = await tr._build_pinterest_dossier(item)

    assert d is not None
    assert d["origin"] == "pinterest_live"
    assert d["category"] == "fashion"  # beauty maps to the fashion bucket
    assert d["pinterest_category"] == "beauty"
    # Measured demand 88, neutral money 50 (no live products), win 46 (2 angles):
    # 0.40*88 + 0.35*50 + 0.25*46 = 64.2 → 64 / Tier B
    assert d["opportunity_score"] == 64
    assert d["tier"] == "Tier B"
    assert d["score_breakdown"]["demand_source"] == "pinterest_measured"
    assert d["score_breakdown"]["money_source"] == "neutral_no_data"
    assert d["score_breakdown"]["winnability_source"] == "angle_breadth_proxy"
    assert "%" not in d["heat_badge"]
    assert d["keyword_pack"]["primary"] == "chrome french tip nails"
    assert d["mom_change"] == 420.0
    assert d["sparkline"] == [4, 12, 40, 88]
    assert d["provenance"] == "live"


@pytest.mark.asyncio
async def test_build_pinterest_dossier_proxy_when_unmeasured():
    """search_count None degrades honestly to the autocomplete proxy label."""
    import datetime as _dt
    from app.services.trend_sources import SourceSignal

    async def _fake_scan(seed_query, category):
        return [SourceSignal(
            source="shopping", status="fresh",
            queries=[seed_query],
            demand_hint=75.0,
            fetched_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
        )]

    item = {"term": "velvet ribbon decor", "category": "home", "mom_change": 20.0,
            "search_count": None, "is_fallback": False}

    with patch.object(tr, "_scan_seed_signals", new_callable=AsyncMock) as mock_scan, \
         patch.object(tr, "match_amazon_products_for_trend", new_callable=AsyncMock) as mock_match:
        mock_scan.side_effect = _fake_scan
        mock_match.return_value = []

        d = await tr._build_pinterest_dossier(item)

    assert d is not None
    assert d["score_breakdown"]["demand_source"] == "autocomplete_breadth_proxy"
    # Proxy demand 75, neutral money 50, win 38 (1 angle):
    # 0.40*75 + 0.35*50 + 0.25*38 = 57 / Tier B
    assert d["opportunity_score"] == 57
    assert await tr._build_pinterest_dossier({"term": "  "}) is None


@pytest.mark.asyncio
async def test_discover_includes_pinterest_and_sorts():
    """Full scan mixes measured Pinterest entries with seeds, sorted desc."""
    import datetime as _dt
    from app.services.trend_sources import SourceSignal

    async def _fake_scan(seed_query, category):
        return [SourceSignal(
            source="shopping", status="fresh",
            queries=[seed_query],
            demand_hint=10.0,
            fetched_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
        )]

    pin_items = [
        {"term": "hot measured trend", "category": "fashion", "mom_change": 900.0,
         "search_count": 100, "sparkline": [90, 100], "is_fallback": False},
    ]

    with patch.object(tr, "_scan_seed_signals", new_callable=AsyncMock) as mock_scan, \
         patch.object(tr, "match_amazon_products_for_trend", new_callable=AsyncMock) as mock_match, \
         patch.object(tr, "_fetch_pinterest_discovery", new_callable=AsyncMock) as mock_pin, \
         patch.object(tr, "_write_snapshot", return_value=None) as mock_snap:
        mock_scan.side_effect = _fake_scan
        mock_match.return_value = []
        mock_pin.return_value = pin_items

        dossiers = await tr.discover_trends_radar()

    origins = {d["origin"] for d in dossiers}
    assert "pinterest_live" in origins
    assert "curated_seed" in origins
    # Measured 100 (money 50 neutral, win 38) → 67 tops proxy seeds (10 → 31)
    assert dossiers[0]["id"] == "pin-trend-hot_measured_trend"
    scores = [d["opportunity_score"] for d in dossiers]
    assert scores == sorted(scores, reverse=True)
    assert mock_snap.called


@pytest.mark.asyncio
async def test_discover_pinterest_failsoft():
    """Broken discovery degrades to seeds-only — never raises, never demo data."""
    import datetime as _dt
    from app.services.trend_sources import SourceSignal

    async def _fake_scan(seed_query, category):
        return [SourceSignal(
            source="shopping", status="fresh",
            queries=[seed_query],
            demand_hint=50.0,
            fetched_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
        )]

    with patch.object(tr, "_scan_seed_signals", new_callable=AsyncMock) as mock_scan, \
         patch.object(tr, "match_amazon_products_for_trend", new_callable=AsyncMock) as mock_match, \
         patch.object(tr, "_fetch_pinterest_discovery", new_callable=AsyncMock) as mock_pin, \
         patch.object(tr, "_write_snapshot", return_value=None):
        mock_scan.side_effect = _fake_scan
        mock_match.return_value = []
        mock_pin.side_effect = RuntimeError("playwright exploded")

        dossiers = await tr.discover_trends_radar()

    assert len(dossiers) > 0
    assert all(d["origin"] == "curated_seed" for d in dossiers)


def test_snapshot_prunes_stale_pinterest(tmp_path, monkeypatch):
    """Full scans evict yesterday's Pinterest ids; seeds and filtered scans are safe."""
    import json
    from app.config import settings

    monkeypatch.setattr(settings, "storage_path", str(tmp_path))

    def _snap_file():
        files = list((tmp_path / "trend_radar").glob("*.json"))
        assert len(files) == 1
        return files[0]

    seed = {"id": "barn_jacket_heritage", "origin": "curated_seed", "opportunity_score": 40}
    stale = {"id": "pin-trend-old_news", "origin": "pinterest_live", "opportunity_score": 90}
    fresh = {"id": "pin-trend-today_thing", "origin": "pinterest_live", "opportunity_score": 70}

    tr._write_snapshot([seed, stale])
    snap_file = _snap_file()

    # Full scan without the stale id prunes it; seed retained.
    tr._write_snapshot([seed, fresh], prune_missing_origin="pinterest_live")
    payload = json.loads(snap_file.read_text(encoding="utf-8"))
    ids = {d["id"] for d in payload["dossiers"]}
    assert ids == {"barn_jacket_heritage", "pin-trend-today_thing"}

    # Without the prune flag (e.g. category scans) nothing is evicted.
    tr._write_snapshot([seed])
    payload = json.loads(snap_file.read_text(encoding="utf-8"))
    assert {d["id"] for d in payload["dossiers"]} == {"barn_jacket_heritage", "pin-trend-today_thing"}


def test_money_from_live_products_only():
    """Money blends rating + review volume; demo/empty inputs stay neutral."""
    money, source = tr._money_from_products([
        {"asin": "B1", "rating": 4.6, "review_count": 840, "demo_only": False},
        {"asin": "B2", "rating": 4.5, "review_count": 1250, "demo_only": False},
    ])
    assert source == "live_products"
    # rating 4.55/5 → 91.0; volume 20*log10(2091) ≈ 66.4 → (91+66.4)/2 ≈ 78.7
    assert money == pytest.approx(78.7, abs=0.2)
    assert 0 <= money <= 100

    # Demo placeholders must not move the needle.
    money_demo, source_demo = tr._money_from_products([
        {"asin": "B0DEMO", "rating": 5.0, "review_count": 999999, "demo_only": True},
    ])
    assert (money_demo, source_demo) == (50.0, "neutral_no_data")
    assert tr._money_from_products([]) == (50.0, "neutral_no_data")
    assert tr._money_from_products(None) == (50.0, "neutral_no_data")


def test_winnability_scales_with_angles():
    """More distinct angles → higher winnability; never a silent constant."""
    assert tr._winnability_from_angles([]) == 30.0
    assert tr._winnability_from_angles(None) == 30.0
    assert tr._winnability_from_angles(["a", "b"]) == 46.0
    assert tr._winnability_from_angles([f"q{i}" for i in range(8)]) == 94.0


def test_blend_carries_sources():
    """Blend output labels every input — Tier S must be reachable now."""
    import datetime as _dt
    from app.services.trend_sources import SourceSignal

    signals = [SourceSignal(
        source="shopping", status="fresh", queries=["x", "y"],
        demand_hint=100.0, fetched_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
    )]
    products = [{"rating": 5.0, "review_count": 100000, "demo_only": False}]
    blended = tr._blend_signals(signals, products=products, related=[f"q{i}" for i in range(8)])
    assert blended["money_source"] == "live_products"
    assert blended["winnability_source"] == "angle_breadth_proxy"
    assert blended["money"] > 50.0
    assert blended["winnability"] == 94.0

    from app.services.trend_scorer import score_trend
    top = score_trend(100.0, blended["money"], blended["winnability"])
    assert top["tier"] == "S"


def test_select_snapshot_dossiers():
    """Version, weights, age and category gates all force rescan on mismatch."""
    fp = tr._current_weights_fingerprint()
    payload = {
        "snapshot_version": tr.SNAPSHOT_VERSION,
        "weights_fingerprint": fp,
        "dossiers": [
            {"id": "a", "category": "fashion", "opportunity_score": 90},
            {"id": "b", "category": "home", "opportunity_score": 80},
        ],
    }
    all_rows = tr.select_snapshot_dossiers(payload, "all", scanned_at_s=1000.0, now_s=2000.0)
    assert [d["id"] for d in all_rows] == ["a", "b"]
    fashion = tr.select_snapshot_dossiers(payload, "fashion", scanned_at_s=1000.0, now_s=2000.0)
    assert [d["id"] for d in fashion] == ["a"]
    assert tr.select_snapshot_dossiers(payload, "tech", scanned_at_s=1000.0, now_s=2000.0) is None
    assert tr.select_snapshot_dossiers(payload, "all", scanned_at_s=1000.0, now_s=5000.0) is None
    assert tr.select_snapshot_dossiers({**payload, "snapshot_version": 1}, "all",
                                       scanned_at_s=1000.0, now_s=2000.0) is None
    assert tr.select_snapshot_dossiers({**payload, "weights_fingerprint": "deadbeef"}, "all",
                                       scanned_at_s=1000.0, now_s=2000.0) is None
    assert tr.select_snapshot_dossiers(None, "all") is None


@pytest.mark.asyncio
async def test_custom_cache_key_tracks_weights(tmp_path, monkeypatch):
    """Weight changes write a different custom-cache file (no stale scores)."""
    import datetime as _dt
    from app.config import settings
    from app.services.trend_sources import SourceSignal

    async def _fake_scan(seed_query, category):
        return [SourceSignal(
            source="shopping", status="fresh", queries=[seed_query],
            demand_hint=70.0, fetched_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
        )]

    monkeypatch.setattr(settings, "storage_path", str(tmp_path))
    with patch.object(tr, "_scan_seed_signals", new_callable=AsyncMock) as mock_scan, \
         patch.object(tr, "match_amazon_products_for_trend", new_callable=AsyncMock) as mock_match:
        mock_scan.side_effect = _fake_scan
        mock_match.return_value = []

        await tr.analyze_custom_trend_query("keyed query", category="fashion", refresh=True)
        files_v1 = list((tmp_path / "trend_radar" / "custom_cache").glob("*.json"))
        assert len(files_v1) == 1

        monkeypatch.setattr(settings, "trend_weight_demand", 0.90)
        await tr.analyze_custom_trend_query("keyed query", category="fashion", refresh=True)
        files_v2 = list((tmp_path / "trend_radar" / "custom_cache").glob("*.json"))
        assert len(files_v2) == 2


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
