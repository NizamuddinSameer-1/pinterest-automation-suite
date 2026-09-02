"""
Comprehensive verification test for Elite Affiliate Lookbook & Bridge Page Engine.
Job ID: 6511d2af-0b11-4b75-921d-d4cc8d1bd941
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

import httpx
from httpx import ASGITransport
from sqlalchemy import select

# Ensure Windows Proactor
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import async_session
from app.models.models import Job, PinDraft, Product
from app.services.article_generator import generate_lookbook_html
from app.services.bridge_copilot import generate_bridge_copy
from app.services.niche_strategist import score_product_opportunity
from app.services.output_service import _product_to_dict
from app.services.vercel_publisher import deploy_article_to_vercel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("test_lookbook")

JOB_ID = "6511d2af-0b11-4b75-921d-d4cc8d1bd941"


async def main():
    logger.info("=== STEP 1: Fetch Job & Product from Database ===")
    async with async_session() as db:
        job = await db.get(Job, JOB_ID)
        assert job, f"Job {JOB_ID} not found"
        product = await db.get(Product, job.product_id)
        assert product, "Product not found"

    product_data = _product_to_dict(product)
    scene_data = json.loads(job.scene_json) if job.scene_json else {}
    output_dir = Path(f"data/outputs/{JOB_ID}")
    image_paths = sorted([str(f) for f in output_dir.glob("flow_var_*.jpg")])

    logger.info("Product: %s (%s)", product.name, product.brand)
    logger.info("Affiliate URL: %s", product.affiliate_url)
    logger.info("Found %d variation image(s) on disk: %s", len(image_paths), image_paths)
    assert len(image_paths) > 0, "No variation images found!"

    logger.info("=== STEP 2: Run Strategic Niche & EPC Opportunity Audit ===")
    audit = score_product_opportunity(product_data)
    logger.info("Opportunity Score: %s/10 (%s)", audit["composite_opportunity_score"], audit["epc_tier"])
    logger.info("Estimated EPC Range: %s | Commission: %s", audit["estimated_epc_range"], audit["typical_commission_rate"])
    logger.info("Recommended Pin Angles: %s", audit["recommended_pin_angles"])
    assert audit["composite_opportunity_score"] >= 7.0

    logger.info("=== STEP 3: Generate Elite Affiliate UGC Copy (Objections + Staged CTAs) ===")
    copy_data = await generate_bridge_copy(
        product_data=product_data,
        scene_data=scene_data,
        variations_count=len(image_paths),
    )
    logger.info("Headline: %s", copy_data.get("headline"))
    logger.info("Quick Verdict: %s", copy_data.get("quick_verdict"))
    logger.info("Objections FAQ: %d Q&As generated", len(copy_data.get("objections_faq", [])))
    logger.info("Staged CTAs: %s", copy_data.get("staged_ctas"))
    assert copy_data.get("quick_verdict") is not None
    assert len(copy_data.get("objections_faq", [])) >= 3
    assert copy_data.get("staged_ctas") is not None

    logger.info("=== STEP 4: Assemble Conversion-Optimized Lookbook HTML ===")
    slug, html_content, og_image_bytes = await generate_lookbook_html(
        job_id=JOB_ID,
        product_data=product_data,
        scene_data=scene_data,
        image_paths=image_paths,
        affiliate_url=product.affiliate_url,
        copy_data=copy_data,
    )
    logger.info("Generated HTML Lookbook: slug=%s, size=%d bytes, og_bytes=%d", slug, len(html_content), len(og_image_bytes))
    assert "schema.org" in html_content
    assert '"@type": "Product"' in html_content
    assert '"@type": "FAQPage"' in html_content
    assert "The Bottom Line" in html_content
    assert "Buyer Questions & Honest Answers" in html_content
    assert "swiper" in html_content
    assert "data:image/webp;base64," in html_content
    assert product.affiliate_url in html_content
    assert "FTC Disclosure" in html_content
    assert "og:image" in html_content
    assert len(og_image_bytes) > 0

    logger.info("=== STEP 5: Deploy to Vercel Production with Readiness Polling ===")
    deploy_url = await deploy_article_to_vercel(
        slug=slug,
        html_content=html_content,
        job_id=JOB_ID,
        og_image_bytes=og_image_bytes,
    )
    logger.info("Bridge Page Destination URL: %s", deploy_url)
    assert "https://" in deploy_url or "http://" in deploy_url

    logger.info("=== STEP 6: Test Local Serving & REST API Endpoint ===")
    import app.main
    transport = ASGITransport(app=app.main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as client:
        r = await client.get(f"/lookbooks/{JOB_ID}")
        logger.info("GET /lookbooks/%s -> HTTP %d (size: %d bytes)", JOB_ID, r.status_code, len(r.text))
        assert r.status_code == 200
        assert "The Bottom Line" in r.text
        assert "FAQPage" in r.text

        r_api = await client.post(f"/api/jobs/{JOB_ID}/lookbook")
        logger.info("POST /api/jobs/%s/lookbook -> HTTP %d: %s", JOB_ID, r_api.status_code, r_api.json())
        assert r_api.status_code == 200
        assert r_api.json().get("slug")
        assert r_api.json().get("pin_drafts_updated", 0) >= 0

    logger.info("=== STEP 7: Verify Database PinDraft Records Destination URL ===")
    async with async_session() as db:
        stmt = select(PinDraft).where(PinDraft.job_id == JOB_ID)
        result = await db.execute(stmt)
        drafts = result.scalars().all()
        for draft in drafts:
            logger.info("PinDraft %s destination_url: %s", draft.id, draft.destination_url)
            assert draft.destination_url == deploy_url

    logger.info("🎉 ALL ELITE AFFILIATE CONVERSION CHECKS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    asyncio.run(main())
