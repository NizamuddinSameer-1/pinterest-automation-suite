"""KeywordPack schema round-trip + deterministic builder."""
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
