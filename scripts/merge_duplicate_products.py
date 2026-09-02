"""
Pinterest Realism Engine — Merge Duplicate Products & Backfill Script.

Usage:
    # Dry run (default, preview only):
    python -m scripts.merge_duplicate_products

    # Apply changes to database:
    python -m scripts.merge_duplicate_products --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections import defaultdict
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session, init_db
from app.models.models import Job, Product
from app.services.amazon_paapi import extract_asin
from app.services.product_dedup import compute_dedup_key

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("merge_products")


def _extract_asin_from_truth(truth_json: str | None) -> str | None:
    if not truth_json:
        return None
    try:
        data = json.loads(truth_json)
        if isinstance(data, dict):
            asin = data.get("asin")
            if asin:
                return extract_asin(str(asin))
    except Exception:
        pass
    return None


def calculate_richness_score(product: Product) -> int:
    """Calculate a richness score to determine the best survivor in a duplicate group."""
    score = 0
    # Rich Product Truth constraint definition
    if product.product_truth_json and len(product.product_truth_json.strip()) > 2:
        score += 25

    # Image presence & physical existence
    if product.product_image_path:
        score += 10
        try:
            if Path(product.product_image_path).exists():
                score += 10
        except Exception:
            pass

    # Commercial metadata
    if product.affiliate_url:
        score += 8
    if product.product_url:
        score += 5
    if product.price is not None:
        score += 4
    if product.brand:
        score += 3
    if product.category and product.category.lower() not in ("general", "unknown"):
        score += 2
    if product.materials:
        score += 2
    if product.key_attributes:
        score += 2

    return score


async def run_merge(apply: bool = False) -> None:
    logger.info("Initializing database and adding any missing columns...")
    await init_db()

    async with async_session() as db:
        stmt = select(Product)
        res = await db.execute(stmt)
        all_products = list(res.scalars().all())
        logger.info("Total products in database: %d", len(all_products))

        # ── 1. Backfill ASIN and dedup_key ───────────────────────────
        backfill_count = 0
        for p in all_products:
            # Detect ASIN
            found_asin = (
                extract_asin(p.product_url)
                or extract_asin(p.affiliate_url)
                or _extract_asin_from_truth(p.product_truth_json)
            )
            # Compute dedup key
            expected_key = compute_dedup_key(p.name, p.brand, p.merchant)

            updated = False
            if found_asin and p.asin != found_asin:
                p.asin = found_asin
                updated = True
            if p.dedup_key != expected_key:
                p.dedup_key = expected_key
                updated = True

            if updated:
                backfill_count += 1

        logger.info("Backfilled %d products with asin / dedup_key", backfill_count)

        # ── 2. Group Products by ASIN or dedup_key ──────────────────
        # Amazon products with identical ASIN
        asin_groups: dict[str, list[Product]] = defaultdict(list)
        # Non-Amazon / remaining products grouped by dedup_key
        key_groups: dict[str, list[Product]] = defaultdict(list)

        for p in all_products:
            if p.asin:
                asin_groups[p.asin].append(p)
            else:
                key_groups[p.dedup_key].append(p)

        # Collect groups with duplicates
        duplicate_clusters: list[tuple[str, list[Product]]] = []

        for asin_val, group in asin_groups.items():
            if len(group) > 1:
                duplicate_clusters.append((f"ASIN:{asin_val}", group))

        for dedup_k, group in key_groups.items():
            if len(group) > 1:
                duplicate_clusters.append((f"KEY:{dedup_k[:10]}...", group))

        if not duplicate_clusters:
            logger.info("No duplicate products found! Database is already clean.")
            if apply and backfill_count > 0:
                await db.commit()
                logger.info("Committed backfilled fields.")
            return

        logger.info("Found %d duplicate product cluster(s):", len(duplicate_clusters))

        total_repointed_jobs = 0
        total_deleted_products = 0

        for cluster_label, group in duplicate_clusters:
            # Sort group by richness score (highest first)
            group.sort(key=calculate_richness_score, reverse=True)
            survivor = group[0]
            victims = group[1:]

            survivor_score = calculate_richness_score(survivor)
            logger.info(
                "\n--- Cluster [%s] ---", cluster_label,
            )
            logger.info(
                "  Survivor: [ID: %s] %r (Score: %d, Image: %s, Truth: %s)",
                survivor.id,
                survivor.name,
                survivor_score,
                bool(survivor.product_image_path),
                bool(survivor.product_truth_json),
            )

            for victim in victims:
                victim_score = calculate_richness_score(victim)
                # Count jobs referencing victim
                job_res = await db.execute(select(Job).where(Job.product_id == victim.id))
                jobs = list(job_res.scalars().all())

                logger.info(
                    "  -> Victim:   [ID: %s] %r (Score: %d, Referenced by %d job(s))",
                    victim.id,
                    victim.name,
                    victim_score,
                    len(jobs),
                )

                # Merge any useful missing fields from victim to survivor
                if not survivor.product_image_path and victim.product_image_path:
                    survivor.product_image_path = victim.product_image_path
                if not survivor.product_truth_json and victim.product_truth_json:
                    survivor.product_truth_json = victim.product_truth_json
                if not survivor.product_url and victim.product_url:
                    survivor.product_url = victim.product_url
                if not survivor.affiliate_url and victim.affiliate_url:
                    survivor.affiliate_url = victim.affiliate_url
                if survivor.price is None and victim.price is not None:
                    survivor.price = victim.price

                if apply:
                    # Repoint jobs directly
                    if jobs:
                        await db.execute(
                            update(Job).where(Job.product_id == victim.id).values(product_id=survivor.id)
                        )
                    total_repointed_jobs += len(jobs)

                    # Flush and delete victim product
                    await db.flush()
                    await db.execute(delete(Product).where(Product.id == victim.id))
                    total_deleted_products += 1
                else:
                    total_repointed_jobs += len(jobs)
                    total_deleted_products += 1

        if apply:
            await db.commit()
            logger.info(
                "\nSUCCESS: Committed merge! Repointed %d jobs and deleted %d duplicate products.",
                total_repointed_jobs,
                total_deleted_products,
            )
        else:
            logger.info(
                "\nDRY-RUN COMPLETE: Would repoint %d jobs and delete %d duplicate products. (Run with --apply to execute)",
                total_repointed_jobs,
                total_deleted_products,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge duplicate products and backfill ASIN & dedup keys.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes to the database. If omitted, operates in dry-run mode.",
    )
    args = parser.parse_args()
    asyncio.run(run_merge(apply=args.apply))


if __name__ == "__main__":
    main()
