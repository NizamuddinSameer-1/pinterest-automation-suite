import pytest
from app.pipeline.commerce_strategist import generate_commerce_dna, SYSTEM_PROMPT

def test_system_prompt_mentions_hero_prominence():
    assert "hero_product" in SYSTEM_PROMPT.lower()
    assert "click_reason" in SYSTEM_PROMPT.lower()

@pytest.mark.asyncio
async def test_generate_commerce_dna_returns_required_fields(monkeypatch):
    from app.pipeline.commerce_strategist import generate_commerce_dna
    fake = {
        "commerce_dna": {
            "primary_objective": "product_desire",
            "visual_hook": "expensive_looking_leather_texture",
            "hero_product": "leather_jacket",
            "hero_prominence": "high",
            "must_show": ["leather texture","silhouette","collar"],
            "desire_mechanism": ["premium appearance"],
            "click_reason": "viewer wants to find the exact jacket",
            "context_role": "supporting",
            "product_clarity": "high"
        }
    }
    # monkeypatch llm.structured_output to return fake['commerce_dna'] wrapped
    import app.pipeline.commerce_strategist as mod
    async def fake_llm(prompt, system=None):
        return fake["commerce_dna"]
    monkeypatch.setattr(mod.llm, "structured_output", fake_llm)
    dna = await generate_commerce_dna(
        product={"name":"Leather Jacket","category":"apparel"},
        product_truth={"must_preserve":["jacket"],"must_not_invent":[]},
        visual_dna={"capture_identity":{"type":"styled_flat_lay"}},
        reference_analysis={"subject":{"primary_category":"apparel"}}
    )
    assert dna["hero_prominence"] == "high"
    assert "must_show" in dna
