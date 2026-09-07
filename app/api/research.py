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
from typing import Any
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.models import Job, Product, Reference
from app.services.affiliate_router import build_smart_redirect_url
from app.services.product_dedup import compute_dedup_key, find_existing
from app.services.trend_research import (
    DEMO_ASINS,
    analyze_custom_trend_query,
    discover_trends_radar,
)

logger = logging.getLogger("pre.api.research")
router = APIRouter(prefix="/api/research", tags=["Trend Research & Discovery"])


class CustomTrendQueryRequest(BaseModel):
    query: str = Field(..., description="Topic, outfit, aesthetic, or product to analyze")
    category: str = Field("fashion", description="Category: fashion | home | kitchen | tech | seasonal")


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


@router.get("/trends")
async def get_trends_radar(
    category: str = Query("all", description="Category filter: all | fashion | home | kitchen | tech | seasonal"),
) -> dict[str, Any]:
    """
    Get today's real-time Trend Radar feed with live Google Shopping search momentum,
    high-intent queries, and top-rated matching Amazon affiliate products.
    """
    try:
        trends = await discover_trends_radar(category_filter=category)
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
        dossier = await analyze_custom_trend_query(query=body.query, category=body.category)
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
                async with httpx.AsyncClient(timeout=12.0) as client:
                    resp = await client.get(body.image_url)
                    if resp.status_code == 200 and len(resp.content) > 500:
                        img_dest.write_bytes(resp.content)
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
