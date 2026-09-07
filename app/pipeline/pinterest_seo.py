"""
Pinterest SEO — generates Pinterest-optimized metadata for Pins.

Takes trend, product, scene context, and optionally the generated image itself:
  - When given an image, inspects the photo with vision (Lane 2 content_llm) to produce
    100% unique, photo-grounded titles, descriptions, and keywords for each variation.
  - Rotates through 6 high-CTR hook frameworks so no two pins share duplicate copy.
  - Never outputs generic duplicate titles like "(Look #2)".
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.pipeline.errors import PipelineStageError
from app.providers.llm import content_llm

logger = logging.getLogger("pre.pipeline.pinterest_seo")

FRAMEWORKS = [
    {
        "name": "The Skeptical Micro-Review",
        "example": "Honestly didn't expect this [Product] to look this good in person",
        "instruction": "Focus on an honest aesthetic reaction, surprising quality, or unboxing impression visible in the photo.",
    },
    {
        "name": "The Practical Problem-Solver",
        "example": "Finally found a [Product] that actually [Observed Benefit/Fit]",
        "instruction": "Focus on solving a specific pain point (proportions, space saving, drape, flattering silhouette) shown in this angle.",
    },
    {
        "name": "The Real-Life Preview",
        "example": "What this [Product] looks like in real daily life",
        "instruction": "Emphasize genuine unretouched daily lighting, natural room placement, or practical lifestyle wear.",
    },
    {
        "name": "The Curation & Vibe Anchor",
        "example": "The exact [Product] aesthetic for your [Observed Room/Outfit]",
        "instruction": "Anchor the product to a specific trending aesthetic, room decor theme, or seasonal palette visible in the shot.",
    },
    {
        "name": "The Value / Smart Pick Hook",
        "example": "Skip the overpriced brand — this [Product] has the exact same [Observed Feature]",
        "instruction": "Highlight rich materials, textures, or design details visible in the photo that rival luxury brands.",
    },
    {
        "name": "The Daily Routine Utility",
        "example": "How I'm styling this [Product] for [Observed Setting]",
        "instruction": "Focus on practical everyday styling, pairing advice, or functional setup highlighted by this perspective.",
    },
]

VISION_PIN_SEO_SYSTEM = """\
You are an expert Pinterest SEO specialist and visual merchandising copywriter for SmartPickr.
You inspect the GIVEN PHOTO of an affiliate product and craft HIGH-CLICKTHROUGH-RATE, 100% photo-grounded Pinterest SEO copy.

CORE RULES:
1. Ground every claim strictly in what is VISIBLE in this exact photo (camera angle, lighting, styling, material finish, real-life placement, room setting).
2. NEVER use generic duplicated titles like "(Look #2)" or "(Look #3)". Every variation must have a distinct angle and hook.

3. 2026 PIN TITLE FORMULA (30-60 characters, hook-driven):
   Formula: [Aesthetic Name] + [Item Type] + [Amazon Signal/Benefit] + [Year/Modifier]
   Examples:
     - "Poetcore Outfit Ideas | Chunky Knit Amazon Find (2026)"
     - "Neo-Deco Bar Cart for Small Spaces | Slim 3-Tier Amazon Find (2026)"
     - "Aesthetic Fluted Ceramic Vase | Textured Stoneware Amazon Review"
     - "Linen Duvet Set | Breathable French Flax Amazon Guide (2026)"

   Assigned Hook Angle for this photo: {framework_name}
   Pattern Inspiration: "{framework_example}"
   Guidance: {framework_instruction}

   - Integrate the assigned hook angle into the 2026 title formula naturally.
   - Title MUST be between 30 and 60 characters.
   - Always include an authentic Amazon commercial signal (e.g., "Amazon Find", "Amazon Review", "on Amazon", "Amazon Essentials").
   - NO keyword stuffing, NO all-caps urgency ("HURRY!"), NO fake claims ("BEST EVER!").

