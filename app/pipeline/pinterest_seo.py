"""
Pinterest SEO — generates Pinterest-optimized metadata for Pins.

Takes trend, product, scene context and generates:
  title, description, keywords, board suggestion.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.pipeline.errors import PipelineStageError
from app.providers.llm import llm

logger = logging.getLogger("pre.pipeline.pinterest_seo")

SYSTEM_PROMPT = """\
You are the Pinterest SEO specialist for the Pinterest Realism Engine.

Generate Pinterest-optimized metadata for an affiliate Pin.

RULES:
- Use natural, conversational language — write like a real Pinterest user
- NO keyword stuffing
- NO fake urgency ("LIMITED TIME!", "HURRY!")
- NO fake claims ("BEST EVER!", "MIRACLE!")
- NO clickbait or misleading descriptions
- Title should be 30-60 characters, hook-driven
- Description should be 100-300 characters, informative
- Keywords should be 5-10 relevant search terms
- Board suggestion should match the content category

Title patterns that work on Pinterest:
- "I Found The Cutest [Product] at [Store]"
- "[Season] [Product] You Need Right Now"
- "This [Product] Is Everything"
- "[Product] That Actually [Benefit]"

The bracketed slots are placeholders. Fill them from the PRODUCT, SCENE and
TREND given below — never carry over a season, holiday or emoji from these
examples if the input does not mention one.

OUTPUT SCHEMA:
{
  "title": "string — 30-60 chars, natural hook",
  "description": "string — 100-300 chars, informative",
  "keywords": ["string — 5-10 relevant terms"],
  "board_suggestion": "string — suggested board name"
}

Return ONLY the JSON object.
"""


async def generate_pin_seo(
    product: dict[str, Any],
    scene: dict[str, Any],
    trend_label: str | None = None,
) -> dict[str, Any]:
    """
    Generate Pinterest SEO metadata for a Pin.

    Returns:
        Dict with title, description, keywords, board_suggestion.
    """
    logger.info("Generating Pinterest SEO for product: %s", product.get("name"))

    prompt = (
        "Generate Pinterest SEO metadata for this affiliate Pin.\n\n"
        f"PRODUCT:\n```json\n{json.dumps(product, indent=2)}\n```\n\n"
        f"SCENE:\n```json\n{json.dumps(scene, indent=2)}\n```\n\n"
    )
    if trend_label:
        prompt += f"TREND: {trend_label}\n\n"

    try:
        result = await llm.structured_output(prompt, system=SYSTEM_PROMPT)
    except Exception as e:
        logger.error("Pinterest SEO generation failed: %s", e)
        raise PipelineStageError("pinterest_seo", f"LLM call failed: {e}") from e

    # No placeholder titles. The previous hardcoded fallback ("Look at this cute
    # X! 🎃" / board "Seasonal Trends & Aesthetic Finds") is why 20 pin drafts
    # shipped with generic Halloween copy that had nothing to do with the pin.
    if not result.get("title") or not result.get("description"):
        raise PipelineStageError(
            "pinterest_seo",
            f"LLM returned SEO without title/description. Got keys: {sorted(result.keys())}",
        )

    logger.info("Pinterest SEO generation complete")
    return result
