"""
Rework Engine — generates targeted prompt revisions based on critique results.

Instead of blind regeneration, targets ONLY the weak dimensions
while preserving what works.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.providers.llm import llm

logger = logging.getLogger("pre.pipeline.rework_engine")

SYSTEM_PROMPT = """\
You are the Rework Engine for the Pinterest Realism Engine.

A generated image was critiqued and needs revision. Your job is to
create a TARGETED revision instruction that fixes ONLY what failed
while preserving everything that works.

You will receive:
  • The original prompt
  • The critique results (what passed, what failed)
  • Product Truth (must still be respected)

OUTPUT FORMAT — plain text revision instruction with three sections:

PRESERVE: [list what should NOT change]

FIX: [describe exactly what failed and how to fix it]

AVOID: [what caused the failure — what to steer away from]

Be SPECIFIC. Don't say "make it more realistic" — say exactly
what aspect needs to change and how.

Return the revision instruction as plain text, not JSON.
"""


async def generate_rework(
    original_prompt: str,
    critique: dict[str, Any],
    product_truth: dict[str, Any],
) -> str:
    """
    Generate a targeted rework instruction based on critique results.

    Returns:
        Plain text revision instruction.
    """
    logger.info("Generating rework instruction")

    prompt = (
        "The following generated image needs revision.\n\n"
        f"ORIGINAL PROMPT:\n{original_prompt}\n\n"
        f"CRITIQUE RESULT:\n```json\n{json.dumps(critique, indent=2)}\n```\n\n"
        f"PRODUCT TRUTH:\n```json\n{json.dumps(product_truth, indent=2)}\n```\n\n"
        "Generate a targeted revision instruction. Be specific about what to fix "
        "and what to preserve. Return plain text with PRESERVE, FIX, and AVOID sections."
    )

    result = await llm.generate_text(prompt, system=SYSTEM_PROMPT)
    logger.info("Rework instruction generated")
    return result
