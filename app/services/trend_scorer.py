"""
Trend Radar blended scorer — pure function, no I/O, no LLM calls.

score = w_demand*demand + w_money*money + w_winnability*winnability.
Tiers: S >= 85, A >= 70, else B (same bands as the legacy dossiers).
"""
from __future__ import annotations

from typing import Any

DEFAULT_WEIGHTS: dict[str, float] = {
    "demand": 0.40,
    "money": 0.35,
    "winnability": 0.25,
}

WEIGHTS_VERSION = 1


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def tier_for(score: float) -> str:
    """Map a 0-100 score to a Tier band."""
    if score >= 85:
        return "S"
    if score >= 70:
        return "A"
    return "B"


def score_trend(
    demand: float,
    money: float,
    winnability: float,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """
    Blend three 0-100 signals into one score.

    Returns {"score": rounded 1-decimal float, "tier": "S|A|B", "breakdown": {...}}.
    Inputs are clamped; custom weights replace (not merge with) the defaults.
    """
    w = weights or DEFAULT_WEIGHTS
    d, m, wn = _clamp(demand), _clamp(money), _clamp(winnability)
    blended = round(w["demand"] * d + w["money"] * m + w["winnability"] * wn, 1)
    return {
        "score": blended,
        "tier": tier_for(blended),
        "breakdown": {
            "demand": d,
            "money": m,
            "winnability": wn,
            "weights_version": WEIGHTS_VERSION,
        },
    }
