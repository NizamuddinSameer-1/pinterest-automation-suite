"""
Research & Trend Discovery API Endpoints.

Provides endpoints for:
- Browsing real-time global shopping trends across Fashion, Home, Kitchen, Tech, Seasonal
- On-demand deep trend analysis for custom search queries
- 1-Click campaign launching: from trending product directly to database ingestion and generation setup
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import urllib.parse
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.models import Job, Product, Reference, ReferenceAnalysis, VisualDNA
from app.services.affiliate_router import build_smart_redirect_url
from app.services.product_dedup import compute_dedup_key, find_existing
from app.services.pinterest_trends_scraper import (
    get_official_pinterest_trends,
    get_trend_deep_dive,
    scrape_custom_pinterest_trend_metrics,
)
from app.services.trend_research import (
    DEMO_ASINS,
    analyze_custom_trend_query,
    discover_trends_radar,
    select_snapshot_dossiers,
)

logger = logging.getLogger("pre.api.research")
router = APIRouter(prefix="/api/research", tags=["Trend Research & Discovery"])


class CustomTrendQueryRequest(BaseModel):
    query: str = Field(..., description="Topic, outfit, aesthetic, or product to analyze")
    category: str = Field("fashion", description="Category: fashion | home | kitchen | tech | seasonal")
    refresh: bool = Field(False, description="Force live market search bypassing cache")


class LaunchTrendCampaignRequest(BaseModel):
    asin: str = Field(..., description="Amazon ASIN of the chosen product")
    title: str = Field(..., description="Product title")
    price: float = Field(39.99, description="Product price")
    category: str = Field("fashion", description="Category")
    image_url: str | None = Field(None, description="Primary product image URL")
    trend_label: str | None = Field(None, description="Aesthetic or trend label")
    scene_setting: str | None = Field(None, description="Recommended scene description")
    board_name: str | None = Field(None, description="Target Pinterest board name")
    affiliate_url: str | None = Field(None, description="Direct or smart affiliate link")
    keyword_pack: dict[str, Any] | None = Field(None, description="Keyword pack threaded from the trend dossier")


@router.get("/trends")
async def get_trends_radar(
    category: str = Query("all", description="Category filter: all | fashion | home | kitchen | tech | seasonal"),
    refresh: bool = Query(False, description="Force live market re-scan bypassing snapshot cache"),
    include_pinterest: bool = Query(True, description="Ingest today's measured Pinterest trends alongside curated seeds"),
) -> dict[str, Any]:
    """
    Get today's real-time Trend Radar feed with live Google Shopping search momentum,
    high-intent queries, and top-rated matching Amazon affiliate products.
    Serves the daily snapshot when fresh (<1h), contains items for category, and refresh is False.
    """
    if not refresh:
        try:
            snap_dir = Path(settings.storage_path) / "trend_radar"
            snap_file = snap_dir / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.json"
            if snap_file.exists():
                try:
                    now_s = datetime.now(timezone.utc).timestamp()
                    payload = json.loads(snap_file.read_text(encoding="utf-8"))
                    # Version-, weights- and age-checked; None falls through to live scan.
                    filtered = select_snapshot_dossiers(
                        payload, category,
                        scanned_at_s=snap_file.stat().st_mtime, now_s=now_s,
                    )
                    if filtered:
                        return {
                            "success": True,
                            "category": category,
                            "count": len(filtered),
                            "trends": filtered,
                        }
                except Exception as e:
                    logger.warning("Trend snapshot unreadable, falling through to live scan: %s", e)
        except Exception as e:
            logger.warning("Trend snapshot check failed, falling through to live scan: %s", e)

    try:
        trends = await discover_trends_radar(category_filter=category, include_pinterest=include_pinterest)
        if category and category != "all":
            trends = [t for t in trends if t.get("category") == category]
        return {
            "success": True,
            "category": category,
            "count": len(trends),
            "trends": trends,
        }
    except Exception as e:
        logger.error("Failed to generate trends radar: %s", e)
        raise HTTPException(status_code=500, detail=f"Could not load trends: {e}") from e


@router.post("/query")
async def query_custom_trend(body: CustomTrendQueryRequest) -> dict[str, Any]:
    """
    Deep-dive into any custom topic, outfit formula, or aesthetic.
    Returns real-time shopping search queries, momentum badges, and matched products.
    """
    try:
        dossier = await analyze_custom_trend_query(
            query=body.query,
            category=body.category,
            refresh=body.refresh,
        )
        return {
            "success": True,
            "dossier": dossier,
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error("Custom trend query failed for %r: %s", body.query, e)
        raise HTTPException(status_code=500, detail=f"Trend query failed: {e}") from e


@router.post("/launch-campaign")
async def launch_campaign_from_trend(
    body: LaunchTrendCampaignRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    1-Click Action: Ingests the researched product into SQLite, ensures primary image is stored,
    attaches or discovers a matching aesthetic reference, and initializes a Job.
    """
    asin = body.asin.strip().upper()
    if not asin:
        raise HTTPException(status_code=400, detail="ASIN is required")
    if not re.fullmatch(r"[A-Z0-9]{10}", asin):
        raise HTTPException(status_code=400, detail=f"Invalid ASIN {body.asin!r}: must be 10 alphanumeric characters")
    if body.image_url:
        lowered = body.image_url.strip().lower()
        if not (lowered.startswith("http://") or lowered.startswith("https://")):
            raise HTTPException(status_code=400, detail="image_url must use http:// or https://")

    # Demo-guard: curated Trend Radar fallbacks carry invented ASINs (Unsplash
    # photos, illustrative prices) — ingesting one would create a Product whose
    # affiliate link points at a listing that does not exist. Fail loud.
    if asin in DEMO_ASINS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"ASIN {asin} is a curated demo placeholder, not a real Amazon listing. "
                "Wait for live PA-API results (or ingest the real ASIN) instead of "
                "launching a campaign on demo data."
            ),
        )

    # 1. Resolve a matching aesthetic reference FIRST — before creating anything.
    # Failing here must leave no orphan Product behind.
    ref_stmt = select(Reference).where(Reference.trend_label == body.trend_label).limit(1)
    ref_res = await db.execute(ref_stmt)
    reference = ref_res.scalars().first()

    if not reference:
        # Check any active reference or fail loud: writing a fake JPEG placeholder
        # here used to poison the vision chain (analyst → DNA → scene) with garbage
        # pixels. A campaign without a real analyzed reference is not launchable.
        any_ref = (await db.execute(select(Reference).limit(1))).scalars().first()
        if any_ref:
            reference = any_ref
        else:
            raise HTTPException(
                status_code=409,
                detail=(
                    "No reference images in the library yet. Upload and analyze a "
                    "reference photo first — campaigns cannot launch on placeholder pixels."
                ),
            )

    # 2. Check if product already exists
    dedup_key = compute_dedup_key(name=body.title, merchant="Amazon")
    existing_product = await find_existing(db, asin=asin, name=body.title, merchant="Amazon")

    if existing_product:
        product = existing_product
        logger.info("Found existing product for ASIN %s: %s (ID: %s)", asin, product.name, product.id)
    else:
        # Download primary image if provided
        products_dir = settings.products_path
        products_dir.mkdir(parents=True, exist_ok=True)
        img_dest = products_dir / f"{asin}.jpg"
        image_path_str = str(img_dest)

        if body.image_url:
            try:
                async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
                    async with client.stream("GET", body.image_url) as resp:
                        if resp.status_code != 200:
                            logger.warning("Product image download returned %s for %s", resp.status_code, body.image_url)
                        else:
                            content_type = resp.headers.get("content-type", "")
                            if not content_type.lower().startswith("image/"):
                                logger.warning(
                                    "Refusing product image with content-type %r from %s",
                                    content_type, body.image_url,
                                )
                            else:
                                chunks: list[bytes] = []
                                total = 0
                                too_big = False
                                async for chunk in resp.aiter_bytes(chunk_size=65536):
                                    total += len(chunk)
                                    if total > 8 * 1024 * 1024:
                                        too_big = True
                                        break
                                    chunks.append(chunk)
                                if too_big:
                                    logger.warning("Product image exceeded 8 MB cap, discarding bytes from %s", body.image_url)
                                else:
                                    content = b"".join(chunks)
                                    if len(content) > 500:
                                        img_dest.write_bytes(content)
            except Exception as e:
                logger.warning("Could not download product image from %s: %s", body.image_url, e)

        # Build smart redirect affiliate URL
        smart_url = body.affiliate_url or build_smart_redirect_url(asin=asin, title=body.title)

        product = Product(
            id=str(uuid4()),
            name=body.title,
            asin=asin,
            dedup_key=dedup_key,
            product_url=f"https://www.amazon.com/dp/{asin}",
            affiliate_url=smart_url,
            price=body.price,
            currency="USD",
            category=body.category.title(),
            product_image_path=image_path_str if img_dest.exists() else body.image_url,
            product_images_json=json.dumps([image_path_str]) if img_dest.exists() else None,
            availability="in_stock",
        )
        db.add(product)
        await db.commit()
        await db.refresh(product)
        logger.info("Created new Product from Trend Radar: %s (ASIN: %s)", product.name, asin)

    # 3. Create Job from the resolved reference + product
    scene_dict = {
        "setting": body.scene_setting or f"Realistic lifestyle scene highlighting {body.title}",
        "lighting": "warm natural ambient morning light",
        "perspective": "candid eye-level authentic camera framing",
    }
    job = Job(
        id=str(uuid4()),
        product_id=product.id,
        reference_id=reference.id,
        scene_json=json.dumps(scene_dict),
        current_state="DRAFT",
        keyword_pack_json=json.dumps(body.keyword_pack) if body.keyword_pack else None,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    return {
        "status": "success",
        "product_id": product.id,
        "job_id": job.id,
        "product_name": product.name,
        "board_name": body.board_name,
        "message": f"Successfully launched campaign for '{product.name}'. Ready for generation!",
    }


# ── Official Pinterest Trends (Live from trends.pinterest.com) ────────────────

class OfficialPinterestTrendQueryRequest(BaseModel):
    query: str = Field(..., description="Custom keyword or trend to analyze on trends.pinterest.com")
    country: str = Field("US", description="Country code, e.g. US, GB")
    refresh: bool = Field(False, description="Force live Playwright re-query")


class LaunchInspoCampaignRequest(BaseModel):
    term: str = Field(..., description="Trending keyword or topic (e.g. 'fall nail colors 2026')")
    category: str = Field("beauty", description="Category: beauty | fashion | home | seasonal")
    board_name: str | None = Field(None, description="Target Pinterest board name")
    destination_url: str | None = Field(None, description="Blog, Lookbook, or media destination URL")
    preview_image_url: str | None = Field(None, description="Inspirational thumbnail or preview image")
    visual_prompt_notes: str | None = Field(None, description="Aesthetic prompt guidance")


@router.get("/pinterest-official-trends")
async def get_pinterest_official_trends(
    preset: str = Query("breakout", description="Preset: breakout | growing | top"),
    intent: str = Query("all", description="Intent filter: all | viral_blog | commercial_product"),
    country: str = Query("US", description="Country code, e.g. US, GB, CA"),
    refresh: bool = Query(False, description="Force live Playwright re-scrape of trends.pinterest.com"),
) -> dict[str, Any]:
    """
    Get official live Pinterest Trends from trends.pinterest.com via Playwright.
    Includes 52-week search momentum sparklines, MoM growth surges,
    20-day early-pinning indexing window recommendations, and intent classification.
    """
    try:
        trends = await get_official_pinterest_trends(
            preset=preset,
            intent=intent,
            country=country,
            force_refresh=refresh,
        )
        is_fallback = bool(trends) and all(t.get("is_fallback", False) for t in trends)
        return {
            "success": True,
            "source": "curated_fallback" if is_fallback else "trends.pinterest.com",
            "is_fallback": is_fallback,
            "preset": preset,
            "intent": intent,
            "country": country,
            "count": len(trends),
            "trends": trends,
        }
    except Exception as e:
        logger.error("Failed to fetch official Pinterest trends: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to fetch official Pinterest trends: {e}") from e


@router.post("/pinterest-official-trends/query")
async def query_pinterest_official_trend(body: OfficialPinterestTrendQueryRequest) -> dict[str, Any]:
    """
    Deep-dive into ANY custom topic on trends.pinterest.com using Playwright.
    Returns official 52-week normalized search points, MoM/WoW change, and 20-day indexing advice.
    """
    clean_q = body.query.strip()
    if not clean_q:
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    try:
        item = await scrape_custom_pinterest_trend_metrics(query=clean_q, country=body.country)
        if not item:
            # Honest miss: Pinterest returned no trajectory for this term.
            # Never invent a sparkline / growth numbers and call it success.
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No Pinterest Trends data for {clean_q!r} (region {body.country}). "
                    "Try a broader term or check the spelling."
                ),
            )
        return {
            "success": True,
            "trend": item,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to query custom Pinterest trend %r: %s", body.query, e)
        raise HTTPException(status_code=500, detail=f"Custom Pinterest trend query failed: {e}") from e


@router.get("/pinterest-official-trends/detail")
async def get_pinterest_official_trend_detail(
    term: str = Query(..., description="Trend keyword, e.g. 'casual blazer outfits' or 'september nails ideas 2026'"),
    country: str = Query("US", description="Country code, e.g. US, GB, CA"),
    refresh: bool = Query(False, description="Force live re-scrape"),
) -> dict[str, Any]:
    """
    Deep-dive into a specific Pinterest trend: returns 0-100 indexed momentum graph,
    MoM growth, 'Pinners commonly search for' queries, and authentic 'Popular Pins' gallery.
    """
    clean_term = term.strip()
    if not clean_term:
        raise HTTPException(status_code=400, detail="Query term cannot be empty")
    try:
        data = await get_trend_deep_dive(term=clean_term, country=country, force_refresh=refresh)
        return {
            "success": True,
            "data": data,
        }
    except Exception as e:
        logger.error("Failed to fetch Pinterest trend deep dive for %r: %s", clean_term, e)
        raise HTTPException(status_code=500, detail=f"Trend deep dive failed: {e}") from e


class ImportPinReferenceRequest(BaseModel):
    image_url: str = Field(..., description="High-res pin image URL (i.pinimg.com or external)")
    pin_title: str = Field(..., description="Title or visual hook of the pin")
    trend_label: str = Field(..., description="Aesthetic or trend keyword, e.g. 'casual blazer outfits'")
    category: str = Field("fashion", description="Category: fashion | beauty | home | seasonal")
    source_pin_url: str | None = Field(None, description="Original Pinterest pin link")


@router.post("/import-pin-reference")
async def import_pin_reference(
    body: ImportPinReferenceRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    1-Click Action: Imports an authentic viral Pinterest pin into PRE's Reference Library,
    downloads the high-res image, triggers LLM visual analysis & Visual DNA extraction,
    and syncs to Obsidian Vault.
    """
    img_url = body.image_url.strip()
    if not (img_url.startswith("http://") or img_url.startswith("https://")):
        raise HTTPException(status_code=400, detail="image_url must use http:// or https://")

    # Upgrade pinimg thumbnail to high-resolution (236x -> 736x)
    if "pinimg.com/236x/" in img_url:
        img_url = img_url.replace("/236x/", "/736x/")

    ref_id = str(uuid4())
    references_dir = settings.references_path
    references_dir.mkdir(parents=True, exist_ok=True)
    dest_path = references_dir / f"{ref_id}.jpg"

    # Download the image
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                "Referer": "https://www.pinterest.com/",
            }
            async with client.stream("GET", img_url, headers=headers) as resp:
                if resp.status_code != 200:
                    raise HTTPException(status_code=400, detail=f"Failed to download pin image (HTTP {resp.status_code})")
                with open(dest_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        f.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error downloading pin image from %s: %s", img_url, e)
        raise HTTPException(status_code=500, detail=f"Failed to download pin image: {e}") from e

    clean_label = body.trend_label.strip() or "Pinterest Trend Reference"
    clean_cat = body.category.strip().lower() or "fashion"

    # Create Reference in DB
    ref = Reference(
        id=ref_id,
        image_path=str(dest_path),
        trend_label=clean_label,
        category=clean_cat,
        status="uploaded",
    )
    db.add(ref)
    await db.flush()

    # Run visual analysis and DNA extraction
    analysis_data = None
    dna_data = None
    try:
        from app.pipeline.reference_analyst import analyze_reference
        analysis_data = await analyze_reference(str(dest_path))
        analysis_record = ReferenceAnalysis(
            reference_id=ref.id,
            analysis_json=json.dumps(analysis_data),
        )
        db.add(analysis_record)
        await db.flush()
    except Exception as e:
        logger.warning("LLM analysis failed for imported pin reference %s: %s", ref.id, e)

    try:
        from app.pipeline.visual_dna import extract_visual_dna
        if analysis_data:
            dna_data = await extract_visual_dna(analysis_data, image_path=dest_path)
    except Exception as e:
        logger.warning("Visual DNA extraction failed for imported pin reference %s: %s", ref.id, e)

    if dna_data is None:
        dna_data = {
            "capture_identity": {
                "type": "pinterest_viral_ugc",
                "professionalism": "authentic_creator",
                "spontaneity": "high",
            },
            "composition_dna": {
                "centering": "rule_of_thirds",
                "framing": "vertical_editorial",
                "crop": "pinterest_2_3",
                "camera_height": "eye_level",
            },
            "environment_dna": {
                "real_world_context": True,
                "trend_context": clean_label,
                "clutter": "low",
            },
            "lighting_dna": {
                "type": "natural_daylight",
                "quality": "soft_diffused",
                "color_cast": "warm_neutral",
            },
            "realism_markers": {
                "anti_stock": True,
                "anti_ai_gloss": True,
                "imperfection_level": "moderate",
            },
        }

    dna_record = VisualDNA(
        reference_id=ref.id,
        version=1,
        dna_json=json.dumps(dna_data),
    )
    db.add(dna_record)
    ref.status = "analyzed"
    await db.commit()
    await db.refresh(ref)

    # Obsidian Vault Sync
    vault_synced = True
    try:
        from app.services.vault_sync import sync_reference_node
        sync_reference_node(
            reference_id=ref.id,
            trend_label=ref.trend_label,
            category=ref.category,
            image_path=ref.image_path,
            analysis=analysis_data,
            visual_dna=dna_data,
        )
    except Exception as e:
        vault_synced = False
        logger.warning("Vault sync error for pin reference %s: %s", ref.id, e)

    return {
        "status": "success",
        "reference_id": ref.id,
        "trend_label": ref.trend_label,
        "category": ref.category,
        "image_path": str(dest_path),
        "vault_synced": vault_synced,
        "has_visual_dna": True,
        "message": f"Successfully imported '{body.pin_title or clean_label}' into Style Reference library!",
    }


@router.post("/launch-inspo-campaign")
async def launch_inspo_campaign(
    body: LaunchInspoCampaignRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    1-Click Action for Viral Blog & Editorial Inspo Topics (Nails, Hair, Outfits, DIY).
    Creates an editorial product entry pointing to the blog/lookbook and initializes a ready-to-run Job.
    """
    clean_term = body.term.strip()
    if not clean_term:
        raise HTTPException(status_code=400, detail="Term is required")

    # 1. Resolve or pick a visual aesthetic reference
    any_ref = (await db.execute(select(Reference).limit(1))).scalars().first()
    if not any_ref:
        raise HTTPException(
            status_code=409,
            detail="No reference images in the library yet. Please upload at least one reference photo first.",
        )
    reference = any_ref

    # 2. Destination URL (default to live Lookbook site)
    dest_url = body.destination_url or f"https://pinterest-lookbooks-beta.vercel.app/?topic={urllib.parse.quote_plus(clean_term)}"
    target_board = body.board_name or f"{clean_term.title()} Inspo & Aesthetic Ideas"

    # 3. Create or find editorial Product entry
    dedup_key = compute_dedup_key(name=clean_term.title(), merchant="Pinterest Inspo")
    existing_product = await find_existing(db, asin=None, name=clean_term.title(), merchant="Pinterest Inspo")

    if existing_product:
        product = existing_product
    else:
        product = Product(
            id=str(uuid4()),
            name=f"{clean_term.title()} (Viral Inspo Guide)",
            brand="Pinterest Trend Inspo",
            merchant="Pinterest Inspo",
            dedup_key=dedup_key,
            product_url=dest_url,
            affiliate_url=dest_url,
            price=0.0,
            currency="USD",
            category=body.category.title(),
            product_image_path=body.preview_image_url,
            availability="in_stock",
        )
        db.add(product)
        await db.commit()
        await db.refresh(product)

    # 4. Initialize generation Job
    scene_dict = {
        "setting": f"Editorial high-aesthetic lifestyle framing for {clean_term}, soft directional lighting, premium detail, candid composition",
        "lighting": "golden hour soft ambient lighting",
        "perspective": "macro close-up and candid lifestyle perspective",
    }
    job = Job(
        id=str(uuid4()),
        product_id=product.id,
        reference_id=reference.id,
        scene_json=json.dumps(scene_dict),
        current_state="DRAFT",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    return {
        "status": "success",
        "job_id": job.id,
        "product_id": product.id,
        "board_name": target_board,
        "message": f"Successfully launched viral inspo campaign for '{clean_term}'! Ready in Creative Lab.",
    }

