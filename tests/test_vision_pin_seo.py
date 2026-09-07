"""
Tests for Vision-Aware Pinterest Pin Generation.

Verifies:
1. generate_pin_seo calls vision when an image_path exists.
2. generate_batch_pins_seo produces 100% unique titles across all batch variations (no (Look #2) duplicates).
3. Fallback to text prompt preserves distinct hook rotation.
4. record_generation_outputs persists unique, photo-grounded titles and descriptions to SQLite PinDraft records.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.models import Base, Job, PinDraft, Product, Reference
from app.pipeline.pinterest_seo import (
    FRAMEWORKS,
    generate_batch_pins_seo,
    generate_pin_seo,
)
from app.services.output_service import record_generation_outputs


@pytest.mark.asyncio
async def test_generate_pin_seo_vision_grounded(tmp_path):
    """When image_path exists, generate_pin_seo calls analyze_image with VISION_PIN_SEO_SYSTEM."""
    img_file = tmp_path / "test_var_1.jpg"
    img_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

    product = {
        "name": "Ceramic Fluted Vase",
        "brand": "NordicHome",
        "price": "34.99",
        "category": "Home Decor",
    }
    scene = {"setting": "bright living room", "lighting": "morning sunlight"}

    mock_vision_return = {
        "title": "Honestly Didn't Expect This Ceramic Vase to Look This Good",
        "description": "Morning sun highlights the raw stoneware texture and fluted silhouette on this coffee table setup. #HomeDecor #AmazonFinds",
        "keywords": ["ceramic vase", "fluted stoneware", "minimalist decor"],
        "board_suggestion": "Aesthetic Living Room Decor",
    }

    with patch("app.pipeline.pinterest_seo.content_llm.analyze_image", new_callable=AsyncMock) as mock_vision:
        mock_vision.return_value = mock_vision_return

        result = await generate_pin_seo(
            product=product,
            scene=scene,
            trend_label="warm minimalism",
            image_path=img_file,
            variation_index=1,
            total_variations=4,
        )

        assert mock_vision.called
        call_kwargs = mock_vision.call_args.kwargs
        assert str(img_file) in call_kwargs["image_path"]
        assert "The Skeptical Micro-Review" in call_kwargs["system"]
        assert "[Aesthetic Name] + [Item Type] + [Amazon Signal/Benefit] + [Year/Modifier]" in call_kwargs["system"]
        assert "2-SENTENCE DESCRIPTION RULES" in call_kwargs["system"]
        assert "Target Year: 2026" in call_kwargs["prompt"]
        assert result["title"] == "Honestly Didn't Expect This Ceramic Vase to Look This Good"
        assert "(Look #" not in result["title"]
        assert "Morning sun highlights" in result["description"]


@pytest.mark.asyncio
async def test_generate_batch_pins_seo_unique_titles(tmp_path):
    """generate_batch_pins_seo must produce distinct titles for all 4 images with no duplicates."""
    img_paths = []
    for i in range(1, 5):
        p = tmp_path / f"var_{i}.jpg"
        p.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
        img_paths.append(str(p))

    product = {
        "name": "Slim Rolling Bar Cart",
        "brand": "VASAGLE",
        "price": "59.99",
        "category": "Furniture",
    }
    scene = {"setting": "compact dining nook"}

    def vision_side_effect(prompt, image_path, system, temperature=0.6):
        if "var_1" in image_path:
            return {
                "title": "Honestly Didn't Expect This Bar Cart to Fit My Nook",
                "description": "Angle 1 shows the 11.8-inch depth fitting perfectly against the wall. #SmallSpace #BarCart",
                "keywords": ["bar cart", "small space furniture"],
                "board_suggestion": "Home Bar Ideas",
            }
        elif "var_2" in image_path:
            return {
                "title": "Finally Found a Bar Cart That Actually Has Zero Wobble",
                "description": "Close perspective on the gold steel frame and tempered glass shelves. #AmazonHome #HomeBar",
                "keywords": ["gold bar cart", "stable cart"],
                "board_suggestion": "Home Bar Ideas",
            }
        elif "var_3" in image_path:
            return {
                "title": "What This Gold Bar Cart Looks Like in Daily Living",
                "description": "Styled with glassware and cocktail shakers under warm evening lighting. #CocktailStation",
                "keywords": ["bar styling", "cocktail cart"],
                "board_suggestion": "Home Bar Ideas",
            }
        else:
            return {
                "title": "The Exact Neo-Deco Aesthetic for Your Apartment Corner",
                "description": "Full room lifestyle perspective showcasing sleek casters and compact footprint. #NeoDeco",
                "keywords": ["neo deco", "apartment living"],
                "board_suggestion": "Home Bar Ideas",
            }

    with patch("app.pipeline.pinterest_seo.content_llm.analyze_image", side_effect=vision_side_effect):
        results = await generate_batch_pins_seo(
            product=product,
            scene=scene,
            image_paths=img_paths,
            trend_label="neo deco",
        )

        assert len(results) == 4
        titles = [r["title"] for r in results]
        # Every title is 100% distinct
        assert len(set(titles)) == 4
        for t in titles:
            assert "(Look #" not in t
            assert len(t) <= 60


@pytest.mark.asyncio
async def test_fallback_when_image_missing():
    """When an image path does not exist, it falls back to text prompt with rotated framework."""
    product = {"name": "Linen Duvet Set"}
    scene = {"setting": "bedroom"}

    mock_text_return = {
        "title": "Finally Found a Linen Duvet That Stays Cool All Night",
        "description": "Washed French flax linen that gets softer with every wash cycle. #LinenBedding #CozyHome",
        "keywords": ["linen duvet", "breathable bedding"],
        "board_suggestion": "Bedding Essentials",
    }

    with (
        patch("app.pipeline.pinterest_seo.content_llm.analyze_image", new_callable=AsyncMock) as mock_vision,
        patch("app.pipeline.pinterest_seo.content_llm.structured_output", new_callable=AsyncMock) as mock_text,
    ):
        mock_text.return_value = mock_text_return

        result = await generate_pin_seo(
            product=product,
            scene=scene,
            image_path="/nonexistent/path/var_2.jpg",
            variation_index=2,
            total_variations=4,
        )

        mock_vision.assert_not_called()
        assert mock_text.called
        call_kwargs = mock_text.call_args.kwargs
        assert "The Practical Problem-Solver" in call_kwargs["system"]
        assert result["title"] == "Finally Found a Linen Duvet That Stays Cool All Night"
        assert "(Look #" not in result["title"]


@pytest.mark.asyncio
async def test_record_generation_outputs_persists_unique_pins(tmp_path):
    """record_generation_outputs persists 4 distinct PinDraft records with unique titles and descriptions."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/test_unique.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        product = Product(
            id="prod-seo-test",
            asin="B0UNIQUEASIN",
            name="Textured Ceramic Planter",
            affiliate_url="https://amzn.to/planter",
            product_url="https://amazon.com/dp/B0UNIQUEASIN",
            key_attributes=json.dumps(["Ceramic", "Textured", "Indoor Planter"]),
        )
        ref = Reference(
            id="ref-seo-test",
            image_path="test_ref.jpg",
            trend_label="biophilic living",
        )
        job = Job(
            id="job-seo-test-999",
            product_id=product.id,
            reference_id=ref.id,
            current_state="GENERATING",
            scene_json=json.dumps({"setting": "sunlit windowsill"}),
        )
        db.add_all([product, ref, job])
        await db.commit()

        img_paths = []
        for i in range(1, 5):
            p = tmp_path / f"planter_var_{i}.jpg"
            p.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 150)
            img_paths.append(str(p))

        mock_batch_results = [
            {
                "title": f"Planter Perspective #{i} Unique Hook Title",
                "description": f"Observational description for planter angle #{i} in sunlight. #Plants",
                "keywords": [f"keyword-{i}", "ceramic planter"],
                "board_suggestion": "Plant Decor",
            }
            for i in range(1, 5)
        ]

        with (
            patch("app.pipeline.pinterest_seo.generate_batch_pins_seo", new_callable=AsyncMock) as mock_batch_seo,
            patch("app.services.anti_ai_processor.postprocess_batch"),
            patch("app.services.colab_automator.upscale_images_via_colab", new_callable=AsyncMock),
            patch.object(settings, "auto_create_lookbooks", False),
        ):
            mock_batch_seo.return_value = mock_batch_results

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

        pins_res = await db.execute(select(PinDraft).where(PinDraft.job_id == job.id).order_by(PinDraft.created_at))
        pins = pins_res.scalars().all()
        assert len(pins) == 4

        # Verify NO pin has '(Look #' in its title
        for idx, pin in enumerate(pins, 1):
            assert "(Look #" not in pin.title
            assert pin.title == f"Planter Perspective #{idx} Unique Hook Title"
            assert f"planter angle #{idx}" in pin.description
            assert f"keyword-{idx}" in pin.keywords

        # Verify summary contains unique variation titles
        for idx, var in enumerate(summary["variations"], 1):
            assert var["title"] == f"Planter Perspective #{idx} Unique Hook Title"
