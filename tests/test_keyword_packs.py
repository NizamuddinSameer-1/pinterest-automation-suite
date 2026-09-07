"""KeywordPack schema round-trip + deterministic builder."""
import pytest

from app.services.keyword_packs import KeywordPack, build_pack


def test_round_trip_preserves_all_fields():
    pack = KeywordPack(
        primary="chunky knit cardigan",
        long_tails=["oversized cardigan outfit", "fall layering amazon"],
        hooks=[{"variation_index": 1, "framework": "The Skeptical Micro-Review"}],
        board_angle="Cozy Fall Knitwear & Layering",
        negative_terms=["swimwear"],
    )
    restored = KeywordPack.from_dict(pack.to_dict())
    assert restored == pack
    assert restored.pack_version == 1


def test_build_pack_assigns_frameworks_round_robin():
    pack = build_pack(
        primary="fluted ceramic vase",
        related_queries=["fluted vase", "stoneware decor", "minimalist living room"],
        board_angle="Japandi Living Room & Organic Decor",
        variations_count=4,
    )
    assert pack.primary == "fluted ceramic vase"
    assert len(pack.hooks) == 4
    frameworks = [h["framework"] for h in pack.hooks]
    assert len(set(frameworks)) == 4
    assert pack.hooks[0]["variation_index"] == 1


@pytest.mark.asyncio
async def test_batch_seo_prefers_pack_primary(monkeypatch):
    """A provided pack steers the fallback text path (no network)."""
    from app.pipeline import pinterest_seo as seo

    async def _fake_text(prompt, system=None, temperature=None):
        assert "chunky knit cardigan" in prompt
        return {"title": "Chunky Knit Amazon Find (2026) Cozy",
                "description": "Soft knit visible in warm light. Pairs with denim daily. #Knitwear #AmazonFinds",
                "keywords": ["chunky knit cardigan"],
                "board_suggestion": "Cozy Fall Knitwear"}

    async def _no_vision(*a, **kw):
        raise RuntimeError("no vision in this test")

    monkeypatch.setattr(seo.content_llm, "structured_output", _fake_text)
    monkeypatch.setattr(seo.content_llm, "analyze_image", _no_vision)
    from app.services.keyword_packs import build_pack
    pack = build_pack(primary="chunky knit cardigan",
                      related_queries=["chunky knit cardigan"],
                      board_angle="Cozy")
    out = await seo.generate_pin_seo(
        product={"name": "Cardigan"}, scene={},
        image_path="/nonexistent/x.jpg", keyword_pack=pack.to_dict(),
    )
    assert out["title"].startswith("Chunky Knit")


@pytest.mark.asyncio
async def test_bridge_copy_without_pack_unchanged(monkeypatch):
    """No pack = today's behavior (vision skipped when no images)."""
    from app.services import bridge_copilot as bc

    async def _fake_structured(prompt, system=None, temperature=None):
        return {"looks": [{"look_title": "L1"}],
                "comparison_matrix": {}, "ugc_narrative": {},
                "pros_cons": {}, "buyer_persona": {}, "final_verdict": {},
                "staged_ctas": {}, "objections_faq": [{"q": "a", "a": "b"},
                                                      {"q": "c", "a": "d"}]}

    monkeypatch.setattr(bc.content_llm, "structured_output", _fake_structured)
    out = await bc.generate_bridge_copy(
        product_data={"name": "Vase", "category": "home"}, variations_count=1,
    )
    assert out["looks"][0]["look_title"] == "L1"
