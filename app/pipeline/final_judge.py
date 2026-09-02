"""
Stage — Final Creative Judge (4-gate).

Applies the 4-gate rule:
  1. REALISM  — realism_critique.decision == PASS
  2. PRODUCT  — commerce_critique.product_clarity != low AND product_prominence != low
  3. ORIGINALITY — realism_critique.originality != COPY
  4. COMMERCE — commerce_critique.click_intent != low AND desire != low
→ FINAL PASS, else REWORK with targeted reason.
"""

from __future__ import annotations

from typing import Any


def judge(
    realism_critique: dict[str, Any],
    commerce_critique: dict[str, Any],
    diversity_report: dict[str, Any] | None = None,
) -> dict[str, str]:
    """
    Judge final creative output across 4 gates.

    Args:
        realism_critique: Result from realism critic, expects `decision` and `originality`.
        commerce_critique: Result from commerce critic, expects `product_clarity`,
            `product_prominence`, `desire`, `click_intent`.
        diversity_report: Optional diversity report (kept for backwards compat, not gated).

    Returns:
        Dict with `final` (PASS or REWORK) and `reason` (gate that failed or all gates passed).
    """
    # Gate 1: REALISM
    if realism_critique.get("decision") != "PASS":
        return {"final": "REWORK", "reason": "realism"}
    # Gate 2: PRODUCT (clarity + prominence)
    if commerce_critique.get("product_clarity") == "low":
        return {"final": "REWORK", "reason": "product_clarity"}
    if commerce_critique.get("product_prominence") == "low":
        return {"final": "REWORK", "reason": "product_prominence"}
    # Gate 3: ORIGINALITY
    if realism_critique.get("originality") == "COPY":
        return {"final": "REWORK", "reason": "originality"}
    # Gate 4: COMMERCE (desire + click intent)
    if commerce_critique.get("desire") == "low":
        return {"final": "REWORK", "reason": "desire"}
    if commerce_critique.get("click_intent") == "low":
        return {"final": "REWORK", "reason": "click_intent"}
    return {"final": "PASS", "reason": "all gates passed"}
