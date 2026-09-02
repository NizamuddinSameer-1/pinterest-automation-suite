from app.pipeline.prompt_compiler import compile_prompt


def test_compile_includes_commerce_blocks():
    res = compile_prompt(
        visual_dna={"camera_dna": {}, "composition_dna": {}, "lighting_dna": {}, "material_dna": {}, "environment_dna": {}, "realism_markers": {}},
        product={"name": "Jacket", "materials": ["leather"]},
        product_truth={"must_preserve": ["jacket"], "must_not_invent": []},
        scene={"capture_motivation": "mirror check", "location": "bedroom", "product_class": "apparel", "creative_format": "mirror_pov", "human_presence": "full"},
        commerce_dna={"hero_prominence": "high", "must_show": ["zipper"], "hero_product": "jacket"},
        concept={"objective": "product_desire", "visual_hook": "fit"},
    )
    assert "COMMERCE" in res.prompt or "Hero" in res.prompt
    assert "REALISM MICRO-TRIGGERS" in res.prompt
    assert res.is_valid is True
