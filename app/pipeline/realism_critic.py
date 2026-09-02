"""
Stage 6 — Realism Critic.

Evaluates generated images against 3 core questions:
  1. Does this look like a real photograph? (authenticity)
  2. Does this match the actual product? (product fidelity)
  3. Is this original enough from the reference? (originality)

Also detects specific defects with severity levels.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.pipeline.errors import PipelineStageError
from app.providers.llm import llm

logger = logging.getLogger("pre.pipeline.realism_critic")

SYSTEM_PROMPT = """\
You are the Realism Critic for the Pinterest Realism Engine.

You evaluate whether a generated image plausibly looks like a REAL
photograph taken by a normal person — NOT whether it looks "good" or
"beautiful" or "cinematic".

You will receive:
  • The generated image to evaluate
  • The original reference image (for originality comparison)
  • Visual DNA (the photographic style it should match)
  • Product Truth (what the product MUST look like)
  • Scene description (what should be happening)

ANSWER THREE QUESTIONS:

1. AUTHENTICITY — "Does this look like a real photograph?"
   AUTHENTIC  — Passes as genuine UGC smartphone photo
   PLAUSIBLE  — Close but has minor tells (slightly too clean/sharp)
   SYNTHETIC  — Clearly AI-generated or too polished
   BROKEN     — Has obvious AI artifacts (bad hands, impossible geometry)

2. PRODUCT FIDELITY — "Does this match the actual product?"
   FAITHFUL       — Product appears as described in Product Truth
   MINOR_DRIFT    — Small deviations (slightly different shade, minor detail)
   MISREPRESENTED — Product looks significantly different from truth

3. ORIGINALITY — "Is this sufficiently different from the reference?"
   ORIGINAL    — New composition, angle, arrangement
   DERIVATIVE  — Same general layout but with differences
   COPY        — Too close to the reference composition

DEFECT DETECTION:
List ALL specific defects you find. For each, state:
  • severity: BLOCKER | MAJOR | MINOR
  • location: where in the image (e.g., "left_hand", "background_right")
  • description: what's wrong

BLOCKER examples: malformed hands, impossible anatomy, floating objects,
  broken product geometry, severe scene impossibility
MAJOR examples: distorted fabric, fake reflections, repeated objects,
  impossible shelf geometry, severe lighting inconsistency
MINOR examples: small texture issue, subtle background artifact,
  small edge irregularity

ALSO list STRENGTHS — what the image does well.

DO NOT reward:
  - Cinematic styling
  - Hyper-sharpness
  - Beauty alone
  - Visual polish alone

PRIORITIZE:
  - Physical plausibility
  - Photographic plausibility
  - Material realism
  - Ordinary camera behavior
  - Natural human interaction
  - Realistic environment
  - Product fidelity
  - Originality

OUTPUT SCHEMA:
{
  "authenticity": "AUTHENTIC|PLAUSIBLE|SYNTHETIC|BROKEN",
  "product_fidelity": "FAITHFUL|MINOR_DRIFT|MISREPRESENTED",
  "originality": "ORIGINAL|DERIVATIVE|COPY",
  "defects": [
    {
      "severity": "BLOCKER|MAJOR|MINOR",
      "location": "string",
      "description": "string"
    }
  ],
  "strengths": ["string"],
  "decision": "PASS|REWORK",
  "decision_reason": "string explaining the decision"
}

DECISION LOGIC (follow strictly):
  - Any BLOCKER defect → REWORK
  - MISREPRESENTED product fidelity → REWORK
  - COPY originality → REWORK
  - BROKEN or SYNTHETIC authenticity → REWORK
  - Otherwise → PASS (human makes final call)

Return ONLY the JSON object.
"""


async def critique_image(
    generated_image_path: str,
    reference_image_path: str,
    visual_dna: dict[str, Any],
    product_truth: dict[str, Any],
    scene: dict[str, Any],
    prompt_text: str,
) -> dict[str, Any]:
    """
    Evaluate a generated image for realism, product fidelity, and originality.

    Uses Gemini vision to analyze the generated image with full context.

    Returns:
        Critique dict with authenticity, product_fidelity, originality,
        defects, strengths, decision, and decision_reason.
    """
    logger.info("Critiquing generated image: %s", generated_image_path)

    user_prompt = (
        "Evaluate this generated image against the following context.\n\n"
        f"VISUAL DNA (target style):\n```json\n{json.dumps(visual_dna, indent=2)}\n```\n\n"
        f"PRODUCT TRUTH:\n```json\n{json.dumps(product_truth, indent=2)}\n```\n\n"
        f"SCENE:\n```json\n{json.dumps(scene, indent=2)}\n```\n\n"
        f"GENERATION PROMPT:\n{prompt_text}\n\n"
        "Evaluate the image critically. Return the critique JSON only."
    )

    result = await llm.analyze_image(
        prompt=user_prompt,
        image_path=generated_image_path,
        system=SYSTEM_PROMPT,
    )

    # A critique that is missing its judgement axes would sail through
    # _enforce_decision() as a PASS (no defects listed == no blockers found).
    # Refuse it instead: an unverified image must not be recorded as verified.
    required = ("authenticity", "product_fidelity", "originality")
    missing = [k for k in required if not result.get(k)]
    if missing:
        raise PipelineStageError(
            "realism_critic",
            f"Critique missing required axes: {', '.join(missing)}. Got keys: {sorted(result.keys())}",
        )

    # Enforce decision logic even if LLM gets it wrong
    result["decision"] = _enforce_decision(result)

    logger.info("Critique complete — decision: %s", result.get("decision"))
    return result


def _enforce_decision(critique: dict[str, Any]) -> str:
    """Apply deterministic decision logic on top of LLM output."""
    defects = critique.get("defects", [])
    has_blocker = any(d.get("severity") == "BLOCKER" for d in defects)

    if has_blocker:
        return "REWORK"
    if critique.get("product_fidelity") == "MISREPRESENTED":
        return "REWORK"
    if critique.get("originality") == "COPY":
        return "REWORK"
    if critique.get("authenticity") in ("BROKEN", "SYNTHETIC"):
        return "REWORK"

    return "PASS"
