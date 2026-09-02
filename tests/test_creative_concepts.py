# tests/test_creative_concepts.py
import pytest
from app.pipeline.creative_concepts import generate_concepts
@pytest.mark.asyncio
async def test_generate_concepts_returns_4_distinct_formats(monkeypatch):
    import app.pipeline.creative_concepts as mod
    fake_concepts = [{"concept_id":"A","objective":"product_desire","visual_hook":"zipper detail","creative_format":"macro_detail","hero_prominence":"high"},{"concept_id":"B","objective":"product_detail","visual_hook":"texture","creative_format":"styled_surface","hero_prominence":"high"},{"concept_id":"C","objective":"lifestyle_use","visual_hook":"street","creative_format":"outdoor_use","hero_prominence":"medium"},{"concept_id":"D","objective":"discovery","visual_hook":"store rack","creative_format":"discovery","hero_prominence":"high"}]
    async def fake_llm(prompt, system=None):
        return {"concepts": fake_concepts}
    monkeypatch.setattr(mod.llm, "structured_output", fake_llm)
    concepts = await generate_concepts(commerce_dna={"hero_product":"leather_jacket"}, product={"name":"Jacket"}, product_truth={}, reference_analysis={})
    assert len(concepts) == 4
    assert len(set(c["creative_format"] for c in concepts)) == 4
