from app.pipeline.final_judge import judge


def test_judge_requires_all_pass():
    assert judge({"decision": "PASS"}, {"product_clarity": "high"}, {"score": 90})["final"] == "PASS"
    assert judge({"decision": "REWORK"}, {"product_clarity": "high"}, {"score": 90})["final"] == "REWORK"
    assert judge({"decision": "PASS"}, {"product_clarity": "low"}, {"score": 90})["final"] == "REWORK"
