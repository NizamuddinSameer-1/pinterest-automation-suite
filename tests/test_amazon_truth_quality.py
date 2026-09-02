"""
`must_preserve` is a fidelity contract, so seller SEO copy must not enter it.

A live scrape of B0FT5DQTZF produced "Occasion type: Spring dresses for women,
Maxi dresses for seniors, Summer dresses for women 2025, …" and "Make Your Summer
Statement: Embrace the sunny vibes" as *strictly accurate product details* — the
render was being told to preserve a search query and a slogan.

Covers the two guards in app/services/amazon_paapi.py that filter them.
"""

from app.services.amazon_paapi import _bullet_highlight, _is_keyword_stuffing


def test_search_phrase_lists_are_rejected():
    # Arrange — verbatim from the ASIN's "Occasion type" row
    stuffed = (
        "Spring dresses for women, Maxi dresses for seniors, "
        "Summer dresses for women 2025, Midi dresses for women"
    )

    # Act / Assert
    assert _is_keyword_stuffing(stuffed) is True


def test_real_multi_part_specs_survive():
    assert _is_keyword_stuffing("97% Polyester, 3% Elastane") is False
    assert _is_keyword_stuffing("Sage Green, Dusty Rose, Black") is False
    assert _is_keyword_stuffing("Scoop Neck") is False


def test_slogan_headline_is_stripped_and_the_claim_kept():
    got = _bullet_highlight(
        "Soft Fabric Blends: cut from a lightweight polyester jersey that drapes"
    )

    assert got == "cut from a lightweight polyester jersey that drapes"


def test_pure_marketing_bullets_are_dropped():
    assert _bullet_highlight("Make Your Summer Statement: Embrace the sunny vibes") is None
    assert _bullet_highlight("Perfect Gift For Her: she will love it") is None


def test_physical_claims_without_a_headline_pass_through():
    assert _bullet_highlight("Sleeveless scoop neck with a smocked back panel") == (
        "Sleeveless scoop neck with a smocked back panel"
    )
