"""
Stage 1 — Reference Analyst.

Sends a reference image to Gemini vision and extracts structured
photographic analysis across 10 dimensions: subject, scene, camera,
composition, lighting, materials, environment, UGC signals, psychology,
and the product facts.

The tenth dimension is newer than the rest and exists for one reason. Nine
dimensions describe the *photograph*; none of them described the *thing in it*, so
an operator who uploaded a picture of two glowing ghost lamps had no way to turn
that picture into something the pipeline could sell — the SUBJECT and PRODUCT TRUTH
lines can only come from a product record, and the nearest one said "Pumpkin Fleece
Pajama Pants". `product_facts` is what `app.services.product_drafter` reads to draft
a product from the photograph itself. Generation is text-only (Google Flow never
receives the reference image), so these facts have to be written in words or they
cannot reach the render at all.
"""

from __future__ import annotations

import logging
from typing import Any

from app.pipeline.errors import PipelineStageError
from app.providers.llm import llm

logger = logging.getLogger("pre.pipeline.reference_analyst")

SYSTEM_PROMPT = """\
You are the Reference Analyst for the Pinterest Realism Engine.

Your job: analyze a Pinterest reference image and extract structured
photographic information that explains WHY this image feels like a
genuine, real photograph (or doesn't).

You must analyze ONLY what can reasonably be inferred from the image.

ANALYSIS DIMENSIONS:

1. SUBJECT — primary category, secondary category, visible objects,
   product visibility (high/medium/low), human presence (full/partial/none)

2. SCENE — scene type (retail_discovery/closeup_ugc/wear_test/haul/etc.),
   location (be honest if unknown), context, capture_motivation
   (WHY was this photo taken?)

3. CAMERA — device class (smartphone/dslr/unknown + confidence),
   distance (close/medium/far), perspective (natural/elevated/low),
   depth of field (shallow/moderate/deep), sharpness (natural/sharp/soft)

4. COMPOSITION — framing (tight/medium/wide), subject position
   (centered/slightly_off_center/off_center), symmetry (low/moderate/high),
   crop (natural/tight/standard)

5. LIGHTING — source (natural_window/retail_fluorescent/outdoor/flash/mixed),
   hardness (soft/medium/hard), direction (front/front_side/side/back),
   white balance (warm/warm_neutral/neutral/cool), exposure (under/natural/over)

6. MATERIALS — primary textures present, texture visibility
   (low/medium/high), imperfection level (none/low/medium/high)

7. ENVIRONMENT — clutter level (none/low/moderate/high),
   background detail (low/medium/high), background blur (none/low/moderate/heavy)

8. UGC SIGNALS — handheld (bool), spontaneous (bool),
   staging level (none/low/moderate/high)

9. PSYCHOLOGY — pick the top 3 hooks from: discovery, curiosity, novelty,
   identity, inspiration, seasonal_urgency, transformation, value,
   collection, problem_solution

10. PRODUCT FACTS — the physical truth of the main object itself, as opposed to
   the photograph of it. This is the only dimension that describes the *thing*:
   what it is, its visible colours, its materials, its shape, and the details that
   would let someone recognise it again. Describe only what is visible. If the
   image has no single main object (a flat-lay of many unrelated items, a pure
   landscape), set "is_single_product": false and leave the lists empty.

RULES:
- Include a confidence level (high/medium/low) for uncertain fields.
- Never hallucinate exact metadata (camera model, store name) that
  cannot be inferred.
- Return your analysis as a single JSON object matching the schema below.

OUTPUT SCHEMA:
{
  "subject": {
    "primary_category": "string",
    "secondary_category": "string or null",
    "objects": ["string"],
    "product_visibility": "high|medium|low",
    "human_presence": "full|partial|none"
  },
  "scene": {
    "type": "string",
    "location": {"value": "string", "confidence": "high|medium|low"},
    "context": "string",
    "capture_motivation": "string"
  },
  "camera": {
    "device_class": {"value": "string", "confidence": "high|medium|low"},
    "distance": "string",
    "perspective": "string",
    "depth_of_field": "string",
    "sharpness": "string"
  },
  "composition": {
    "framing": "string",
    "subject_position": "string",
    "symmetry": "string",
    "crop": "string"
  },
  "lighting": {
    "source": "string",
    "hardness": "string",
    "direction": "string",
    "white_balance": "string",
    "exposure": "string"
  },
  "materials": {
    "primary_textures": ["string"],
    "texture_visibility": "string",
    "imperfection_level": "string"
  },
  "environment": {
    "clutter_level": "string",
    "background_detail": "string",
    "background_blur": "string"
  },
  "ugc_signals": {
    "handheld": true|false,
    "spontaneous": true|false,
    "staging_level": "string"
  },
  "psychology": {
    "primary_hooks": ["string", "string", "string"]
  },
  "product_facts": {
    "is_single_product": true|false,
    "product_name_guess": "string — a short, plain shop-style name",
    "product_type": "string — what kind of object it is, in ordinary words",
    "visible_colors": ["string"],
    "visible_materials": ["string"],
    "shape_or_silhouette": "string",
    "distinguishing_features": ["string"],
    "text_or_branding_visible": ["string"],
    "confidence": "high|medium|low"
  }
}
"""

USER_PROMPT = """\
Analyze this Pinterest reference image. Extract its photographic DNA — \
explain what makes this image feel like a genuine photograph (or not). \
Return structured JSON only, no other text.
"""


async def analyze_reference(image_path: str) -> dict[str, Any]:
    """
    Run vision analysis on a reference image.

    Args:
        image_path: Absolute or relative path to the image file.

    Returns:
        Structured ReferenceAnalysis dict.
    """
    logger.info("Analyzing reference image: %s", image_path)
    result = await llm.analyze_image(
        prompt=USER_PROMPT,
        image_path=image_path,
        system=SYSTEM_PROMPT,
    )

    # visual_dna consumes this analysis; an empty or off-schema reply must not
    # be persisted as an analysis row.
    if not result.get("camera") and not result.get("lighting") and not result.get("subject"):
        raise PipelineStageError(
            "reference_analyst",
            f"Vision model returned no recognisable analysis. Got keys: {sorted(result.keys())}",
        )

    logger.info("Reference analysis complete")
    return result
