"""
Stage — Commerce Critic.

Evaluates generated commerce images for product clarity, prominence,
desire, scroll-stop, click intent, commercial composition and Pinterest fit.
Mirrors realism_critic.py but for commerce.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.providers.llm import llm

logger = logging.getLogger("pre.pipeline.commerce_critic")

SYSTEM_PROMPT = """\
You are the Commerce Critic for the Visual Commerce Engine.

You evaluate whether a generated image sells the product effectively on Pinterest.

You will receive:
  • The generated image to evaluate
  • Commerce DNA (hero product, hero prominence, must-show features, click reason)
  • Creative Concept (objective, visual hook, desire mechanism)
  • Product Truth (what the product MUST look like)

EVALUATE THE FOLLOWING COMMERCE AXES (return each as low | medium | high unless otherwise noted):

1. product_clarity — Is the product instantly recognizable? Can a viewer tell what is being sold within 1 second?
2. product_prominence — Does the hero product dominate the frame (60-80%) or is it lost in context/background?
3. visual_hook — Is the concept's visual_hook clearly visible and in focus (e.g., zipper, texture, silhouette)?
4. desire — Does the image create want? Does it make the viewer imagine owning/wearing/using the product?
5. scroll_stop — Would this thumb-stop a Pinterest scroller? Strong contrast, interesting composition, human element?
6. click_intent — Does the viewer have a reason to click to find/buy the exact product (not just admire the scene)?
7. commercial_composition — Is the framing/composition commercial (product-forward, clean, not overly artistic or cluttered)?
8. pinterest_fit — Does the image feel native to Pinterest (vertical, bright, inspirational, shoppable aesthetic)?

OUTPUT SCHEMA:
{
  "product_clarity": "low|medium|high",
  "product_prominence": "low|medium|high",
  "visual_hook": "string — what hook is visible or 'none'",
  "desire": "low|medium|high",
  "scroll_stop": "low|medium|high",
  "click_intent": "low|medium|high",
  "commercial_composition": "low|medium|high",
  "pinterest_fit": "low|medium|high",
  "reason": "string explaining overall commerce effectiveness"
}

Return ONLY the JSON object.
"""


async def critique_commerce(
    image_path: str,
    commerce_dna: dict[str, Any],
    concept: dict[str, Any],
    product_truth: dict[str, Any],
) -> dict[str, Any]:
    """
    Evaluate a generated commerce image for product clarity, prominence, desire, etc.

    Uses vision LLM to analyze the image with commerce context.

    Args:
        image_path: Path to generated image file.
        commerce_dna: Commerce DNA dict (hero_product, hero_prominence, must_show, etc.)
        concept: Creative concept dict (objective, visual_hook, etc.)
        product_truth: Product truth dict (must_preserve, must_not_invent, etc.)

    Returns:
        Commerce critique dict with product_clarity, product_prominence, visual_hook,
        desire, scroll_stop, click_intent, commercial_composition, pinterest_fit.
    """
    logger.info("Critiquing commerce image: %s", image_path)

    prompt = (
        f"COMMERCE DNA:\n```json\n{json.dumps(commerce_dna, indent=2)}\n```\n"
        f"CONCEPT:\n```json\n{json.dumps(concept, indent=2)}\n```\n"
        f"PRODUCT TRUTH:\n```json\n{json.dumps(product_truth, indent=2)}\n```\n\n"
        "Evaluate this generated image for commerce effectiveness. Return the critique JSON only."
    )

    result = await llm.analyze_image(prompt, image_path, system=SYSTEM_PROMPT)

    logger.info("Commerce critique complete — product_clarity: %s", result.get("product_clarity"))
    return result
