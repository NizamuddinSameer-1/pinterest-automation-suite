# app/pipeline/creative_concepts.py
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.pipeline.errors import PipelineStageError
from app.providers.llm import llm

logger = logging.getLogger("pre.pipeline.creative_concepts")

STAGE_TIMEOUT_SECONDS = 45.0

SYSTEM_PROMPT = """You are the Creative Concept Generator for the Pinterest Realism Engine. Return {"concepts":[{concept_id, objective, visual_hook, must_show, desire_mechanism, click_reason, hero_prominence, creative_format, context_role}]} with 4 to 7 distinct concepts, each with different creative_format and objective matched to the product class."""


async def generate_concepts(
    commerce_dna: dict[str, Any],
    product: dict[str, Any],
    product_truth: dict[str, Any],
    reference_analysis: dict[str, Any] | None = None,
    count: int = 4,
) -> list[dict[str, Any]]:
    prompt = (
        f"COMMERCE DNA:\n```json\n{json.dumps(commerce_dna, indent=2)}\n```\n"
        f"PRODUCT:\n```json\n{json.dumps(product, indent=2)}\n```\n"
        f"PRODUCT TRUTH:\n```json\n{json.dumps(product_truth, indent=2)}\n```"
    )
    if reference_analysis:
        prompt += f"\nREFERENCE ANALYSIS:\n```json\n{json.dumps(reference_analysis, indent=2)}\n```"

    try:
        result = await asyncio.wait_for(
            llm.structured_output(prompt, system=SYSTEM_PROMPT),
            timeout=STAGE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as e:
        logger.error("Creative concepts LLM timed out after %ds", STAGE_TIMEOUT_SECONDS)
        raise PipelineStageError(
            "creative_concepts",
            f"Creative concepts LLM timed out after {STAGE_TIMEOUT_SECONDS}s without replying.",
        ) from e
    except Exception as e:
        logger.error("Creative concepts LLM failed: %s", e)
        raise PipelineStageError("creative_concepts", f"Creative concepts generation failed: {e}") from e

    concepts = result.get("concepts", []) if isinstance(result, dict) else []
    if len(concepts) < 4:
        logger.error("Creative concepts: expected at least 4, got %d", len(concepts))
        raise PipelineStageError(
            "creative_concepts",
            f"Expected at least 4 concepts from LLM, but received {len(concepts)}.",
        )

    seen = set()
    deduped = []
    for c in concepts:
        fmt = c.get("creative_format")
        if fmt not in seen:
            seen.add(fmt)
            deduped.append(c)

    return deduped[:7] if deduped else concepts[:count]
