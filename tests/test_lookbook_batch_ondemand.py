"""
Tests for on-demand batch lookbook generation.

Verifies:
1. Generation outputs do NOT auto-create or auto-deploy lookbooks by default.
2. Pin drafts default to direct product affiliate URLs or smart redirect links.
3. Lookbook generation compiles all variations in the batch into ONE unified article.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.models import Base, Job, JobOutput, PinDraft, Product, Reference
from app.services.article_generator import generate_lookbook_html
from app.services.output_service import record_generation_outputs


@pytest.mark.asyncio
async def test_no_auto_lookbook_on_generation(tmp_path):
    """record_generation_outputs must NOT call lookbook generation/deploy when auto_create_lookbooks is False."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        product = Product(
            id="prod-test-1",
            asin="B0TEST1234",
            name="Aesthetic Ceramic Vase",
            affiliate_url="https://amzn.to/test-affiliate",
            product_url="https://amazon.com/dp/B0TEST1234",
            key_attributes=json.dumps(["Ceramic", "Modern", "Matte Finish"]),
        )
        ref = Reference(
            id="ref-test-1",
            image_path="test_ref.jpg",
            trend_label="coastal grandmillennial",
        )
        job = Job(
            id="job-test-1234",
            product_id=product.id,
            reference_id=ref.id,
            current_state="GENERATING",
            scene_json=json.dumps({"room_type": "living_room", "lighting": "soft natural"}),
        )
        db.add_all([product, ref, job])
        await db.commit()

        # Create 4 test image files
        img_paths = []
        for i in range(1, 5):
            p = tmp_path / f"flow_var_{i}.jpg"
            p.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 200)  # fake JPEG header
            img_paths.append(str(p))

        with (
            patch("app.pipeline.pinterest_seo.generate_pin_seo", new_callable=AsyncMock) as mock_seo,
            patch("app.services.article_generator.generate_lookbook_html", new_callable=AsyncMock) as mock_lb_gen,
            patch("app.services.vercel_publisher.deploy_article_to_vercel", new_callable=AsyncMock) as mock_deploy,
            patch("app.services.anti_ai_processor.postprocess_batch") as mock_anti_ai,
        ):
            mock_seo.return_value = {
                "title": "Aesthetic Ceramic Vase Guide",
                "description": "Stunning ceramic vase for modern aesthetic homes.",
                "keywords": ["vase", "decor"],
                "board_suggestion": "Home Decor Finds",
            }

            with (
                patch.object(settings, "auto_create_lookbooks", False),
                patch("app.services.colab_automator.upscale_images_via_colab", new_callable=AsyncMock),
            ):
                summary = await record_generation_outputs(
                    db=db,
                    job=job,
                    product=product,
                    ref=ref,
                    image_paths=img_paths,
                    prompt_version=None,
                    produced_by="flow_api",
                )
                await db.commit()

            # Verify lookbook generation and Vercel deploy were NEVER called
            mock_lb_gen.assert_not_called()
            mock_deploy.assert_not_called()

            # Verify pin drafts were created with direct affiliate URL
            pins_res = await db.execute(select(PinDraft).where(PinDraft.job_id == job.id))
            pins = pins_res.scalars().all()
            assert len(pins) == 4
            for p in pins:
                assert p.destination_url == "https://amzn.to/test-affiliate"
                assert not p.destination_url.endswith(".html")


@pytest.mark.asyncio
async def test_batch_lookbook_compiles_all_variations(tmp_path):
    """generate_lookbook_html must compile all 4 variations into ONE single lookbook article."""
    from PIL import Image

    img_paths = []
    for i in range(1, 5):
        p = tmp_path / f"flow_var_{i}.jpg"
        img = Image.new("RGB", (200, 300), color=(50 * i, 100, 150))
        img.save(p, "JPEG")
        img_paths.append(str(p))

    product_data = {
        "name": "Linen Duvet Cover",
        "brand": "PureLinen",
        "price": "89.99",
        "currency": "$",
        "category": "Home Bedding",
        "affiliate_url": "https://amzn.to/duvet-affiliate",
    }

    mock_copy = {
        "headline": "The Authentic Linen Duvet Guide",
        "subheadline": "Everyday perspective breakdown",
        "looks": [
            {"look_title": f"Perspective #{i}: Daily Practicality", "styling_advice": f"Advice {i}"}
            for i in range(1, 5)
        ],
        "quick_verdict": {"why_worth_it": "Breathable natural fabric", "best_for": "Year-round comfort"},
    }

    with patch("app.services.git_publisher.generate_catalog_index", new_callable=AsyncMock):
        slug, html_content, og_bytes = await generate_lookbook_html(
            job_id="job-batch-777",
            product_data=product_data,
            scene_data={"setting": "bedroom"},
            image_paths=img_paths,
            affiliate_url=product_data["affiliate_url"],
            copy_data=mock_copy,
        )

        assert "job-batc" in slug
        # One single HTML file containing all 4 looks
        assert "Perspective #1" in html_content
        assert "Perspective #2" in html_content
        assert "Perspective #3" in html_content
        assert "Perspective #4" in html_content
        # Multi-look section heading
        assert "Practical Perspectives &amp; Visual Breakdown" in html_content or "Practical Perspectives & Visual Breakdown" in html_content
