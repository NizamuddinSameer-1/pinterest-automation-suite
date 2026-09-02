"""
Stage — Creative Diversity Score.

Counts unique combinations of creative_format + framing + location + human_presence.
Score = int(100 * unique_combinations / len(scenes)). Warnings when highly repetitive.
"""

from __future__ import annotations


def score_diversity(scenes: list[dict]) -> dict:
    if not scenes:
        return {"score": 100, "warnings": [], "unique_formats": 0, "unique_combinations": 0}
    # Unique combinations across all 4 diversity dimensions
    combos = set(
        (
            s.get("creative_format"),
            s.get("framing"),
            s.get("location"),
            s.get("human_presence"),
        )
        for s in scenes
    )
    unique_combinations = len(combos)
    score = int(100 * unique_combinations / max(len(scenes), 1))

    # Per-dimension uniques for diagnostics (useful for callers, not for scoring)
    unique_formats = len(set(s.get("creative_format") for s in scenes))
    unique_framings = len(set(s.get("framing") for s in scenes))
    unique_locations = len(set(s.get("location") for s in scenes))
    unique_presences = len(set(s.get("human_presence") for s in scenes))

    warnings: list[str] = []
    if score < 40:
        warnings.append(f"HIGH REPETITION \u2014 Creative Diversity: {score}/100")
    return {
        "score": score,
        "warnings": warnings,
        "unique_formats": unique_formats,
        "unique_combinations": unique_combinations,
        "unique_framings": unique_framings,
        "unique_locations": unique_locations,
        "unique_presences": unique_presences,
    }
