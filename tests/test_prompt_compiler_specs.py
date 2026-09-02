"""
The compiler must forward the merchant's stated facts, not just `must_preserve`.

The Amazon engine scrapes "Neck style: Scoop Neck", "97% Polyester, 3% Elastane"
and the product's colours; before this block existed the compiler dropped all of
it, so a text-only render had nothing to hold the neckline or fabric to.

Companion to tests/test_prompt_compiler_commerce.py, which covers the commerce
blocks of the same function and nothing about listing specifications.
"""

from app.pipeline.prompt_compiler import compile_prompt

DNA = {
    "camera_dna": {},
    "composition_dna": {},
    "lighting_dna": {},
    "material_dna": {},
    "environment_dna": {},
    "realism_markers": {},
}
SCENE = {
    "capture_motivation": "mirror check before going out",
    "location": "bedroom",
    "product_class": "apparel",
    "creative_format": "mirror_pov",
    "human_presence": "full",
}


def _compile(product, product_truth):
    return compile_prompt(
        visual_dna=DNA, product=product, product_truth=product_truth, scene=SCENE
    )


def test_listing_specs_and_colours_reach_the_prompt():
    # Arrange — exactly the shape the Amazon ingestion writes to product_truth_json
    product = {"name": "Midi Dress", "materials": ["Polyester Blend"], "colors": ["Sage Green"]}
    truth = {
        "must_preserve": ["Fabric and material composition: Polyester Blend"],
        "must_not_invent": [],
        "product_overview": {
            "Neck style": "Scoop Neck",
            "Sleeve type": "Sleeveless",
            "Length": "Midi",
            "Care instructions": "Machine Wash",
            "Net Quantity": "1 Count",
        },
        "technical_specs": {"Package Dimensions": "31.8 x 25.91 x 1.4 cm; 299 g"},
    }

    # Act
    res = _compile(product, truth)

    # Assert — visual facts in, listing paperwork out
    assert res.is_valid is True
    assert "Scoop Neck" in res.prompt
    assert "Sleeveless" in res.prompt
    assert "Sage Green" in res.prompt
    assert "31.8 x 25.91 x 1.4 cm" in res.prompt
    assert "Machine Wash" not in res.prompt
    assert "1 Count" not in res.prompt


def test_facts_already_stated_are_not_repeated():
    product = {"name": "Midi Dress", "materials": [], "colors": ["Sage Green"]}
    truth = {
        "must_preserve": ["Neck style: Scoop Neck"],
        "must_not_invent": [],
        "product_overview": {"Neck style": "Scoop Neck"},
    }

    res = _compile(product, truth)

    assert res.prompt.count("Scoop Neck") == 1


def test_weight_is_not_stated_twice():
    # Arrange — Amazon states the weight inside Package Dimensions AND again as Item Weight
    truth = {
        "must_preserve": ["Midi Dress"],
        "technical_specs": {
            "Package Dimensions": "31.8 x 25.91 x 1.4 cm; 299 g",
            "Item Weight": "299 g",
        },
    }

    res = _compile({"name": "Midi Dress"}, truth)

    assert res.prompt.count("299 g") == 1


def test_products_without_specs_compile_with_an_info_warning():
    res = _compile({"name": "Jacket", "materials": ["leather"]}, {"must_preserve": ["jacket"]})

    assert res.is_valid is True
    assert any(
        w.severity == "info" and "no listing specifications" in w.message for w in res.warnings
    )
