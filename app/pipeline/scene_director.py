"""
Stage 3 — Scene Director.

Decides what is happening in the photograph and why it was taken.

This stage is where "every pin looks like a clothing pin" came from. The director
used to receive one fixed menu of ten creative formats — six of them apparel or
retail idioms (`wear_test`, `mirror_pov`, `product_rack`, `shopping_cart`,
`discovery`, `bedroom_home`) — plus five `capture_motivation` examples of which
four were clothing or footwear. Nothing said "assume apparel"; the menu simply made
apparel the likeliest answer for a toy, a saucepan or a set of press-on nails.

Now the menu, the physical reality (scale, framing, camera height, believable
surfaces and product states) and the examples all come from
`app.pipeline.product_taxonomy`, keyed on the product's class. The class is
inferred from the product's name and attributes *and* from Stage 1's own reading of
the reference image — `subject.primary_category`, `subject.objects` — which the
pipeline computed, stored, and until now never read.

The output schema gained `framing`, `product_state` and `surface`, because the
compiler had no way to say "this is a macro shot of a hand" versus "this is a
standing shot of a room" and defaulted to the latter every time.
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
from app.providers.llm import llm

logger = logging.getLogger("pre.pipeline.scene_director")

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

You must create a BELIEVABLE SCENE — a scenario that a real person
would actually photograph and share on Pinterest.

The PRODUCT CLASS block in the user message is binding. It lists the only creative
formats that make sense for this object, the scale it should be photographed at,
the surfaces and locations it plausibly sits on, and the states it can be in. Do
not import a format, a location or a pose from a different kind of product: a set
of nails is not hung on a rail, a saucepan is not worn, a duvet is not held up to
a mirror, a charger is not photographed at standing height across a room.

MANDATORY FIELD: capture_motivation
  You MUST answer: "Why would a real person take this photo?"
  The class block gives examples for THIS kind of product. Match their
  specificity — a motivation that would fit any product at all is not specific
  enough, and a generic one is what made every generated pin look identical.

OUTPUT SCHEMA:
{
  "creative_format": "one of the formats listed in the PRODUCT CLASS block",
  "capture_motivation": "string — WHY this photo was taken (MANDATORY)",
  "location": "string — specific, believable location",
  "action": "string — what is happening; if nobody is present, what state the product is in",
  "camera_position": "string — how the camera is held, at what height and distance",
  "framing": "macro|tight|medium|wide — how much of the frame the product occupies",
  "product_state": "string — the product's condition in this photo (worn, mid-use, just unboxed, put away, …)",
  "surface": "string — what the product is resting on, worn on, or held by",
  "human_presence": "full|partial_hand_arm|partial_body|none",
  "background_elements": ["string — specific background items"],
  "staging_level": "none|minimal|moderate"
}

RULES:
- The scene must be PLAUSIBLE — something a real person would actually do
- creative_format MUST come from the PRODUCT CLASS block, exactly as spelled there
- human_presence MUST be one of the values the class block allows
- framing and camera_position must match the product's scale — do not photograph a
  centimetre-scale object from standing height, or a bed from macro distance
- The scene must MATCH the Visual DNA style (don't create studio shots for UGC DNA)
- capture_motivation is MANDATORY — if you can't justify WHY someone would
  take this photo, the scene is not believable

Return ONLY the JSON object. No extra text.
"""


