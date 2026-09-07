"""
Regression guards for Trend Radar launch integrity.

Locks in:
1. Curated fallback products are flagged demo_only (never presented as live listings).
2. launch-campaign refuses demo ASINs with 400 and creates nothing.
3. launch-campaign fails loud with 409 (no orphan Product) when no reference exists.
"""

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.api.research import LaunchTrendCampaignRequest, launch_campaign_from_trend
from app.models.models import Base, Job, Product
from app.services import trend_research as tr


def _demo_asin() -> str:
    return sorted(tr.DEMO_ASINS)[0]


def test_demo_asins_registry_covers_all_fallbacks():
    """Every fallback ASIN in TREND_SEEDS must be in the DEMO_ASINS blocklist."""
    assert len(tr.DEMO_ASINS) > 0
    for seeds in tr.TREND_SEEDS.values():
        for seed in seeds:
            for item in seed.get("fallback_products") or []:
                assert str(item["asin"]).upper() in tr.DEMO_ASINS


@pytest.mark.asyncio
async def test_fallback_matcher_tags_demo_only(monkeypatch):
    """PA-API outage path: fallbacks come back flagged demo_only; live path is False."""

    class _FailingPaapi:
        async def search_items(self, **kwargs):
            raise RuntimeError("offline")

    monkeypatch.setattr(tr, "paapi_client", _FailingPaapi())
    results = await tr.match_amazon_products_for_trend(
        query="barn jacket",
        category="fashion",
        fallback_items=[{"asin": "B0DG12BARN", "title": "Demo Jacket"}],
        item_count=2,
    )
    assert results, "expected fallback results when PA-API is down"
    assert all(r.get("demo_only") is True for r in results)

    class _LivePaapi:
        async def search_items(self, **kwargs):
            return [{
                "asin": "B012345678",
                "title": "Live Jacket",
                "price": 49.99,
                "image_url": "https://example.com/img.jpg",
                "rating": 4.5,
                "review_count": 100,
                "affiliate_url": "https://amzn.to/live",
            }]

    monkeypatch.setattr(tr, "paapi_client", _LivePaapi())
    live = await tr.match_amazon_products_for_trend(
        query="barn jacket", category="fashion", item_count=1
    )
    assert live[0].get("demo_only") is False


def _make_db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/research_guard.db")
    return engine, sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.mark.asyncio
async def test_launch_rejects_demo_asin_without_writing(tmp_path):
    """Demo ASIN launch must 400 before any Product/Job row is created."""
    engine, async_session = _make_db(tmp_path)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as db:
        body = LaunchTrendCampaignRequest(
            asin=_demo_asin(), title="Demo Jacket", price=54.99
        )
        with pytest.raises(HTTPException) as exc_info:
            await launch_campaign_from_trend(body, db)
        assert exc_info.value.status_code == 400
        assert "demo" in exc_info.value.detail.lower()

        products = (await db.execute(select(Product))).scalars().all()
        jobs = (await db.execute(select(Job))).scalars().all()
        assert products == []
        assert jobs == []


@pytest.mark.asyncio
async def test_launch_fails_loud_without_reference_and_leaves_no_orphan(tmp_path):
    """Empty reference library must 409 with no orphan Product left behind."""
    engine, async_session = _make_db(tmp_path)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as db:
        body = LaunchTrendCampaignRequest(
            asin="B012345678", title="Real Test Jacket", price=49.99
        )
        with pytest.raises(HTTPException) as exc_info:
            await launch_campaign_from_trend(body, db)
        assert exc_info.value.status_code == 409

        products = (await db.execute(select(Product))).scalars().all()
        jobs = (await db.execute(select(Job))).scalars().all()
        assert products == []
        assert jobs == []


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

    async def _no_match(*a, **kw):
        return []

    monkeypatch.setattr(mod, "_scan_seed_signals", _counting_scan)
    monkeypatch.setattr(mod, "match_amazon_products_for_trend", _no_match)
    monkeypatch.setattr(mod, "_trend_cache_dir",
                        lambda: tmp_path / "trend_cache")
    (tmp_path / "trend_cache").mkdir(parents=True, exist_ok=True)

    first = await mod.analyze_custom_trend_query("coastal cowgirl", "fashion")
    second = await mod.analyze_custom_trend_query("coastal cowgirl", "fashion")
    assert calls["n"] == 1
    assert first["keyword_pack"]["primary"]
    assert second["title"] == first["title"]
