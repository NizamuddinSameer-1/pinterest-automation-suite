"""
Unit tests for Product Deduplication service and helpers.
"""

from __future__ import annotations

import json
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import Job, Product, Reference
from app.services.product_dedup import (
    compute_dedup_key,
    find_existing,
    normalize_text,
)
from scripts.merge_duplicate_products import calculate_richness_score


def test_normalize_text():
    """Verify normalize_text lowercases, strips punctuation, and collapses whitespace."""
    assert normalize_text("  Leather   Jacket!  ") == "leather jacket"
    assert normalize_text("Women's Vintage Tea Dress, Short Sleeve") == "womens vintage tea dress short sleeve"
    assert normalize_text("Hanes - Boys' (Fleece)") == "hanes boys fleece"
    assert normalize_text("") == ""
    assert normalize_text(None) == ""


def test_compute_dedup_key():
    """Verify dedup key is identical for minor punctuation / case / spacing variants."""
    key1 = compute_dedup_key("Leather Jacket", "Acme", "Amazon")
    key2 = compute_dedup_key("  leather jacket! ", "ACME", "amazon")
    key3 = compute_dedup_key("Different Jacket", "Acme", "Amazon")

    assert key1 == key2
    assert len(key1) == 40  # SHA-1 hex digest
    assert key1 != key3


def test_calculate_richness_score():
    """Verify that richer products score higher."""
    bare_product = Product(id="p1", name="Leggings")
    rich_product = Product(
        id="p2",
        name="Leggings",
        product_image_path="products/leggings.jpg",
        product_truth_json=json.dumps({"must_preserve": ["waistband"]}),
        affiliate_url="https://amazon.com/dp/B012345678?tag=aff",
        price=29.99,
        brand="Lululemon",
    )
    assert calculate_richness_score(rich_product) > calculate_richness_score(bare_product)


@pytest.mark.asyncio
async def test_find_existing_by_asin_and_dedup_key():
    """Test finding products by ASIN and by normalized dedup_key."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # Product 1: Amazon product with ASIN
        p1 = Product(
            id="prod-asin",
            name="Wireless Headphones",
            brand="Sony",
            merchant="Amazon",
            asin="B07X123456",
            dedup_key=compute_dedup_key("Wireless Headphones", "Sony", "Amazon"),
            product_url="https://www.amazon.com/dp/B07X123456",
        )
        # Product 2: Non-Amazon product with dedup_key
        p2 = Product(
            id="prod-local",
            name="Ceramic Coffee Mug",
            brand="Handmade",
            merchant="Etsy",
            dedup_key=compute_dedup_key("Ceramic Coffee Mug", "Handmade", "Etsy"),
        )
        # Product 3: Legacy product without dedup_key
        p3 = Product(
            id="prod-legacy",
            name="Vintage Desk Lamp",
            brand=None,
            merchant=None,
            dedup_key=None,
        )

        db.add_all([p1, p2, p3])
        await db.commit()

        # 1. Match by ASIN directly
        res_asin = await find_existing(db, asin="B07X123456")
        assert res_asin is not None
        assert res_asin.id == "prod-asin"

        # 2. Match by URL containing ASIN
        res_url = await find_existing(db, url="https://amazon.com/dp/B07X123456?tag=test")
        assert res_url is not None
        assert res_url.id == "prod-asin"

        # 3. Match by Name / Brand / Merchant with different casing & punctuation
        res_key = await find_existing(
            db,
            name="  ceramic coffee mug!  ",
            brand="HANDMADE",
            merchant="etsy",
        )
        assert res_key is not None
        assert res_key.id == "prod-local"

        # 4. Fallback match for legacy product with NULL dedup_key
        res_legacy = await find_existing(db, name="vintage desk lamp")
        assert res_legacy is not None
        assert res_legacy.id == "prod-legacy"

        # 5. Non-matching product
        res_none = await find_existing(db, name="Nonexistent Item")
        assert res_none is None
