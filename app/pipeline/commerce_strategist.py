from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.pipeline.errors import PipelineStageError
from app.providers.llm import llm

logger = logging.getLogger("pre.pipeline.commerce_strategist")

STAGE_TIMEOUT_SECONDS = 45.0

SYSTEM_PROMPT = """You are the Commerce Strategist for the Pinterest Realism Engine. Your job is to turn product truth + visual DNA + reference analysis into Commerce DNA that gives every generated image a commercial reason to exist. You must identify the hero_product and decide its hero_prominence, choose a visual_hook that creates desire, list must_show features that cannot be hidden, and explain the click_reason why a viewer would click to find this exact product. Return ONLY JSON with commerce_dna {primary_objective, visual_hook, hero_product, hero_prominence, must_show, desire_mechanism, click_reason, context_role, product_clarity}"""


async def generate_commerce_dna(
    product: dict[str, Any],
    product_truth: dict[str, Any],
    visual_dna: dict[str, Any],
    reference_analysis: dict[str, Any] | None = None,
    trend_label: str | None = None,
) -> dict[str, Any]:
    prompt = (
        f"PRODUCT:\n```json\n{json.dumps(product, indent=2)}\n```\n"
        f"PRODUCT TRUTH:\n```json\n{json.dumps(product_truth, indent=2)}\n```\n"
        f"VISUAL DNA:\n```json\n{json.dumps(visual_dna, indent=2)}\n```"
    )
    if reference_analysis:
        prompt += f"\nREFERENCE ANALYSIS:\n```json\n{json.dumps(reference_analysis, indent=2)}\n```"
    if trend_label:
        prompt += f"\nTREND LABEL:\n{trend_label}"

    try:
        result = await asyncio.wait_for(
            llm.structured_output(prompt, system=SYSTEM_PROMPT),
            timeout=STAGE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as e:
        logger.error("Commerce strategist LLM timed out after %ds", STAGE_TIMEOUT_SECONDS)
        raise PipelineStageError(
            "commerce_strategist",
            f"Commerce strategist LLM timed out after {STAGE_TIMEOUT_SECONDS}s without replying.",
        ) from e
    except Exception as e:
        logger.error("Commerce strategist LLM call failed: %s", e)
        raise PipelineStageError("commerce_strategist", f"Commerce strategist LLM failed: {e}") from e

    dna = result.get("commerce_dna", result) if isinstance(result, dict) else {}
    required = [
        "primary_objective",
        "visual_hook",
        "hero_product",
        "hero_prominence",
        "must_show",
        "desire_mechanism",
        "click_reason",
        "context_role",
        "product_clarity",
    ]
    missing = [k for k in required if not dna.get(k)]
    if missing:
        logger.error("Commerce DNA reply is missing required fields: %s", missing)
        raise PipelineStageError(
            "commerce_strategist",
            f"Commerce DNA LLM reply was incomplete; missing keys: {missing}",
        )

    return dna