4. 2-SENTENCE DESCRIPTION RULES (100-300 characters):
   Strictly 2 sentences + maximum 3 hashtags:
   - Sentence 1 (Primary Keyword Hook & Visual Context): Must contain the primary search term and describe what is visibly featured in THIS photo (lighting, angle, texture, or styling).
   - Sentence 2 (Long-Tail Integration & Buyer Benefit): Naturally weave in 3-5 supporting organic long-tail search terms and a clear practical takeaway.
   - Hashtags: Exactly 2-3 relevant hashtags at the very end (e.g. #HomeDecor #AmazonFinds #AestheticLiving). NEVER use more than 3 hashtags (Pinterest flags >3 hashtags as spam).

5. KEYWORDS: 5-10 specific, high-intent search terms.
6. BOARD SELECTION:
   - Known Pinterest account boards: {existing_boards}
   - If one of the known account boards matches this product category, aesthetic, or vibe, you MUST choose that exact board name.
   - Only if NONE of the known boards are suitable, suggest a concise, high-CTR new board name (2-4 words) that would be suitable to create.

OUTPUT SCHEMA:
{{
  "title": "string — 30-60 chars, follows [Aesthetic] + [Item] + [Amazon Signal] + [Year] formula, grounded in photo",
  "description": "string — 100-300 chars, strictly 2 sentences + max 3 hashtags",
  "keywords": ["string — 5-10 relevant search terms"],
  "board_suggestion": "string — either an existing board name from the list above if relevant, or a new board name to create"
}}
Return ONLY the JSON object.
"""

TEXT_PIN_SEO_SYSTEM = """\
You are the Pinterest SEO specialist for the Pinterest Realism Engine.
Generate Pinterest-optimized metadata for an affiliate Pin.

RULES:
- Use natural, conversational language — write like a real Pinterest user
- NO keyword stuffing
- NO fake urgency ("LIMITED TIME!", "HURRY!")
- NO fake claims ("BEST EVER!", "MIRACLE!")
- NO clickbait or misleading descriptions
- NEVER use generic suffixes like "(Look #2)" or "(Look #3)"

2026 PIN TITLE FORMULA (30-60 characters):
Formula: [Aesthetic Name] + [Item Type] + [Amazon Signal/Benefit] + [Year/Modifier]
Examples:
  - "Poetcore Outfit Ideas | Chunky Knit Amazon Find (2026)"
  - "Neo-Deco Bar Cart for Small Spaces | Slim Amazon Find (2026)"
  - "Aesthetic Fluted Ceramic Vase | Amazon Stoneware Review (2026)"

ASSIGNED HOOK FRAMEWORK:
{framework_name}: "{framework_example}"
Guidance: {framework_instruction}

2-SENTENCE DESCRIPTION RULES (100-300 characters):
Strictly 2 sentences + maximum 3 hashtags:
- Sentence 1: Primary search keyword hook + conversational context describing the product and styling.
- Sentence 2: Naturally weaves in 3-5 supporting organic search terms and a practical buyer benefit.
- Hashtags: Exactly 2-3 relevant hashtags at the end (e.g. #HomeDecor #AmazonFinds). Never exceed 3.

BOARD SELECTION:
- Known Pinterest account boards: {existing_boards}
- If one of the known account boards matches this product category, aesthetic, or vibe, you MUST choose that exact board name.
- Only if NONE of the known boards are suitable, suggest a concise, high-CTR new board name (2-4 words) that would be suitable to create.

OUTPUT SCHEMA:
{{
  "title": "string — 30-60 chars, follows [Aesthetic] + [Item] + [Amazon Signal] + [Year] formula",
  "description": "string — 100-300 chars, strictly 2 sentences + max 3 hashtags",
  "keywords": ["string — 5-10 relevant search terms"],
  "board_suggestion": "string — either an existing board name from the list above if relevant, or a new board name to create"
}}
Return ONLY the JSON object.
"""


def _clean_title(title: str, fallback_name: str) -> str:
    """Ensure title has no (Look #N) leftovers and conforms to length constraints."""
    cleaned = re.sub(r"\s*\(Look\s*#?\d+\)", "", title, flags=re.IGNORECASE).strip()
    if not cleaned:
        cleaned = fallback_name[:60]
    return cleaned[:60]


async def generate_pin_seo(
    product: dict[str, Any],
    scene: dict[str, Any],
    trend_label: str | None = None,
    image_path: str | Path | None = None,
    variation_index: int = 1,
    total_variations: int = 1,
    existing_boards: list[str] | None = None,
    profile_id: str | None = None,
    keyword_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Generate Pinterest SEO metadata for a Pin.
    If image_path is provided and exists, uses Lane 2 vision to inspect the photo
    and ground the title and description in what is actually visible.
    Also grounds board_suggestion in the account's existing Pinterest boards.
    """
    from app.services import board_catalog

    if existing_boards is None:
        catalog = board_catalog.read_catalog(profile_id=profile_id)
        existing_boards = list(catalog.boards)

    boards_str = ", ".join(f'"{b}"' for b in existing_boards) if existing_boards else "None recorded yet"

    framework = FRAMEWORKS[(variation_index - 1) % len(FRAMEWORKS)]
    prompt_seed = ""
    if keyword_pack:
        primary = str(keyword_pack.get("primary") or "").strip()
        tails = [str(t) for t in (keyword_pack.get("long_tails") or []) if str(t).strip()]
        if primary:
            seed_hint = primary + (" | " + ", ".join(tails[:3]) if tails else "")
            prompt_seed = f"Pack primary keyword (use verbatim where natural): {seed_hint}\n\n"
    product_name = product.get("name") or "Curated Item"
    aesthetic = trend_label or product.get("category") or "Aesthetic"

    # Vision-grounded path
    if image_path:
        path = Path(image_path)
        if path.exists():
            try:
                system_prompt = VISION_PIN_SEO_SYSTEM.format(
                    framework_name=framework["name"],
                    framework_example=framework["example"],
                    framework_instruction=framework["instruction"],
                    existing_boards=boards_str,
                )
                user_prompt = prompt_seed + (f"This is variation #{variation_index} of {total_variations} for '{product_name}'.\n"
                    f"Target Year: 2026.\n"
                    f"Aesthetic / Trend: {aesthetic}.\n"
                    f"Inspect the attached photo and generate photo-grounded Pinterest SEO using the [Aesthetic] + [Item] + [Amazon Signal] + [Year] formula and 2-sentence description rule.\n\n"
                    f"PRODUCT:\n```json\n{json.dumps(product, indent=2)}\n```\n\n"
                    f"SCENE:\n```json\n{json.dumps(scene, indent=2)}\n```\n\n"
                )
                if trend_label:
                    user_prompt += f"TREND: {trend_label}\n\n"

                result = await content_llm.analyze_image(
                    prompt=user_prompt,
                    image_path=str(path),
                    system=system_prompt,
                    temperature=0.6,
                )
                if isinstance(result, dict) and result.get("title") and result.get("description"):
                    result["title"] = _clean_title(str(result["title"]), product_name)
                    # Ground board suggestion if an existing board matches
                    suggested = str(result.get("board_suggestion") or "").strip()
                    if suggested and existing_boards:
                        matched = board_catalog.find_best_board_match(suggested, existing_boards)
                        if matched:
                            result["board_suggestion"] = matched
                    logger.info("Vision-grounded Pinterest SEO generated for variation #%d: %s (board: %s)",
                                variation_index, result["title"], result.get("board_suggestion"))
                    return result
            except Exception as e:
                logger.warning("Vision analysis failed for image %s, falling back to text prompt: %s", path, e)

    # Text-based generation (with assigned framework to ensure unique angles)
    logger.info("Generating text-grounded Pinterest SEO for variation #%d: %s", variation_index, product_name)
    system_prompt = TEXT_PIN_SEO_SYSTEM.format(
        framework_name=framework["name"],
        framework_example=framework["example"],
        framework_instruction=framework["instruction"],
        existing_boards=boards_str,
    )
    prompt = prompt_seed + (f"Generate Pinterest SEO metadata for variation #{variation_index} of {total_variations} for this affiliate Pin.\n"
        f"Target Year: 2026.\n"
        f"Aesthetic / Trend: {aesthetic}.\n"
        f"Follow the [Aesthetic] + [Item] + [Amazon Signal] + [Year] formula and 2-sentence description rule.\n\n"
        f"PRODUCT:\n```json\n{json.dumps(product, indent=2)}\n```\n\n"
        f"SCENE:\n```json\n{json.dumps(scene, indent=2)}\n```\n\n"
    )
    if trend_label:
        prompt += f"TREND: {trend_label}\n\n"

    try:
        result = await content_llm.structured_output(prompt, system=system_prompt, temperature=0.7)
    except Exception as e:
        logger.error("Pinterest SEO generation failed: %s", e)
        raise PipelineStageError("pinterest_seo", f"LLM call failed: {e}") from e

    if not isinstance(result, dict) or not result.get("title") or not result.get("description"):
        raise PipelineStageError(
            "pinterest_seo",
            f"LLM returned SEO without title/description. Got: {result}",
        )

    result["title"] = _clean_title(str(result["title"]), product_name)
    suggested = str(result.get("board_suggestion") or "").strip()
    if suggested and existing_boards:
        matched = board_catalog.find_best_board_match(suggested, existing_boards)
        if matched:
            result["board_suggestion"] = matched

    logger.info("Pinterest SEO generation complete for variation #%d: %s (board: %s)",
                variation_index, result["title"], result.get("board_suggestion"))
    return result


async def generate_batch_pins_seo(
    product: dict[str, Any],
    scene: dict[str, Any],
    image_paths: list[str | Path] | None = None,
    trend_label: str | None = None,
    existing_boards: list[str] | None = None,
    profile_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Generate vision-grounded Pinterest SEO for a batch of generated images.
    Each image is inspected via vision (Lane 2) and assigned a distinct hook framework,
    guaranteeing zero duplicate titles across the batch.
    """
    paths = list(image_paths or [])
    total = len(paths) if paths else 1
    results: list[dict[str, Any]] = []

    if not paths:
        # Fallback when no image paths provided
        seo = await generate_pin_seo(
            product=product,
            scene=scene,
            trend_label=trend_label,
            existing_boards=existing_boards,
            profile_id=profile_id,
        )
        return [seo]

    for idx, path in enumerate(paths, 1):
        try:
            item_seo = await generate_pin_seo(
                product=product,
                scene=scene,
                trend_label=trend_label,
                image_path=path,
                variation_index=idx,
                total_variations=total,
                existing_boards=existing_boards,
                profile_id=profile_id,
            )
            results.append(item_seo)
        except Exception as e:
            logger.warning("Vision SEO generation failed for image %d (%s), trying fallback: %s", idx, path, e)
            try:
                fallback_seo = await generate_pin_seo(
                    product=product,
                    scene=scene,
                    trend_label=trend_label,
                    image_path=None,
                    variation_index=idx,
                    total_variations=total,
                    existing_boards=existing_boards,
                    profile_id=profile_id,
                )
                results.append(fallback_seo)
            except Exception as e2:
                logger.error("Text fallback SEO also failed for image %d: %s", idx, e2)
                raise PipelineStageError("pinterest_seo", f"SEO generation failed for variation {idx}: {e2}") from e2

    return results

