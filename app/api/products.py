"""
Product Management & Product Truth API.

Provides endpoints for listing, viewing, creating, updating, and deleting
products and managing their physical fidelity constraints (Product Truth).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import Product
from app.services.amazon_paapi import extract_asin
from app.services.product_dedup import compute_dedup_key, find_existing

logger = logging.getLogger("pre.api.products")
router = APIRouter(prefix="/api/products", tags=["Product Library"])


# ── Pydantic Request / Response Schemas ───────────────────────────

class ProductCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Product Name")
    brand: str | None = None
    merchant: str | None = None
    price: float | None = None
    currency: str = "USD"
    category: str | None = None
    product_url: str | None = None
    affiliate_url: str | None = None
    key_attributes: list[str] | None = None
    seasons: list[str] | None = None
    colors: list[str] | None = None
    materials: list[str] | None = None
    campaign_id: str | None = None


class ProductUpdateRequest(BaseModel):
    name: str | None = None
    brand: str | None = None
    merchant: str | None = None
    price: float | None = None
    currency: str | None = None
    category: str | None = None
    product_url: str | None = None
    affiliate_url: str | None = None
    key_attributes: list[str] | None = None
    seasons: list[str] | None = None
    colors: list[str] | None = None
    materials: list[str] | None = None


class ProductTruthUpdateRequest(BaseModel):
    must_preserve: list[str] = Field(default_factory=list)
    must_not_invent: list[str] = Field(default_factory=list)
    allowed_scene_variations: list[str] = Field(default_factory=list)


def _serialize_product(p: Product) -> dict[str, Any]:
    """Helper to convert Product model to dictionary with parsed truth JSON."""
    truth_data = {}
    if p.product_truth_json:
        try:
            truth_data = json.loads(p.product_truth_json)
        except Exception:
            truth_data = {}

    key_attrs = []
    if p.key_attributes:
        try:
            key_attrs = json.loads(p.key_attributes) if isinstance(p.key_attributes, str) else p.key_attributes
        except Exception:
            key_attrs = [p.key_attributes]

    return {
        "id": p.id,
        "campaign_id": p.campaign_id,
        "name": p.name,
        "brand": p.brand,
        "merchant": p.merchant or "Amazon",
        "product_url": p.product_url,
        "affiliate_url": p.affiliate_url,
        "price": p.price,
        "currency": p.currency or "USD",
        "category": p.category or "General",
        "product_image_path": p.product_image_path,
        "availability": p.availability,
        "key_attributes": key_attrs,
        "product_truth": truth_data,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


# ── Endpoints ─────────────────────────────────────────────────────

@router.get("")
async def list_products(
    campaign_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """List all registered products."""
    query = select(Product).order_by(Product.created_at.desc())
    if campaign_id:
        query = query.where(Product.campaign_id == campaign_id)

    result = await db.execute(query)
    products = result.scalars().all()
    return [_serialize_product(p) for p in products]


@router.get("/{product_id}")
async def get_product(
    product_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get a single product by ID."""
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return _serialize_product(product)


@router.post("")
async def create_product(
    body: ProductCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a new product manually."""
    # Seed default Product Truth from key_attributes
    truth_dict = {
        "must_preserve": body.key_attributes or [body.name],
        "must_not_invent": [],
        "allowed_scene_variations": [],
    }

    # Check if this product already exists by ASIN or dedup_key
    clean_asin = extract_asin(body.product_url) or extract_asin(body.affiliate_url)
    existing = await find_existing(
        db,
        asin=clean_asin,
        name=body.name,
        brand=body.brand,
        merchant=body.merchant or "Amazon",
        url=body.product_url or body.affiliate_url,
    )
    if existing:
        logger.info("Product dedup hit: reusing existing product %s (%r)", existing.id, existing.name)
        # Fill in any missing metadata from this submission
        if not existing.product_url and body.product_url:
            existing.product_url = body.product_url
        if not existing.affiliate_url and body.affiliate_url:
            existing.affiliate_url = body.affiliate_url
        if existing.price is None and body.price is not None:
            existing.price = body.price
        if clean_asin and not existing.asin:
            existing.asin = clean_asin
        await db.commit()
        await db.refresh(existing)
        return _serialize_product(existing)

    dedup_k = compute_dedup_key(body.name, body.brand, body.merchant or "Amazon")

    product = Product(
        campaign_id=body.campaign_id,
        name=body.name,
        brand=body.brand,
        merchant=body.merchant or "Amazon",
        asin=clean_asin,
        dedup_key=dedup_k,
        product_url=body.product_url,
        affiliate_url=body.affiliate_url,
        price=body.price,
        currency=body.currency,
        category=body.category,
        key_attributes=json.dumps(body.key_attributes) if body.key_attributes else None,
        seasons=json.dumps(body.seasons) if body.seasons else None,
        colors=json.dumps(body.colors) if body.colors else None,
        materials=json.dumps(body.materials) if body.materials else None,
        product_truth_json=json.dumps(truth_dict),
    )

    db.add(product)
    await db.commit()
    await db.refresh(product)
    return _serialize_product(product)


@router.put("/{product_id}")
async def update_product(
    product_id: str,
    body: ProductUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Update general product attributes."""
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if body.name is not None:
        product.name = body.name
    if body.brand is not None:
        product.brand = body.brand
    if body.merchant is not None:
        product.merchant = body.merchant
    if body.price is not None:
        product.price = body.price
    if body.currency is not None:
        product.currency = body.currency
    if body.category is not None:
        product.category = body.category
    if body.product_url is not None:
        product.product_url = body.product_url
    if body.affiliate_url is not None:
        product.affiliate_url = body.affiliate_url
    if body.key_attributes is not None:
        product.key_attributes = json.dumps(body.key_attributes)

    await db.commit()
    await db.refresh(product)
    return _serialize_product(product)


@router.put("/{product_id}/truth")
async def update_product_truth(
    product_id: str,
    body: ProductTruthUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Update Product Truth constraints sheet."""
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Merge with existing truth if any
    existing_truth = {}
    if product.product_truth_json:
        try:
            existing_truth = json.loads(product.product_truth_json)
        except Exception:
            existing_truth = {}

    existing_truth["must_preserve"] = body.must_preserve
    existing_truth["must_not_invent"] = body.must_not_invent
    existing_truth["allowed_scene_variations"] = body.allowed_scene_variations

    product.product_truth_json = json.dumps(existing_truth)
    await db.commit()
    await db.refresh(product)

    return {
        "status": "success",
        "product_id": product.id,
        "product_truth": existing_truth,
    }


@router.delete("/{product_id}")
async def delete_product(
    product_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Delete a product."""
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    await db.delete(product)
    await db.commit()
    return {"status": "success", "deleted_id": product_id}