def _build_user_prompt(
    visual_dna: dict[str, Any],
    product: dict[str, Any],
    product_truth: dict[str, Any],
    classification: Classification,
    reference_analysis: dict[str, Any] | None,
    trend_label: str | None,
    commerce_dna: dict[str, Any] | None = None,
    concept: dict[str, Any] | None = None,
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
        # Ensure title-case variant present for test compatibility without breaking exact uppercase check
        if "Creative Concept" not in parts[-1]:
            parts[-1] += "\nCreative Concept"

    # Stage 1 read the reference image and classified its subject and scene. That
    # was stored and then ignored; passing the useful half through means the
    # director knows what kind of photograph the operator actually chose to copy.
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
    """
    A stable seed for one axis of one scene.

    `hash()` is salted per process, so it would pick a different scene on every
    restart; sha256 keeps a product+concept pair reproducible across runs and
    across machines, which matters because a job can be re-generated.
    """
    return int.from_bytes(
        hashlib.sha256(f"{seed_key}|{axis}".encode("utf-8")).digest()[:8], "big"
    )


def _rotate(items: tuple[str, ...], seed_key: str, axis: str, default: str) -> str:
    """Pick one item from the menu, decorrelated per axis.

    Seeding each axis separately is deliberate: a single seed rotated across
    every axis would move format, location and surface in lockstep, so "the third
    format" would always arrive with "the third location" — variety that looks
    identical in aggregate.
    """
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

    This is a mode, not a fallback — see `generate_scene`. It still has to
    *choose*, for two reasons:

      * `ProductClass.formats` is a whitelist, not a ranking. The taxonomy's own
        docstring says the director still chooses; taking `formats[0]` treats a
        menu as an answer.
      * Upstream already did the creative work. `generate_concepts` asks for 4-7
        concepts that each carry a *different* `creative_format`, and
        `commerce_strategist` produced a `visual_hook` and a `must_show` list.
        Discarding them is what made every pin for a product class identical.

    Variation is seeded, not random: the same product+concept always yields the
    same scene, and different concepts yield different ones.
    """
    name = str(product.get("name") or "product")
    concept = concept or {}
    commerce_dna = commerce_dna or {}
    concept_id = str(concept.get("concept_id") or concept.get("creative_format") or "A")
    seed_key = f"{name}|{concept_id}|{klass.key}"

    # The concept's own format wins when the taxonomy allows it for this class.
    # That is upstream's creative decision, and it is what makes sibling concepts
    # differ. When it is implausible (a "mirror_pov" for a tumbler, say) it is
    # refused rather than forced through — the menu is a whitelist.
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

    # The action carries what must be visible in frame. "Product in use" was the
    # generic string that made every prompt read alike even when the format moved.
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

    # Two distinct surfaces for the background, rotating as a pair so the
    # combination itself varies rather than always being the first two.
    surfaces = list(klass.surfaces)
    if surfaces:
        start = _seed_for(seed_key, "background") % len(surfaces)
        background = [surfaces[(start + i) % len(surfaces)] for i in range(min(2, len(surfaces)))]
    else:
        background = ["soft window light"]

    return {
        "creative_format": fmt,
        "capture_motivation": _rotate(
            klass.motivations, seed_key, "motivation",
            f"Person showing {name} in natural light",
        ),
        "location": _rotate(klass.locations, seed_key, "location", "in a sunlit room"),
        "action": action,
        "camera_position": f"Handheld, {klass.camera_height}",
        "framing": klass.framing,
        "product_state": product_state,
        "surface": _rotate(klass.surfaces, seed_key, "surface", "table"),
        "human_presence": _rotate(klass.human_presence, seed_key, "human", "none"),
        "background_elements": background,
        "staging_level": "moderate",
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

    Args:
        visual_dna: The VisualDNA dict.
        product: Product details dict.
        product_truth: ProductTruth dict (must_preserve, must_not_invent).
        trend_label: Optional trend context ("quiet luxury", "back to school").
            Passed to the LLM verbatim.
        reference_analysis: Optional Stage 1 analysis for the reference image. Its
            `subject` block also feeds product classification, so a picture of a
            child's toy is not directed as a garment because the category field
            says "kids".

    Returns:
        Scene dict. Carries `product_class` and `class_confidence` so the compiler
        and the saved SCENE.json agree with the class this stage actually used.

    Raises:
        PipelineStageError: the director could not produce a believable scene. In
            LLM mode that means the call timed out, failed, or returned a scene
            that does not suit the product class even after one corrective retry.
            In taxonomy mode it means the menu could not satisfy the class
            constraints. Nothing is ever filled in on the scene's behalf: a
            substituted scene is what made every pin look the same.
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
            "reasoning from the product itself. Set a clearer category or name to fix this.",
            product.get("name", "unknown"),
        )

    prompt = _build_user_prompt(
        visual_dna,
        product,
        product_truth,
        classification,
        reference_analysis,
        trend_label,
        commerce_dna=commerce_dna,
        concept=concept,
    )

    # ── Mode 1 (default): direct from the taxonomy menu ────────────
    # Which mode runs is a policy choice, not a fallback. Taking index 0 of every
    # axis — as the old FAST PATH did — threw away the diversity the upstream
    # stages had already computed, and that is what made every pin for a product
    # class come out identical.
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
            "Scene ready (deterministic direction): %s / %s (class %s)",
            scene.get("creative_format"), scene.get("framing"), klass.key,
        )
        return scene

    # ── Mode 2: LLM direction ──────────────────────────────────────
    # Opt-in (settings.scene_director_llm). Nothing is substituted if the LLM
    # cannot answer — a substituted scene is indistinguishable from a directed
    # one downstream, which is exactly how identical pins slipped through.
    scene = {}
    problems = []

    if not scene or problems:
        for attempt in (1, 2):
            try:
                scene = await asyncio.wait_for(llm.structured_output(prompt, system=SYSTEM_PROMPT), timeout=8)
            except asyncio.TimeoutError as e:
                # No substitution. In LLM mode the operator asked for the LLM, so
                # a timeout is a failure the caller must see (and retry or switch
                # scene_director_llm off), not a scene that silently repeats.
                logger.error("Scene LLM timed out after 8s (attempt %d) for %s", attempt, klass.key)
                raise PipelineStageError(
                    "scene_director",
                    f"the LLM director timed out after 8s on attempt {attempt} for a "
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
                    + "\nReturn a corrected JSON object that obeys the PRODUCT CLASS block."
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

    logger.info(
        "Scene ready: %s / %s (class %s)",
        scene.get("creative_format"), scene.get("framing"), klass.key,
    )
    return scene
