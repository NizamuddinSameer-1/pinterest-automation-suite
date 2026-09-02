"""
Pinterest Realism Engine — Product Deduplication Service.

Provides normalized dedup keys and unified lookup by ASIN or normalized (name, brand, merchant)
to eliminate duplicate products across Amazon PA-API ingest, manual creation, and reference auto-drafting.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Product
from app.services.amazon_paapi import extract_asin

logger = logging.getLogger("pre.product_dedup")


def normalize_text(text: str | None) -> str:
    """
    Normalize string: lowercase, strip punctuation, collapse whitespace.
    """
    if not text:
        return ""
    # Lowercase & strip leading/trailing whitespace
    s = str(text).lower().strip()
    # Strip punctuation (keep alphanumeric and spaces)
    s = re.sub(r"[^\w\s]", "", s)
    # Collapse multiple whitespace characters into single space
    s = re.sub(r"\s+", " ", s).strip()
    return s


def compute_dedup_key(
    name: str | None,
    brand: str | None = None,
    merchant: str | None = None,
) -> str:
    """
    Compute a deterministic SHA-1 hash for a product:
    sha1(normalize(name) + "|" + normalize(brand) + "|" + normalize(merchant))
    """
    n = normalize_text(name)
    b = normalize_text(brand)
    m = normalize_text(merchant)
    raw = f"{n}|{b}|{m}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


async def find_existing(
    db: AsyncSession,
    *,
    asin: str | None = None,
    name: str | None = None,
    brand: str | None = None,
    merchant: str | None = None,
    url: str | None = None,
) -> Product | None:
    """
    Find an existing product by ASIN (Priority 1) or by normalized dedup_key (Priority 2).
    Includes fallback matching for legacy un-backfilled rows.
    """
    # ── 1. ASIN Lookup ──────────────────────────────────────────────
    clean_asin: str | None = None
    if asin:
        clean_asin = extract_asin(asin)
    elif url:
        clean_asin = extract_asin(url)

    if clean_asin:
        # Match by indexed column
        stmt = select(Product).where(Product.asin == clean_asin)
        result = await db.execute(stmt)
        product = result.scalars().first()
        if product:
            return product

        # Fallback for legacy rows not yet backfilled
        legacy_stmt = select(Product).where(
            or_(
                Product.product_url.like(f"%{clean_asin}%"),
                Product.affiliate_url.like(f"%{clean_asin}%"),
                Product.product_truth_json.like(f'%"asin": "{clean_asin}"%'),
            )
        )
        legacy_res = await db.execute(legacy_stmt)
        legacy_product = legacy_res.scalars().first()
        if legacy_product:
            if not legacy_product.asin:
                legacy_product.asin = clean_asin
            return legacy_product

    # ── 2. Dedup Key Lookup ─────────────────────────────────────────
    if name:
        target_key = compute_dedup_key(name, brand, merchant)
        stmt = select(Product).where(Product.dedup_key == target_key)
        result = await db.execute(stmt)
        product = result.scalars().first()
        if product:
            return product

        # Fallback for un-backfilled rows where dedup_key is NULL
        # Match case-insensitively on name if dedup_key is missing
        norm_name = normalize_text(name)
        if norm_name:
            candidates_stmt = select(Product).where(Product.dedup_key.is_(None))
            candidates_res = await db.execute(candidates_stmt)
            for cand in candidates_res.scalars().all():
                cand_key = compute_dedup_key(cand.name, cand.brand, cand.merchant)
                if cand_key == target_key:
                    cand.dedup_key = target_key
                    return cand

    return None
