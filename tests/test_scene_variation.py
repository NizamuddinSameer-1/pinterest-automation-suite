"""
Scene variation matrix: class-aware six-axis direction for the director.

Locks in:
1. Every taxonomy class has a dedicated matrix (no silent generic fallback
   for a class we actually support).
2. Same (class, seed) always yields the same six fields (reproducible jobs).
3. Sibling concepts differ on the variation axes, not just the format.
4. Mode-1 scenes always carry all six fields, non-empty.
5. The compiler forwards the six axes into the Imagen prompt — and omits
   the block for pre-matrix scenes.
"""
from __future__ import annotations

import pytest

from app.pipeline import scene_director as sd
from app.pipeline.product_taxonomy import CLASSES, classify_product
from app.pipeline.prompt_compiler import compile_prompt
from app.pipeline.scene_variation_matrix import (
    VariationMatrix,
    axis_options,
    list_supported_classes,
    variation_for,
)

JACKET = {"name": "Oversized Black Leather Utility Jacket", "category": "apparel"}
TOY = {"name": "Wooden Rainbow Stacker Toy", "category": "toys"}

SIX = ("camera_angle", "lighting_setup", "color_grading",
       "scene_environment", "style_aesthetic", "creative_context")


def _concept(cid):
    return {"concept_id": cid, "objective": "product_desire", "visual_hook": "hero"}


def test_every_taxonomy_class_has_a_matrix():
    """No supported class may silently fall back to generic."""
    supported = set(list_supported_classes())
    assert supported == set(CLASSES.keys())
    for key in CLASSES.keys():
        matrix = variation_for(key, "seed")
        assert set(matrix.keys()) == set(SIX)
        assert all(isinstance(v, str) and v for v in matrix.values())


def test_unknown_class_falls_back_to_generic():
    assert variation_for("not_a_class", "seed") == variation_for("generic", "seed")


def test_variation_is_deterministic_per_axis():
    a = variation_for("apparel", "Jacket|A|apparel")
    b = variation_for("apparel", "Jacket|A|apparel")
    assert a == b
    # Same seed, different class → different pools.
    assert variation_for("apparel", "s") != variation_for("toys", "s")


def test_sibling_concepts_differ_on_all_axes():
    """Different concept_ids for one product must not share a single axis value."""
    seen = {axis: set() for axis in SIX}
    for cid in ("A", "B", "C", "D"):
        var = variation_for("apparel", f"Jacket|{cid}|apparel")
        for axis in SIX:
            seen[axis].add(var[axis])
    for axis in SIX:
        assert len(seen[axis]) > 1, f"axis {axis} identical across siblings"


def test_axis_options_matches_matrix():
    matrix = variation_for("apparel", "x")
    assert matrix["camera_angle"] in axis_options("apparel", "camera_angles")
    assert axis_options("nope", "camera_angles") == axis_options("generic", "camera_angles")
    assert axis_options("apparel", "nope") == ()


def test_mode1_scene_always_carries_six_fields():
    """generate_scene path is LLM-gated; _deterministic_scene is the live path."""
    for product in (JACKET, TOY):
        klass = classify_product(product).product_class
        scene = sd._deterministic_scene(klass, product, {}, None, _concept("A"))
        for axis in SIX:
            assert isinstance(scene.get(axis), str) and scene[axis], axis
        problems = sd._scene_problems(scene, classify_product(product))
        assert problems == []


def test_mode1_variation_is_class_aware():
    """Clothes and toys pull from different pools (the clothing-pin fix)."""
    klass_j = classify_product(JACKET).product_class
    klass_t = classify_product(TOY).product_class
    sj = sd._deterministic_scene(klass_j, JACKET, {}, None, _concept("A"))
    st = sd._deterministic_scene(klass_t, TOY, {}, None, _concept("A"))
    assert sj["style_aesthetic"] != st["style_aesthetic"]
    assert sj["scene_environment"] != st["scene_environment"]


def _minimal_scene(**overrides):
    base = {
        "creative_format": "flat_lay",
        "capture_motivation": "Someone showing their new jacket",
        "location": "in a bedroom",
        "action": "Jacket in use",
        "camera_position": "handheld",
        "framing": "medium",
        "product_state": "in use",
        "surface": "bed",
        "human_presence": "none",
        "background_elements": [],
        "staging_level": "minimal",
        "product_class": "apparel",
    }
    base.update(overrides)
    return base


def _product_truth():
    return {"must_preserve": ["black leather"], "must_not_invent": ["logos"]}


def test_compiler_forwards_variation_block():
    scene = _minimal_scene(**{k: f"test-{k}" for k in SIX})
    result = compile_prompt({}, JACKET, _product_truth(), scene)
    assert result.is_valid
    assert "FLOW VARIATION" in result.prompt
    for k in SIX:
        assert f"test-{k}" in result.prompt


def test_compiler_omits_block_for_legacy_scenes():
    """Pre-matrix scenes compile exactly as before (no behavior change)."""
    result = compile_prompt({}, JACKET, _product_truth(), _minimal_scene())
    assert result.is_valid
    assert "FLOW VARIATION" not in result.prompt
