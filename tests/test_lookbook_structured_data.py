"""
Regression guards for lookbook JSON-LD structured data.

Two things are pinned here:

1. `aggregateRating` must NEVER be fabricated.
   The template previously read `product_data.get('review_count', 100)`, so any
   product carrying a `star_rating` automatically claimed a 100-review corpus
   that did not exist — and the rating itself is LLM-derived, not measured.
   Invented ratings/review counts breach Google's structured-data policy and can
   attract a manual action, so rating markup is emitted only when BOTH a real
   rating and a real review count are present.

2. A review page must carry Article + BreadcrumbList, not just Product.
   Without them the page gives search engines no headline, author, publication
   date or site hierarchy — the E-E-A-T signals a review article needs.
"""
import json
import re

import pytest

from app.services.article_generator import jinja_env

TEMPLATE = "bridge_page.html"


def _render(**overrides) -> str:
    ctx = dict(
        title="Test Title",
        headline="The Practical Buyer's Guide to Test Pants",
        subheadline="A grounded subheadline about fabric and fit.",
        product_name="Test Pants",
        brand="TestBrand",
        price_display="$29.99",
        affiliate_url="https://example.com/go",
        canonical_url="https://host.test/test-pants.html",
        first_image_url="https://host.test/test-pants-og.webp",
        looks=[],
        hero_look=None,
        testing_badge="Verified",
        comparison_matrix={},
        ugc_narrative={},
        fabric_deep_dive={},
        pros_cons={},
        buyer_persona={},
        final_verdict={},
        reading_time="4 min",
        author_name="Elena Vance",
        author_title="Product Research Staff",
        quick_verdict={},
        tldr_card={},
        story_intro="",
        objections_faq=[{"question": "Q1", "answer": "A1"}],
        staged_ctas={},
        trust_badges=[],
        related_lookbooks=[],
        product_data={"currency": "USD", "price": "29.99", "name": "Test Pants"},
        year=2026,
        site_base_url="https://host.test",
        date_iso="2026-09-11",
    )
    ctx.update(overrides)
    return jinja_env.get_template(TEMPLATE).render(**ctx)


def _jsonld(html: str) -> dict:
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    assert m, "no JSON-LD block found in the rendered page"
    return json.loads(m.group(1))


def _nodes(payload: dict, node_type: str) -> list[dict]:
    return [n for n in payload["@graph"] if n.get("@type") == node_type]


class TestAggregateRatingIsNeverFabricated:
    def test_absent_when_product_has_no_rating_data(self):
        product = _jsonld(_render())["@graph"][0]
        assert "aggregateRating" not in product

    def test_absent_when_rating_present_but_review_count_missing(self):
        """The old default of 100 would have invented a review corpus here."""
        html = _render(product_data={
            "currency": "USD", "price": "29.99", "name": "Test Pants",
            "star_rating": "4.6",
        })
        product = _jsonld(html)["@graph"][0]
        assert "aggregateRating" not in product, (
            "a star_rating with no review_count must not fabricate reviewCount"
        )

    def test_absent_when_review_count_present_but_rating_missing(self):
        html = _render(product_data={
            "currency": "USD", "price": "29.99", "name": "Test Pants",
            "review_count": "1284",
        })
        product = _jsonld(html)["@graph"][0]
        assert "aggregateRating" not in product

    def test_emitted_with_real_values_when_both_present(self):
        html = _render(product_data={
            "currency": "USD", "price": "29.99", "name": "Test Pants",
            "star_rating": "4.6", "review_count": "1284",
        })
        rating = _jsonld(html)["@graph"][0]["aggregateRating"]
        assert rating["ratingValue"] == "4.6"
        assert rating["reviewCount"] == "1284"
        assert rating["bestRating"] == "5"


class TestArticleAndBreadcrumbSchema:
    def test_graph_carries_all_four_node_types(self):
        payload = _jsonld(_render())
        types = {n.get("@type") for n in payload["@graph"]}
        assert types == {"Product", "Article", "BreadcrumbList", "FAQPage"}

    def test_article_carries_eeat_fields(self):
        article = _nodes(_jsonld(_render()), "Article")[0]
        assert article["headline"] == "The Practical Buyer's Guide to Test Pants"
        assert article["author"]["@type"] == "Person"
        assert article["author"]["name"] == "Elena Vance"
        assert article["datePublished"] == "2026-09-11"
        assert article["dateModified"] == "2026-09-11"
        assert article["publisher"]["@type"] == "Organization"
        assert article["mainEntityOfPage"]["@id"].endswith("test-pants.html")

    def test_breadcrumb_is_ordered_home_reviews_article(self):
        crumbs = _nodes(_jsonld(_render()), "BreadcrumbList")[0]["itemListElement"]
        assert [c["position"] for c in crumbs] == [1, 2, 3]
        assert crumbs[0]["name"] == "Home"
        assert crumbs[1]["name"] == "Reviews"
        assert crumbs[0]["item"] == "https://host.test/"
        assert crumbs[2]["name"] == "The Practical Buyer's Guide to Test Pants"

    def test_headline_is_json_escaped_not_naively_interpolated(self):
        """A quote in the headline must not break the JSON-LD block."""
        tricky = 'The "Best" Pants: 5\'11" Test'
        article = _nodes(_jsonld(_render(headline=tricky)), "Article")[0]
        assert article["headline"] == tricky
