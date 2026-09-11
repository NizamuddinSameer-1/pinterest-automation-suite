"""Probe shot_archetypes: resolve every taxonomy class, render the 4-shot plan,
and prove the four directives are genuinely distinct while sharing a locked world.

Run: python -m scratch.shot_archetype_probe
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline.product_taxonomy import CLASSES, resolve_class  # noqa: E402
from app.pipeline.shot_archetypes import (  # noqa: E402
    SHOT_ORDER,
    _NICHE,
    describe_archetypes,
    name_phrase,
    niche_slots,
    shot_directive,
    shot_plan,
)

print("=" * 78)
print("ARCHETYPE TABLE")
print("=" * 78)
print(describe_archetypes())

# ── 1. every taxonomy class resolves a niche slot set ──────────────────
print()
print("=" * 78)
print("NICHE SLOT COVERAGE")
print("=" * 78)
missing = []
for key in sorted(CLASSES):
    if key == "generic":
        continue  # generic IS the fallback set
    slots = niche_slots(key)
    if slots is niche_slots("generic"):
        missing.append(key)
print(f"taxonomy classes: {len(CLASSES)}")
print(f"classes falling back to generic (excluding 'generic' itself): {len(missing)} {missing}")
assert not missing, f"uncovered classes: {missing}"
assert "generic" in CLASSES and "generic" in _NICHE, "generic must exist in both"

# ── 2. unknown class still works ───────────────────────────────────────
assert niche_slots("not_a_real_class") is niche_slots("generic")
assert niche_slots(None) is niche_slots("generic")
print("unknown class + None both fall back to generic: OK")

# ── 3. render the plan for a few real products ─────────────────────────
SAMPLES = [
    ("linen midi dress", "apparel"),
    ("leather ankle boots", "footwear"),
    ("vitamin c serum", "skincare"),
    ("wireless earbuds", "tech"),
    ("ceramic mug", "kitchen"),
    ("yoga mat", "fitness"),
    ("nonsense object xyzzy", "generic"),
]

scene_stub = {
    "color_grading": "warm neutral, slightly desaturated filmic grade",
    "style_aesthetic": "authentic UGC realism, anti-studio",
    "camera_angle": "eye level",
    "lighting_setup": "window light",
    "scene_environment": "bedroom",
}

print()
print("=" * 78)
print("FOUR-SHOT PLAN PER PRODUCT")
print("=" * 78)
for product_name, expected in SAMPLES:
    klass = resolve_class(expected)
    product = {"name": product_name}
    world = {"colour grading": scene_stub["color_grading"], "visual aesthetic": scene_stub["style_aesthetic"]}
    directives = {k: shot_directive(k, klass, product, world) for k in SHOT_ORDER}

    print(f"\n--- {product_name!r}  ->  class={klass.key}  (expected {expected}) ---")
    for k in SHOT_ORDER:
        d = directives[k]
        first = d.splitlines()[0]
        print(f"    {k:12} | {len(d):4}d | {first}")

    # distinctness: no two directives may be identical
    assert len(set(directives.values())) == 4, f"{product_name}: directives not distinct"

    # shared locked world must appear in all four
    for k in SHOT_ORDER:
        assert "CONSISTENCY" in directives[k], f"{product_name}/{k}: locked world missing"
        assert scene_stub["color_grading"] in directives[k]

    # per-shot differences that actually matter
    assert "SHOT TYPE — Lifestyle / in use." in directives["lifestyle"]
    assert "SHOT TYPE — Editorial / flat lay." in directives["flat_lay"]
    assert "SHOT TYPE — Macro / detail." in directives["macro"]
    assert "SHOT TYPE — Context / environment." in directives["environment"]

    # a macro frame must not carry styling props
    assert "STYLING PROPS" not in directives["macro"], f"{product_name}: macro carries props"
    assert "STYLING PROPS" in directives["flat_lay"]
    assert "STYLING PROPS" in directives["environment"]

    # macro + flat_lay use a surface/backdrop, lifestyle + environment use SETTING
    assert "SURFACE:" in directives["flat_lay"], f"{product_name}: flat_lay missing surface"
    assert "BACKDROP:" in directives["macro"], f"{product_name}: macro missing backdrop"
    assert "SURFACE:" not in directives["macro"], f"{product_name}: macro carries a bare surface"
    assert "SETTING:" in directives["lifestyle"] and "SETTING:" in directives["environment"]

    # the product must be named grammatically mid-sentence in every shot
    phrase = name_phrase({"name": product_name})
    for k in SHOT_ORDER:
        assert phrase in directives[k], f"{product_name}/{k}: {phrase!r} not named"

    # lifestyle must be the only one mentioning a person/wearing
    assert "no person in frame" in directives["flat_lay"]

print()
print("all directives distinct, locked world shared, slot routing correct: OK")

# ── 4. human presence respects the class allow-list ────────────────────
print()
print("=" * 78)
print("HUMAN PRESENCE")
print("=" * 78)
for key in sorted(CLASSES):
    klass = resolve_class(key)
    plan = shot_plan(klass, scene_stub)
    allowed = set(klass.human_presence or ("none",))
    for shot in plan:
        hp = shot["human_presence"]
        assert hp in allowed, f"{key}/{shot['key']}: {hp!r} not in allowed {sorted(allowed)}"
    print(f"  {key:12} allowed={sorted(allowed)!s:48} lifestyle={plan[0]['human_presence']:16} others={plan[1]['human_presence']}")
print("every plan's human_presence is inside its class allow-list: OK")

# ── 5. aspect ratios ───────────────────────────────────────────────────
print()
print("=" * 78)
print("ASPECT RATIOS")
print("=" * 78)
plan = shot_plan(resolve_class("apparel"), scene_stub)
for shot in plan:
    print(f"  {shot['key']:12} {shot['aspect_ratio']:6} framing={shot['framing']:8} {shot['label']}")
assert [s["aspect_ratio"] for s in plan] == ["4:5", "1:1", "1:1", "9:16"]
print("aspect ratios: OK")

print()
print("=" * 78)
print("PRODUCT NAME PHRASING")
print("=" * 78)
for raw, expect in [
    ("linen midi dress", "the linen midi dress"),
    ("The Linen Dress", "The Linen Dress"),
    ("a silk scarf", "a silk scarf"),
    ("Aeropress Coffee Maker", "the Aeropress Coffee Maker"),
    ("", "the product"),
    ("  earbuds.  ", "the earbuds"),
]:
    got = name_phrase({"name": raw})
    print(f"  {raw!r:28} -> {got!r}")
    assert got == expect, f"{raw!r}: got {got!r}, expected {expect!r}"
print("name_phrase: OK")

print()
print("ALL PROBES PASSED")
