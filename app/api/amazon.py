"""
Amazon Product Discovery & Ingestion API.

Provides endpoints for searching Amazon US products via PA-API 5.0,
fetching real-time product metadata/ratings, and 1-click product ingestion
directly into the Pinterest Affiliate Engine.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.models import Product
from app.services.affiliate_router import build_smart_redirect_url, clean_style_keywords
from app.services.amazon_paapi import extract_asin, paapi_client

logger = logging.getLogger("pre.api.amazon")
router = APIRouter(prefix="/api/amazon", tags=["Amazon Product Discovery"])


# ── Pydantic Request / Response Schemas ───────────────────────────

class AmazonSearchRequest(BaseModel):
    keywords: str = Field(..., description="Product keywords to search on Amazon")
    category: str = Field("All", description="Amazon search category (e.g. All, Fashion, HomeGarden)")
    sort_by: str = Field("Featured", description="Featured, AvgCustomerReviews, Price:LowToHigh, Price:HighToLow")
    item_count: int = Field(10, ge=1, le=10, description="Number of results (1-10)")
    country: str = Field("US", description="Amazon marketplace country (US or IN)")


class AmazonLookupRequest(BaseModel):
    asin_or_url: str = Field(..., description="Amazon ASIN or direct product URL")
    country: str = Field("US", description="Amazon marketplace country (US or IN)")
    asin_in: str | None = Field(None, description="Optional Amazon India ASIN")


class AmazonIngestRequest(BaseModel):
    asin_or_url: str = Field(..., description="Amazon ASIN or product URL to ingest")
    campaign_id: str | None = Field(None, description="Optional campaign ID to associate")
    custom_keywords: str | None = Field(None, description="Optional custom search phrase for Indian traffic")
    country: str = Field("US", description="Amazon marketplace country (US or IN)")
    asin_in: str | None = Field(None, description="Optional Amazon India ASIN")


# ── Endpoint: Search Products ─────────────────────────────────────

@router.post("/search")
async def search_amazon_products(body: AmazonSearchRequest) -> dict[str, Any]:
    """
    Search Amazon products with real-time prices and ratings.
    """
    try:
        items = await paapi_client.search_items(
            keywords=body.keywords,
            search_index=body.category,
            item_count=body.item_count,
            sort_by=body.sort_by,
        )
        # Attach preview smart link to each result
        for item in items:
            item["smart_url"] = build_smart_redirect_url(
                asin=item["asin"],
                title=item.get("title"),
                asin_in=item.get("asin_in"),
            )
            item["style_query"] = clean_style_keywords(item.get("title", ""))

        return {
            "success": True,
            "count": len(items),
            "keywords": body.keywords,
            "items": items,
        }
    except Exception as e:
        logger.error("Amazon search failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Amazon search failed: {str(e)}")


# ── Endpoint: Lookup Single Item ──────────────────────────────────

@router.post("/lookup")
async def lookup_amazon_product(body: AmazonLookupRequest) -> dict[str, Any]:
    """
    Lookup detailed metadata for a single Amazon ASIN or product URL.
    """
    asin = extract_asin(body.asin_or_url)
    if not asin:
        raise HTTPException(status_code=400, detail=f"Could not extract a valid ASIN from: {body.asin_or_url}")

    try:
        item = await paapi_client.get_item(asin, country=body.country)
        if not item:
            raise HTTPException(status_code=404, detail=f"Product with ASIN {asin} not found on Amazon.")

        asin_in = body.asin_in or item.get("asin_in")
        item["smart_url"] = build_smart_redirect_url(
            asin=item["asin"],
            title=item.get("title"),
            asin_in=asin_in,
        )
        item["style_query"] = clean_style_keywords(item.get("title", ""))

        return {
            "success": True,
            "item": item,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Amazon lookup failed for %s: %s", asin, e)
        raise HTTPException(status_code=500, detail=f"Amazon lookup failed: {str(e)}")


# ── Endpoint: Ingest Product into Database ────────────────────────

@router.post("/ingest")
async def ingest_amazon_product(
    body: AmazonIngestRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    1-Click Ingestion: Fetches real-time Amazon data, downloads primary product image,
    constructs the universal /api/go smart link, deduplicates by ASIN, and saves the Product.
    """
    asin = extract_asin(body.asin_or_url)
    if not asin:
        raise HTTPException(status_code=400, detail=f"Invalid Amazon ASIN or URL: {body.asin_or_url}")

    item = await paapi_client.get_item(asin, country=body.country)
    if not item:
        raise HTTPException(status_code=404, detail=f"Could not fetch product details for ASIN: {asin}")

    # 1. Download product image locally
    image_rel_path = None
    if item.get("primary_image_url"):
        try:
            products_dir = settings.products_path
            products_dir.mkdir(parents=True, exist_ok=True)
            img_filename = f"{asin}.jpg"
            img_dest = products_dir / img_filename
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(item["primary_image_url"])
                if res.status_code == 200:
                    img_dest.write_bytes(res.content)
                    image_rel_path = str(img_dest)
        except Exception as e:
            logger.warning("Failed to download image for %s: %s", asin, e)

    # 2. Build Universal Smart Link (/api/go) with asin_in support
    asin_in = body.asin_in or item.get("asin_in")
    style_query = body.custom_keywords or clean_style_keywords(item["title"])
    smart_url = build_smart_redirect_url(
        asin=asin,
        title=item["title"],
        asin_in=asin_in,
    )

    # 3. Dynamic Category (no hardcoding)
    category = (
        item.get("category")
        or item.get("department")
        or item.get("search_index")
        or "Fashion & Lifestyle"
    )

    # 4. Authentic fields without fabrication
    brand = item.get("brand") or None
    price_display = item.get("price") or None
    price_amount = item.get("price_amount")
    currency = item.get("currency") or "USD"
    is_prime = bool(item.get("is_prime", False))

    must_preserve = item.get("must_preserve") or []
    if not must_preserve:
        must_preserve = [item["title"][:120], "Original physical silhouette and authentic textures"]

    must_not_invent = item.get("must_not_invent") or [
        "Do not add logos, graphics, or branding not on the original product",
        "Do not alter the garment neckline, sleeve length, or pocket placement",
        "Do not invent extra zippers, hoods, or non-existent hardware",
    ]

    product_truth = {
        "asin": asin,
        "asin_in": asin_in,
        "title": item["title"],
        "brand": brand,
        "price_display": price_display,
        "price_amount": price_amount,
        "currency": currency,
        "list_price": item.get("list_price"),
        "savings_percent": item.get("savings_percent"),
        "star_rating": item.get("star_rating"),
        "review_count": item.get("review_count"),
        "is_prime": is_prime,
        "style_query": style_query,
        "category": category,
        "features": item.get("features", []),
        "about_this_item": item.get("about_this_item", []),
        "product_overview": item.get("product_overview", {}),
        "technical_specs": item.get("technical_specs", {}),
        "product_description": item.get("product_description", ""),
        "materials": item.get("materials", []),
        "style_attributes": item.get("style_attributes", []),
        "must_preserve": must_preserve,
        "must_not_invent": must_not_invent,
        "allowed_scene_variations": [
            "Plausible real-world model poses and candid body angles",
            "Natural indoor and outdoor ambient daylight conditions",
            "Context-appropriate candid lifestyle and streetwear framing",
        ],
        "verified_date": item.get("verified_date"),
        "smart_affiliate_url": smart_url,
    }

    # 5. ASIN Deduplication Check
    query = select(Product).where(
        (Product.product_url.like(f"%{asin}%")) | (Product.product_truth_json.like(f'%"asin": "{asin}"%'))
    )
    res = await db.execute(query)
    existing_product = res.scalars().first()

    if existing_product:
        existing_product.name = item["title"][:250]
        existing_product.brand = brand[:120] if brand else None
        existing_product.merchant = "Amazon"
        existing_product.price = price_amount
        existing_product.currency = currency
        existing_product.category = category
        existing_product.materials = json.dumps(item.get("materials", []))
        existing_product.key_attributes = json.dumps(item.get("style_attributes", []))
        if image_rel_path:
            existing_product.product_image_path = image_rel_path
        existing_product.product_truth_json = json.dumps(product_truth)
        existing_product.affiliate_url = smart_url
        existing_product.availability = "in_stock"
        product = existing_product
        logger.info("Updated existing Amazon product %s (ID: %s)", asin, product.id)
    else:
        product_url = (
            f"https://www.amazon.in/dp/{asin}"
            if body.country.upper() == "IN"
            else f"https://www.amazon.com/dp/{asin}"
        )
        product = Product(
            campaign_id=body.campaign_id,
            name=item["title"][:250],
            brand=brand[:120] if brand else None,
            merchant="Amazon",
            product_url=product_url,
            affiliate_url=smart_url,
            price=price_amount,
            currency=currency,
            category=category,
            materials=json.dumps(item.get("materials", [])),
            key_attributes=json.dumps(item.get("style_attributes", [])),
            product_image_path=image_rel_path,
            product_truth_json=json.dumps(product_truth),
            availability="in_stock",
        )
        db.add(product)
        logger.info("Ingested new Amazon product %s", asin)

    await db.commit()
    await db.refresh(product)

    return {
        "success": True,
        "product_id": product.id,
        "asin": asin,
        "asin_in": asin_in,
        "name": product.name,
        "price": price_display,
        "price_amount": price_amount,
        "currency": currency,
        "brand": brand,
        "category": category,
        "smart_affiliate_url": smart_url,
        "style_query": style_query,
        "image_path": product.product_image_path,
        "deduplicated": existing_product is not None,
    }
