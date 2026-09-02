from __future__ import annotations
import json, logging
from typing import Any
from app.pipeline.errors import PipelineStageError
from app.providers.llm import llm
logger = logging.getLogger("pre.pipeline.commerce_strategist")
SYSTEM_PROMPT = """You are the Commerce Strategist for the Pinterest Realism Engine. Your job is to turn product truth + visual DNA + reference analysis into Commerce DNA that gives every generated image a commercial reason to exist. You must identify the hero_product and decide its hero_prominence, choose a visual_hook that creates desire, list must_show features that cannot be hidden, and explain the click_reason why a viewer would click to find this exact product. Return ONLY JSON with commerce_dna {primary_objective, visual_hook, hero_product, hero_prominence, must_show, desire_mechanism, click_reason, context_role, product_clarity}"""
async def generate_commerce_dna(product, product_truth, visual_dna, reference_analysis=None, trend_label=None):
    prompt = f"PRODUCT:\n```json\n{json.dumps(product, indent=2)}\n```\nPRODUCT TRUTH:\n```json\n{json.dumps(product_truth, indent=2)}\n```\nVISUAL DNA:\n```json\n{json.dumps(visual_dna, indent=2)}\n```"
    if reference_analysis:
        prompt += f"\nREFERENCE ANALYSIS:\n```json\n{json.dumps(reference_analysis, indent=2)}\n```"
    # Deterministic fallback so preview-prompt never hangs on "Running scene director..."
    fallback = {
        "primary_objective": "product_desire",
        "visual_hook": product.get("name", "product")[:40],
        "hero_product": product.get("name", "product").lower().replace(" ", "_")[:30],
        "hero_prominence": "high",
        "must_show": (product_truth.get("must_preserve") or ["product"])[:5],
        "desire_mechanism": ["premium appearance", "wearability"],
        "click_reason": "viewer wants to find the exact product",
        "context_role": "supporting",
        "product_clarity": "high",
    }
    try:
        import asyncio as _aio
        result = await _aio.wait_for(llm.structured_output(prompt, system=SYSTEM_PROMPT), timeout=8)
    except _aio.TimeoutError:
        logger.warning("Commerce strategist LLM timed out after 8s, using fallback")
        return fallback
    except Exception as e:
        logger.warning("Commerce strategist LLM failed (%s), using fallback", e)
        return fallback
    dna = result.get("commerce_dna", result) if isinstance(result, dict) else {}
    required = ["primary_objective","visual_hook","hero_product","hero_prominence","must_show","desire_mechanism","click_reason","context_role","product_clarity"]
    missing = [k for k in required if not dna.get(k)]
    if missing:
        logger.warning("Commerce DNA missing %s, filling fallback", missing)
        for k in missing:
            dna[k] = fallback[k]
    return dna
