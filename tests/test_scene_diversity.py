"""
Scenes must differ between concepts — and stay reproducible within one.

The old FAST PATH in scene_director returned `formats[0] / motivations[0] /
locations[0] / surfaces[0]` for every call, so every pin made for a product class
came out identical. Upstream stages had already generated 4-7 concepts that each
carry a different `creative_format`; the director was throwing that away.

These tests lock in that the taxonomy menu is actually *chosen from*.
"""

from app.pipeline import scene_director as sd
from app.pipeline.product_taxonomy import classify_product

JACKET = {
    "name": "Oversized Black Leather Utility Jacket",
    "category": "apparel",
    "brand": "X",
    "key_attributes": ["leather", "oversized"],
}

TUMBLER = {
    "name": "Simple Modern Halloween Tumbler with Handle | 40oz",
    "category": "kitchen",
    "brand": "Simple Modern",
    "key_attributes": ["stainless steel"],
}

CONCEPT_A = {
    "concept_id": "A",
    "objective": "product_desire",
    "visual_hook": "hero fit",
    "must_show": ["handle", "lid"],
    "creative_format": "mirror_pov",
}
CONCEPT_B = {
    "concept_id": "B",
    "objective": "product_detail",
    "visual_hook": "texture",
    "must_show": ["finish", "seam"],
    "creative_format": "macro_detail",
}
CONCEPT_C = {
    "concept_id": "C",
    "objective": "lifestyle_use",
    "visual_hook": "street",
    "must_show": ["silhouette"],
    "creative_format": "outdoor_use",
}
CONCEPT_D = {
    "concept_id": "D",
    "objective": "discovery",
    "visual_hook": "shelf",
    "must_show": ["packaging"],
    "creative_format": "discovery",
}

CONCEPTS = [CONCEPT_A, CONCEPT_B, CONCEPT_C, CONCEPT_D]


def _scene(product, concept, product_truth=None):
    return sd._deterministic_scene(
        classify_product(product).product_class,
        product,
        product_truth or {},
        None,
        concept,
    )


def _signature(scene):
    return (
        scene["creative_format"],
        scene["location"],
        scene["surface"],
        scene["capture_motivation"],
    )


def test_each_concept_produces_a_different_scene():
    """The bug: four concepts, four identical scenes."""
    signatures = {_signature(_scene(JACKET, c)) for c in CONCEPTS}
    assert len(signatures) == len(CONCEPTS), "concepts collapsed onto the same scene"


def test_different_products_do_not_share_one_scene():
    a = _signature(_scene(JACKET, CONCEPT_B))
    b = _signature(_scene(TUMBLER, CONCEPT_B))
    assert a != b


def test_scene_is_reproducible_for_the_same_product_and_concept():
    """Seeded, not random: re-generating a job must not reshuffle its scene."""
    assert _scene(JACKET, CONCEPT_B) == _scene(JACKET, CONCEPT_B)
    assert _scene(TUMBLER, CONCEPT_A) == _scene(TUMBLER, CONCEPT_A)


def test_seed_is_stable_not_process_salted():
    """hash() is salted per process; the seed must not be."""
    assert sd._seed_for("key", "format") == sd._seed_for("key", "format")
    assert sd._seed_for("key", "format") != sd._seed_for("key", "location")


def test_every_deterministic_scene_passes_validation():
    for product in (JACKET, TUMBLER):
        classification = classify_product(product)
        for concept in CONCEPTS:
            problems = sd._scene_problems(_scene(product, concept), classification)
            assert problems == [], f"{product['name']} + {concept['concept_id']}: {problems}"


def test_concept_format_is_used_when_the_taxonomy_allows_it():
    klass = classify_product(JACKET).product_class
    if "mirror_pov" in klass.formats:
        assert _scene(JACKET, CONCEPT_A)["creative_format"] == "mirror_pov"


def test_concept_format_is_refused_when_implausible_for_the_class():
    """A mirror selfie is not a believable way to photograph a tumbler."""
    klass = classify_product(TUMBLER).product_class
    scene = _scene(TUMBLER, CONCEPT_A)  # asks for mirror_pov
    assert scene["creative_format"] in klass.formats


def test_action_carries_what_must_be_visible():
    """'Product in use' for every pin was the other half of the sameness."""
    action = _scene(JACKET, CONCEPT_A)["action"]
    assert "handle" in action or "lid" in action or "Oversized" in action
    assert action != "Product in use"


def test_menu_rotation_covers_more_than_the_first_item():
    """Rotating one seed across all axes would move them in lockstep."""
    picks = {
        sd._rotate(("a", "b", "c", "d"), "seed", axis, "")
        for axis in ("format", "location", "surface", "motivation")
    }
    assert len(picks) > 1, "every axis picked the same menu slot"
