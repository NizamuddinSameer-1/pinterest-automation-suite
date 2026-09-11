"""
Stage 3 — Scene Director (updated).

What changed vs the previous version
──────────────────────────────────────
1.  `scene_variation_matrix.variation_for()` is now called inside
    `_deterministic_scene`. It returns six extra fields that are
    appended to the scene dict and forwarded to the compiler:

        camera_angle      — specific lens position and height
        lighting_setup    — quality, direction, colour temperature
        color_grading     — post treatment / film look
        scene_environment — exact environment and surroundings
        style_aesthetic   — visual language / editorial genre
        creative_context  — Pinterest save-reason / viewer motivation

    Every axis is seeded independently from the job identity string
    (product name + concept_id + class key), so:
      • The same job always regenerates identically (reproducible).
      • Sibling concepts for the same product differ on all six axes
        simultaneously — not just in which format was chosen.
      • Different product classes pull from different option pools,
        so clothes get clothes-specific situations, toys get toy-
        specific situations, etc.

2.  `_build_user_prompt` receives the variation dict and appends a
    FLOW VARIATION block to the LLM prompt in Mode 2. The LLM is
    asked to honour these six axes when composing the scene.

3.  `_scene_problems` is unchanged — the validation logic is still
    class-based and format-whitelist-driven.

4.  `generate_scene` return value now always includes the six
    variation fields (filled by taxonomy in Mode 1, honoured by the
    LLM in Mode 2, and attached to the scene dict in both paths).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any

from app.config import settings
from app.pipeline.errors import PipelineStageError
from app.pipeline.product_taxonomy import (
    Classification,
    classify_product,
    director_brief,
    format_is_plausible,
)
from app.pipeline.scene_variation_matrix import variation_for  # ← NEW
from app.providers.llm import llm

logger = logging.getLogger("pre.pipeline.scene_director")

# ─────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
You are the Scene Director for the Pinterest Realism Engine.

Your job: decide WHAT IS HAPPENING in the photograph and WHY it was taken.

You receive:
  • Visual DNA — the photographic style to maintain
  • Product — what product this image features
  • Product Class — the kind of object it is, and what is physically believable for it
  • Product Truth — what MUST and MUST NOT appear
  • Reference reading — how the reference image itself was classified (if available)
  • Trend context — seasonal/thematic context
  • Flow Variation — six pre-selected variation axes you MUST honour

You must create a BELIEVABLE SCENE — a scenario that a real person
would actually photograph and share on Pinterest.

The PRODUCT CLASS block in the user message is binding. It lists the only creative
formats that make sense for this object, the scale it should be photographed at,
the surfaces and locations it plausibly sits on, and the states it can be in. Do
not import a format, a location or a pose from a different kind of product.

FLOW VARIATION BLOCK (mandatory — honour all six axes):
  The user message contains a FLOW VARIATION block with six fields. You must
  incorporate all six into the scene you produce. They have already been chosen
  to be believable for this product class. Do not ignore or override them.

  camera_angle      — use this as the camera position and lens feel
  lighting_setup    — use this as the primary light source and mood
  color_grading     — reference this for the post-treatment tone
  scene_environment — use this as the physical setting
  style_aesthetic   — let this govern the editorial genre
  creative_context  — let this be the capture_motivation

MANDATORY FIELD: capture_motivation
  You MUST answer: "Why would a real person take this photo?"
  Derive it directly from the creative_context in the FLOW VARIATION block.

OUTPUT SCHEMA:
{
  "creative_format": "one of the formats listed in the PRODUCT CLASS block",
  "capture_motivation": "string — WHY this photo was taken (MANDATORY, from creative_context)",
  "location": "string — specific, believable location (from scene_environment)",
  "action": "string — what is happening",
  "camera_position": "string — from camera_angle",
  "framing": "macro|tight|medium|wide",
  "product_state": "string — the product's condition in this photo",
  "surface": "string — what the product is resting on",
  "human_presence": "full|partial_hand_arm|partial_body|none",
  "background_elements": ["string"],
  "staging_level": "none|minimal|moderate",
  "camera_angle": "string — echo the camera_angle from FLOW VARIATION",
  "lighting_setup": "string — echo the lighting_setup from FLOW VARIATION",
  "color_grading": "string — echo the color_grading from FLOW VARIATION",
  "scene_environment": "string — echo the scene_environment from FLOW VARIATION",
  "style_aesthetic": "string — echo the style_aesthetic from FLOW VARIATION",
  "creative_context": "string — echo the creative_context from FLOW VARIATION"
}

RULES:
- creative_format MUST come from the PRODUCT CLASS block
- human_presence MUST be one of the values the class block allows
- Honour ALL SIX fields from the FLOW VARIATION block
- The scene must be PLAUSIBLE — something a real person would actually do
- Return ONLY the JSON object. No extra text.
"""


