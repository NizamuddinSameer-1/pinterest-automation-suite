"""
Tests for Lookbook Editorial Compliance, Fact Verification, and Risk Elimination.
Ensures zero fabricated testing claims, zero fake author credentials, clean Schema.org,
fail-loud copy generation, and SEO assets (sitemap.xml, robots.txt).
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest

from app.services.bridge_copilot import (
    BridgeCopyUnavailable,
    _get_taxonomy_context,
    _sanitize_text_claim,
    generate_bridge_copy,
    verify_grounded_copy,
)
from app.services.article_generator import generate_lookbook_html
from app.services.git_publisher import generate_catalog_index


# ── 1. Codebase Scan: No Elena Vance or Fabricated Testing ────────────

def test_no_elena_vance_in_templates_or_services():
    """Guarantee the fictional persona 'Elena Vance' has been completely eradicated."""
    root = Path(__file__).resolve().parents[1]
    targets = [
        root / "app" / "services" / "bridge_copilot.py",
        root / "app" / "services" / "article_generator.py",
        root / "app" / "templates" / "bridge_page.html",
    ]
    for target in targets:
        assert target.exists(), f"Target file {target} must exist"
        content = target.read_text(encoding="utf-8")
        # In bridge_copilot, Elena Vance may only appear in regex sanitizers
        if target.name == "bridge_copilot.py":
            non_regex_matches = [
                line for line in content.splitlines()
                if "Elena Vance" in line and "re.sub" not in line and 'r"\\b' not in line
            ]
            assert not non_regex_matches, f"Found active Elena Vance references in {target}: {non_regex_matches}"
        else:
            assert "Elena Vance" not in content, f"Found Elena Vance in {target}"


def test_no_fake_review_schema_in_template():
    """Verify fake self-authored @type: Review is removed from bridge_page.html."""
    template_path = Path(__file__).resolve().parents[1] / "app" / "templates" / "bridge_page.html"
    content = template_path.read_text(encoding="utf-8")
    assert '"@type": "Review"' not in content, "Found self-authored @type: Review in bridge_page.html"
    assert '"@type": "Product"' in content, "Missing required @type: Product"
    assert '"@type": "FAQPage"' in content, "Missing required @type: FAQPage"


# ── 2. Fact Verifier & Sanitizer Tests ────────────────────────────────

def test_sanitize_text_claim():
    """Verify first-person testing and fake scores are sanitized."""
    raw = "I tested this for 30 days and after 12 machine wash cycles, it scored 9.8 / 10."
    sanitized = _sanitize_text_claim(raw, "source corpus")
    assert "I tested this for 30 days" not in sanitized
    assert "12 machine wash cycles" not in sanitized
    assert "9.8 / 10" not in sanitized


def test_verify_grounded_copy_enforces_author_and_real_ratings():
    """Verify grounded copy enforces editorial team author and legitimate star ratings."""
    mock_copy = {
        "headline": "The Practical Buyer's Guide to Dutch Oven",
        "subheadline": "Quality cookware breakdown",
        "author_name": "Elena Vance",
        "quick_verdict": {
            "star_rating": "4.9",
            "rating_count": "1,000+ Reviews",
        },
        "comparison_matrix": {
            "title": "Comparison",
            "tiers": [
                {
                    "tier": "Featured",
                    "score": "9.8 / 10",
                    "is_featured": True,
                    "squat_opacity": "100% squat-proof verified",
                }
            ],
        },
    }
    product_data = {
        "name": "Enameled Cast Iron Dutch Oven",
        "star_rating": 4.7,
        "review_count": 3420,
        "materials": ["Cast Iron", "Enamel"],
    }

    verified = verify_grounded_copy(mock_copy, product_data)
    assert verified["author_name"] == "SmartPickr Editorial Team"
    assert verified["quick_verdict"]["star_rating"] == "4.7"
    assert "3,420" in verified["quick_verdict"]["rating_count"]
    tier = verified["comparison_matrix"]["tiers"][0]
    assert "9.8 / 10" not in tier["score"]
    assert "100% squat-proof verified" not in tier["squat_opacity"]


# ── 3. Taxonomy Context Grounding ─────────────────────────────────────

def test_get_taxonomy_context_kitchen():
    """Verify kitchen products get cookware-appropriate framing."""
    product = {"name": "Lodge 6 Quart Enameled Cast Iron Dutch Oven", "category": "Cookware"}
    ctx = _get_taxonomy_context(product)
    assert ctx["klass_key"] == "kitchen"
    assert "Kitchen & Cookware" in ctx["domain"]
    assert "Cookware" in ctx["guide_label"]


def test_get_taxonomy_context_tech():
    """Verify tech products get hardware-appropriate framing."""
    product = {"name": "Sony WH-1000XM5 Wireless Noise Canceling Headphones", "category": "Electronics"}
    ctx = _get_taxonomy_context(product)
    assert ctx["klass_key"] == "tech"
    assert "Hardware" in ctx["domain"] or "Consumer Tech" in ctx["domain"]


# ── 4. Fail-Loud Error Handling (No Fabricated Fallbacks) ─────────────

@pytest.mark.asyncio
async def test_generate_bridge_copy_fails_loud_on_llm_error():
    """Assert BridgeCopyUnavailable is raised when LLM fails (no silent fake fallback)."""
    with patch("app.providers.llm.llm.structured_output", new_callable=AsyncMock) as mock_llm:
        mock_llm.side_effect = RuntimeError("LLM rate limited or timed out")

        product = {"name": "Test Product", "category": "General"}
        with pytest.raises(BridgeCopyUnavailable):
            await generate_bridge_copy(product, variations_count=4)


# ── 5. Lookbook HTML Assembly & Performance ──────────────────────────

@pytest.mark.asyncio
async def test_generate_lookbook_html_performance_and_schema(tmp_path):
    """Verify lookbook HTML uses /lookbook.css, standalone WebP images, and clean schema."""
    # Create fake input image
    from PIL import Image
    dummy_img = tmp_path / "var_1.jpg"
    im = Image.new("RGB", (200, 300), color="blue")
    im.save(dummy_img, format="JPEG")

    mock_copy = {
        "headline": "The Practical Guide to Cast Iron Pan",
        "subheadline": "Durable kitchen essential",
        "reading_time": "4 min read",
        "author_name": "SmartPickr Editorial Team",
        "author_title": "Kitchen & Home Research Staff",
        "testing_badge": "Verified Spec & Feature Breakdown",
        "trust_badges": ["Direct Amazon Fulfillment", "30-Day Free Returns"],
        "guide_label": "Cookware Guide",
        "curator_tag": "Spec Breakdown",
        "specs_label": "Technical Specs",
        "quick_verdict": {
            "best_for": "Home cooks",
            "why_worth_it": "High durability",
            "scenario_badge": "Editor's Pick",
            "star_rating": "4.6",
            "rating_count": "1,200 Ratings",
        },
        "story_intro": "Editorial overview of cast iron.",
        "looks": [
            {
                "look_number": 1,
                "look_title": "Perspective #1: Everyday Utility",
                "look_subtitle": "Practical heat retention",
                "look_story": "Observational breakdown.",
                "styling_advice": "Season after every wash.",
                "angle_badge": "Perspective #1",
                "inline_cta": "View on Amazon",
            }
        ],
        "comparison_matrix": {"title": "Specs", "tiers": []},
        "ugc_narrative": {
            "friction_title": "The Everyday Struggle",
            "friction_body": "Cheap non-stick pans wear out quickly.",
            "testing_log_title": "Breakdown",
            "testing_log_entries": [],
        },
        "fabric_deep_dive": {"title": "Materials", "composition": "Cast Iron"},
        "pros_cons": {"pros": ["Durable"], "cons": ["Heavy"]},
        "buyer_persona": {"who_should_buy": ["Home cooks"], "who_should_skip": ["Campers"]},
        "objections_faq": [{"question": "Is it oven safe?", "answer": "Yes, up to 500F."}],
        "final_verdict": {"summary": "Great pan.", "bottom_line": "Buy it."},
        "staged_ctas": {"hero_cta": "Check Price", "bottom_cta": "Get on Amazon"},
    }

    product_data = {
        "name": "Classic Cast Iron Skillet",
        "brand": "Lodge",
        "price": 29.99,
        "currency": "$",
        "category": "Kitchen",
        "star_rating": 4.6,
        "review_count": 1200,
        "materials": ["Cast Iron"],
    }

    slug, html, og_bytes = await generate_lookbook_html(
        job_id="test-compliance-job",
        product_data=product_data,
        image_paths=[str(dummy_img)],
        copy_data=mock_copy,
    )

    assert "lookbook.css" in html
    assert 'loading="lazy"' in html
    assert 'width="640" height="960"' in html
    assert '"@type": "AggregateRating"' in html
    assert '"ratingValue": "4.6"' in html
    assert "Elena Vance" not in html
    assert len(og_bytes) > 0


# ── 6. Sitemap.xml and Robots.txt Generation ──────────────────────────

@pytest.mark.asyncio
async def test_sitemap_and_robots_generation(tmp_path):
    """Verify generate_catalog_index creates valid sitemap.xml and robots.txt."""
    # Create a dummy HTML lookbook in tmp_path
    dummy_html = tmp_path / "classic-cast-iron-skillet-12345678.html"
    dummy_html.write_text(
        "<html><head><title>Classic Cast Iron Skillet | SmartPickr</title></head><body><h1>Guide</h1></body></html>",
        encoding="utf-8",
    )

    await generate_catalog_index(repo_dir=tmp_path)

    sitemap_file = tmp_path / "sitemap.xml"
    robots_file = tmp_path / "robots.txt"

    assert sitemap_file.exists(), "sitemap.xml was not created"
    assert robots_file.exists(), "robots.txt was not created"

    sitemap_content = sitemap_file.read_text(encoding="utf-8")
    assert "<urlset" in sitemap_content
    assert "classic-cast-iron-skillet-12345678.html" in sitemap_content
    assert "<lastmod>" in sitemap_content

    robots_content = robots_file.read_text(encoding="utf-8")
    assert "User-agent: *" in robots_content
    assert "Sitemap:" in robots_content
