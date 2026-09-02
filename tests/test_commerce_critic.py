import pytest
from app.pipeline.commerce_critic import critique_commerce


@pytest.mark.asyncio
async def test_commerce_critic_returns_scores(monkeypatch):
    import app.pipeline.commerce_critic as mod

    async def fake_analyze(prompt, image_path, system=None):
        return {"product_clarity": "high", "product_prominence": "high", "visual_hook": "zipper", "desire": "high", "scroll_stop": "high", "click_intent": "high", "commercial_composition": "high"}

    monkeypatch.setattr(mod.llm, "analyze_image", fake_analyze)
    res = await mod.critique_commerce("data/outputs/x/flow_var_1.jpg", {"hero_prominence": "high"}, {"visual_hook": "zipper"}, {})
    assert res["product_clarity"] == "high"