# ─────────────────────────────────────────────────────────────────────
def _build_user_prompt(
    visual_dna: dict[str, Any],
    product: dict[str, Any],
    product_truth: dict[str, Any],
    classification: Classification,
    reference_analysis: dict[str, Any] | None,
    trend_label: str | None,
    commerce_dna: dict[str, Any] | None = None,
    concept: dict[str, Any] | None = None,
    variation: dict[str, str] | None = None,  # NEW
) -> str:
    """Assemble the user message, class block first so it frames everything after."""
    parts = [
        "Generate a believable scene for this product.",
        director_brief(classification.product_class, classification),
        f"VISUAL DNA:\n```json\n{json.dumps(visual_dna, indent=2)}\n```",
        f"PRODUCT:\n```json\n{json.dumps(product, indent=2)}\n```",
        f"PRODUCT TRUTH:\n```json\n{json.dumps(product_truth, indent=2)}\n```",
    ]

    if commerce_dna:
        parts.append(f"COMMERCE DNA:\n```json\n{json.dumps(commerce_dna, indent=2)}\n```")
    if concept:
        parts.append(f"CREATIVE CONCEPT:\n```json\n{json.dumps(concept, indent=2)}\n```")
        if "Creative Concept" not in parts[-1]:
            parts[-1] += "\nCreative Concept"

    if isinstance(reference_analysis, dict):
        digest = {
            key: reference_analysis.get(key)
            for key in ("subject", "scene", "psychology")
            if reference_analysis.get(key)
        }
        if digest:
            parts.append(
                "REFERENCE READING (how the reference image itself was classified — "
                "match its intent, not its exact composition):\n"
                f"```json\n{json.dumps(digest, indent=2)}\n```"
            )

    if trend_label:
        parts.append(f"TREND CONTEXT: {trend_label}")

    # ─ NEW: inject variation block into LLM prompt ────────────────────────
    if variation:
        var_lines = "\n".join(f"  {k}: {v}" for k, v in variation.items())
        parts.append(
            "FLOW VARIATION (mandatory — honour all six axes in the scene you produce):\n"
            + var_lines
        )

    return "\n\n".join(parts)


def _scene_problems(scene: dict[str, Any], classification: Classification) -> list[str]:
    """Everything wrong with a returned scene, as sentences the LLM can act on."""
    klass = classification.product_class
    problems: list[str] = []

    if not scene.get("capture_motivation"):
        problems.append("capture_motivation is missing; it is mandatory.")

    ok, why = format_is_plausible(str(scene.get("creative_format") or ""), klass)
    if not ok:
        problems.append(f"{why}.")

    human = str(scene.get("human_presence") or "")
    if human and human not in klass.human_presence:
        problems.append(
            f"human_presence {human!r} is not allowed for a {klass.noun}; "
            f"use one of: {', '.join(klass.human_presence)}."
        )

    return problems


def _seed_for(seed_key: str, axis: str) -> int:
    return int.from_bytes(
        hashlib.sha256(f"{seed_key}|{axis}".encode("utf-8")).digest()[:8], "big"
    )


def _rotate(items: tuple[str, ...], seed_key: str, axis: str, default: str) -> str:
    if not items:
        return default
    return items[_seed_for(seed_key, axis) % len(items)]


