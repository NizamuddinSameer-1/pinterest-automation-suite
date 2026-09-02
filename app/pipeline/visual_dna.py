"""
Stage 2 — Visual DNA Extractor.

Separates stable photographic characteristics (reusable across products)
from variable content (changes per image) based on the reference analysis.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.pipeline.errors import PipelineStageError
from app.providers.llm import llm

logger = logging.getLogger("pre.pipeline.visual_dna")

SYSTEM_PROMPT = """\
You are the Visual DNA Architect for the Pinterest Realism Engine.

Your job: take a structured reference analysis and separate the
STABLE photographic characteristics (what makes ANY photo in this
style feel authentic) from the VARIABLE content (what changes per product).

STABLE DNA — characteristics to REUSE:
  • Camera behavior (smartphone, handheld, sharpness, noise level)
  • Lighting pattern (fluorescent, natural, mixed)
  • Composition style (imperfect framing, off-center, natural crop)
  • Environment feel (clutter level, background activity)
  • UGC authenticity markers (spontaneity, staging level)
  • Material rendering style (texture visibility, imperfection)
  • Realism markers (anti-studio, anti-cinematic, imperfection level)

VARIABLE CONTENT — what changes per image:
  • The specific product
  • Exact pose and positions
  • Object arrangement
  • Colors and patterns
  • Specific background objects

OUTPUT SCHEMA:
{
  "capture_identity": {
    "type": "string (e.g. casual_ugc_smartphone, styled_flat_lay, etc.)",
    "professionalism": "very_low|low|moderate|high",
    "spontaneity": "low|moderate|high|very_high"
  },
  "composition_dna": {
    "centering": "centered|slightly_off_center|off_center",
    "framing": "perfect|slightly_imperfect|imperfect",
    "crop": "tight|natural|wide",
    "camera_height": "floor|sitting|human_standing|elevated"
  },
  "environment_dna": {
    "real_world_context": true|false,
    "clutter": "none|low|moderate|moderate_to_high|high",
    "background_activity": "none|low|moderate|high"
  },
  "lighting_dna": {
    "source": "string",
    "contrast": "very_low|low|moderate|high",
    "warmth": "cool|neutral_to_cool|neutral|warm_neutral|warm"
  },
  "camera_dna": {
    "smartphone_behavior": true|false,
    "sharpness": "soft|moderate|sharp|very_sharp",
    "noise": "none|subtle|moderate|visible",
    "hdr": "none|restrained|moderate|aggressive"
  },
  "material_dna": {
    "texture_visibility": "low|moderate|high|very_high",
    "surface_imperfection": "none|low|moderate|high"
  },
  "realism_markers": {
    "imperfection_level": "none|low|moderate|high",
    "anti_studio": true|false,
    "anti_cinematic": true|false
  }
}

Return ONLY the JSON object. No extra text.
"""


async def extract_visual_dna(analysis: dict[str, Any]) -> dict[str, Any]:
    """
    Extract Visual DNA from a reference analysis.

    Args:
        analysis: The structured ReferenceAnalysis dict from Stage 1.

    Returns:
        VisualDNA dict with stable photographic characteristics.
    """
    logger.info("Extracting Visual DNA from analysis")

    prompt = (
        "Here is the structured reference analysis:\n\n"
        f"```json\n{json.dumps(analysis, indent=2)}\n```\n\n"
        "Extract the stable Visual DNA from this analysis. "
        "Return the VisualDNA JSON object only."
    )

    try:
        result = await llm.structured_output(prompt, system=SYSTEM_PROMPT)
    except Exception as e:
        logger.error("Visual DNA extraction failed: %s", e)
        raise PipelineStageError("visual_dna", f"LLM call failed: {e}") from e

    # A DNA dict without capture_identity is unusable downstream — the prompt
    # compiler would silently fill every dimension with generic defaults.
    required = ("capture_identity", "composition_dna", "lighting_dna", "camera_dna")
    missing = [k for k in required if not result.get(k)]
    if missing:
        raise PipelineStageError(
            "visual_dna",
            f"LLM returned a DNA object missing required keys: {', '.join(missing)}. "
            f"Got keys: {sorted(result.keys())}",
        )

    logger.info("Visual DNA extraction complete")
    return result
