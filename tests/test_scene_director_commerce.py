from app.pipeline.product_taxonomy import Classification, resolve_class
from app.pipeline.scene_director import _build_user_prompt


def test_build_prompt_includes_commerce_dna():
    klass = resolve_class("apparel")
    cls = Classification(klass, (), "high")
    prompt = _build_user_prompt(
        visual_dna={},
        product={"name": "Jacket"},
        product_truth={},
        classification=cls,
        reference_analysis={},
        trend_label=None,
        commerce_dna={"hero_prominence": "high"},
        concept={"objective": "product_detail", "visual_hook": "zipper"},
    )
    assert "COMMERCE DNA" in prompt
    assert "Creative Concept" in prompt
