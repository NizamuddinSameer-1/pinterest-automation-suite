"""Tests for the pure blended-score function (no I/O, no LLM)."""
from app.services.trend_scorer import DEFAULT_WEIGHTS, score_trend, tier_for


def test_default_weights_sum_to_one():
    assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) < 1e-9


def test_worked_example_scores_74_point_0_tier_a():
    out = score_trend(demand=82, money=74, winnability=61)
    assert out["score"] == 74.0
    assert out["tier"] == "A"
    assert out["breakdown"] == {
        "demand": 82, "money": 74, "winnability": 61,
        "weights_version": 1,
    }


def test_tier_bands():
    assert tier_for(90) == "S"
    assert tier_for(85) == "S"
    assert tier_for(84.9) == "A"
    assert tier_for(70) == "A"
    assert tier_for(69.9) == "B"


def test_custom_weights_respected():
    out = score_trend(demand=100, money=0, winnability=0,
                      weights={"demand": 0.5, "money": 0.3, "winnability": 0.2})
    assert out["score"] == 50.0


def test_inputs_clamped_to_0_100():
    out = score_trend(demand=999, money=-5, winnability=50)
    assert out["breakdown"]["demand"] == 100
    assert out["breakdown"]["money"] == 0