def _deterministic_scene(
    klass: Any,
    product: dict[str, Any],
    product_truth: dict[str, Any],
    commerce_dna: dict[str, Any] | None,
    concept: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Direct a scene from the taxonomy menu, without an LLM.

    Now extended with six variation axes from scene_variation_matrix.
    The variation axes are seeded independently per axis, so every
    sibling concept within a job lands on a different camera/lighting/
    grading/environment/style/context combination.

    Variation axis options are class-specific: clothes get apparel
    options, toys get toy options, tech gets tech options, etc.
    This is the fix for 'every pin looks like a clothing pin'.
    """
    name = str(product.get("name") or "product")
    concept = concept or {}
    commerce_dna = commerce_dna or {}
    concept_id = str(concept.get("concept_id") or concept.get("creative_format") or "A")
    seed_key = f"{name}|{concept_id}|{klass.key}"

    # ─ existing format selection logic (unchanged) ────────────────────────
    fmt = str(concept.get("creative_format") or "")
    if fmt and fmt not in klass.formats:
        logger.info(
            "Concept format %r is not believable for a %s (class %s); choosing from "
            "the taxonomy menu instead", fmt, klass.noun, klass.key,
        )
        fmt = ""
    if not fmt:
        fmt = _rotate(klass.formats, seed_key, "format", "styled_surface")

    product_state = _rotate(klass.product_states, seed_key, "state", "in use")

    must_show = list(concept.get("must_show") or commerce_dna.get("must_show") or [])
    if not must_show and product_truth:
        must_show = list(product_truth.get("must_preserve") or [])
    hook = str(concept.get("visual_hook") or commerce_dna.get("visual_hook") or "")
    if must_show:
        shown = ", ".join(str(m) for m in must_show[:2])
        action = f"{name} {product_state}, shown with {shown}"
    elif hook:
        action = f"{name} {product_state}, {hook}"
    else:
        action = f"Product {product_state}"

    surfaces = list(klass.surfaces)
    if surfaces:
        start = _seed_for(seed_key, "background") % len(surfaces)
        background = [surfaces[(start + i) % len(surfaces)] for i in range(min(2, len(surfaces)))]
    else:
        background = ["soft window light"]

    # ─ NEW: pull all six variation axes from the category matrix ─────────
    # variation_for() uses the same sha256-seeded rotation internally,
    # but seeds each axis separately so they don't move in lockstep.
    # It falls back to the generic matrix for any unrecognised class key.
    var = variation_for(klass.key, seed_key)

    return {
        # ─ existing fields ───────────────────────────────────────────
        "creative_format":    fmt,
        "capture_motivation": var["creative_context"],          # ← now from matrix
        "location":           _rotate(klass.locations, seed_key, "location", "in a sunlit room"),
        "action":             action,
        "camera_position":    var["camera_angle"],               # ← now from matrix
        "framing":            klass.framing,
        "product_state":      product_state,
        "surface":            _rotate(klass.surfaces, seed_key, "surface", "table"),
        "human_presence":     _rotate(klass.human_presence, seed_key, "human", "none"),
        "background_elements": background,
        "staging_level":      "moderate",
        # ─ six new variation fields ────────────────────────────────────
        "camera_angle":       var["camera_angle"],
        "lighting_setup":     var["lighting_setup"],
        "color_grading":      var["color_grading"],
        "scene_environment":  var["scene_environment"],
        "style_aesthetic":    var["style_aesthetic"],
        "creative_context":   var["creative_context"],
    }


async def generate_scene(
    visual_dna: dict[str, Any],
    product: dict[str, Any],
    product_truth: dict[str, Any],
    trend_label: str | None = None,
    reference_analysis: dict[str, Any] | None = None,
    commerce_dna: dict[str, Any] | None = None,
    concept: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Generate a believable scene for a product.

    Returns a scene dict. Now always includes six variation axes:
        camera_angle, lighting_setup, color_grading,
        scene_environment, style_aesthetic, creative_context.

    These are chosen from a class-specific pool (apparel options for
    clothes, toy options for toys, etc.) so sibling concepts within
    the same job differ on all six axes simultaneously, not just in
    which creative_format was selected.

    Raises:
        PipelineStageError: the director could not produce a believable
        scene after validation.
    """
    classification = classify_product(product, reference_analysis)
    klass = classification.product_class
    logger.info(
        "Generating scene for %r — class %s",
        product.get("name", "unknown"), classification.describe(),
    )
    if classification.confidence == "low":
        logger.warning(
            "Product class for %r could not be identified confidently; the director is "
            "reasoning from the product itself.",
            product.get("name", "unknown"),
        )

    # Build variation dict up front so both modes can use it.
    name = str(product.get("name") or "product")
    concept_safe = concept or {}
    concept_id = str(
        concept_safe.get("concept_id") or concept_safe.get("creative_format") or "A"
    )
    seed_key = f"{name}|{concept_id}|{klass.key}"
    var = variation_for(klass.key, seed_key)  # ← NEW: class-aware variation

    prompt = _build_user_prompt(
        visual_dna,
        product,
        product_truth,
        classification,
        reference_analysis,
        trend_label,
        commerce_dna=commerce_dna,
        concept=concept,
        variation=var,   # ← NEW: pass variation into LLM prompt
    )

    # ── Mode 1 (default): direct from the taxonomy menu ────────────────────
    if not settings.scene_director_llm:
        scene = _deterministic_scene(klass, product, product_truth, commerce_dna, concept)
        problems = _scene_problems(scene, classification)
        if problems:
            raise PipelineStageError(
                "scene_director",
                f"the taxonomy menu could not produce a scene that suits a "
                f"{klass.noun} (class {klass.key}): {' '.join(problems)}",
            )
        scene["product_class"] = klass.key
        scene["class_confidence"] = classification.confidence
        logger.info(
            "Scene ready (deterministic + variation matrix): %s / %s / %s / %s (class %s)",
            scene.get("creative_format"),
            scene.get("framing"),
            scene.get("lighting_setup", "")[:40],
            scene.get("style_aesthetic", "")[:40],
            klass.key,
        )
        return scene

    # ── Mode 2: LLM direction ────────────────────────────────────────────
    scene: dict[str, Any] = {}
    problems: list[str] = []

    for attempt in (1, 2):
        try:
            scene = await asyncio.wait_for(
                llm.structured_output(prompt, system=SYSTEM_PROMPT), timeout=45
            )
        except asyncio.TimeoutError as e:
            logger.error("Scene LLM timed out after 45s (attempt %d) for %s", attempt, klass.key)
            raise PipelineStageError(
                "scene_director",
                f"the LLM director timed out after 45s on attempt {attempt} for a "
                f"{klass.noun} (class {klass.key}); set SCENE_DIRECTOR_LLM=false "
                "to direct from the taxonomy menu instead",
            ) from e
        except Exception as e:
            logger.error("Scene generation failed (attempt %d): %s", attempt, e)
            raise PipelineStageError("scene_director", f"LLM call failed: {e}") from e

        if not isinstance(scene, dict) or not scene.get("creative_format"):
            problems = [
                "the reply had no creative_format; return the JSON object described "
                f"in the schema. Got keys: {sorted(scene) if isinstance(scene, dict) else type(scene).__name__}."
            ]
        else:
            problems = _scene_problems(scene, classification)

        if not problems:
            break

        logger.warning(
            "Scene attempt %d rejected for %s: %s", attempt, klass.key, " ".join(problems)
        )
        if attempt == 1:
            prompt += (
                "\n\nYOUR PREVIOUS ANSWER WAS REJECTED:\n"
                + "\n".join(f"  - {p}" for p in problems)
                + "\nReturn a corrected JSON object that obeys the PRODUCT CLASS block "
                "and honours all six FLOW VARIATION fields."
            )

    if problems:
        raise PipelineStageError(
            "scene_director",
            f"the scene director could not produce a scene that suits a {klass.noun} "
            f"(class {klass.key}) after two attempts: {' '.join(problems)}",
        )

    scene["product_class"] = klass.key
    scene["class_confidence"] = classification.confidence
    scene.setdefault("framing", klass.framing)
    scene.setdefault("product_state", klass.product_states[0] if klass.product_states else "in use")

    # Ensure variation fields are always present in the returned scene dict,
    # even when the LLM omitted them (it should echo them per the schema).
    for axis_key, axis_val in var.items():
        scene.setdefault(axis_key, axis_val)

    logger.info(
        "Scene ready (LLM + variation): %s / %s / %s (class %s)",
        scene.get("creative_format"),
        scene.get("style_aesthetic", "")[:40],
        scene.get("lighting_setup", "")[:40],
        klass.key,
    )
    return scene
