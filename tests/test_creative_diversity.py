from app.pipeline.creative_diversity import score_diversity


def test_diversity_detects_duplicates():
    scenes = [{"creative_format": "mirror_pov", "framing": "medium", "location": "bedroom", "human_presence": "full"}] * 4
    report = score_diversity(scenes)
    assert report["score"] < 40
    assert "HIGH REPETITION" in report["warnings"][0]


def test_diversity_rewards_variety():
    scenes = [
        {"creative_format": f, "framing": "medium", "location": l, "human_presence": "full"}
        for f, l in [
            ("mirror_pov", "bedroom"),
            ("macro_detail", "desk"),
            ("outdoor_use", "street"),
            ("discovery", "store"),
        ]
    ]
    report = score_diversity(scenes)
    assert report["score"] > 80
