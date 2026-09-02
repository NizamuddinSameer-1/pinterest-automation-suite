# app/pipeline/creative_concepts.py
from __future__ import annotations
import asyncio
import json
import logging
from typing import Any
from app.pipeline.errors import PipelineStageError
from app.providers.llm import llm
logger = logging.getLogger("pre.pipeline.creative_concepts")
SYSTEM_PROMPT = """You are the Creative Concept Generator... Return {"concepts":[{concept_id, objective, visual_hook, must_show, desire_mechanism, click_reason, hero_prominence, creative_format, context_role}]} 4-7 distinct concepts, each with different creative_format and objective."""
async def generate_concepts(commerce_dna, product, product_truth, reference_analysis=None, count=4):
    prompt = f"COMMERCE DNA:\n```json\n{json.dumps(commerce_dna, indent=2)}\n```\nPRODUCT:\n```json\n{json.dumps(product, indent=2)}\n```"
    fallback = [
        {"concept_id": "A", "objective": "product_desire", "visual_hook": "hero fit", "must_show": commerce_dna.get("must_show", [])[:3], "desire_mechanism": ["premium appearance"], "click_reason": "find exact product", "hero_prominence": "high", "creative_format": "mirror_pov", "context_role": "supporting"},
        {"concept_id": "B", "objective": "product_detail", "visual_hook": "texture", "must_show": commerce_dna.get("must_show", [])[:2], "desire_mechanism": ["material quality"], "click_reason": "see details", "hero_prominence": "high", "creative_format": "macro_detail", "context_role": "supporting"},
        {"concept_id": "C", "objective": "lifestyle_use", "visual_hook": "street", "must_show": commerce_dna.get("must_show", [])[:2], "desire_mechanism": ["wearability"], "click_reason": "imagine wearing", "hero_prominence": "high", "creative_format": "outdoor_use", "context_role": "supporting"},
        {"concept_id": "D", "objective": "discovery", "visual_hook": "store rack", "must_show": commerce_dna.get("must_show", [])[:2], "desire_mechanism": ["discovery"], "click_reason": "found it", "hero_prominence": "high", "creative_format": "discovery", "context_role": "supporting"},
    ]
    try:
        result = await asyncio.wait_for(llm.structured_output(prompt, system=SYSTEM_PROMPT), timeout=8)
    except asyncio.TimeoutError:
        logger.warning("Creative concepts LLM timed out after 8s, using fallback 4 concepts")
        return fallback[:count]
    except Exception as e:
        logger.warning("Creative concepts LLM failed (%s), using fallback", e)
        return fallback[:count]
    concepts = result.get("concepts", []) if isinstance(result, dict) else []
    if len(concepts) < 4:
        logger.warning("Creative concepts: expected 4-7, got %s, using fallback", len(concepts))
        return fallback[:count]
    seen = set()
    deduped = []
    for c in concepts:
        if c.get("creative_format") not in seen:
            seen.add(c.get("creative_format")); deduped.append(c)
    return deduped[:7] if deduped else fallback[:count]
