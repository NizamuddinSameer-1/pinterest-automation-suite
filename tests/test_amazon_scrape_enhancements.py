"""
Unit tests for Amazon Scrape & Product Truth enhancements:
1. Pydantic AmazonItem validation
2. Shared visual_specs and derive_must_preserve
3. Class-specific must_not_invent
4. Gallery extraction (#altImages and colorImages JSON)
5. Twister color & size variation extraction
6. Raw HTML caching under data/amazon_cache/{asin}.html
"""

import json
from pathlib import Path
import pytest
from pydantic import ValidationError

from app.schemas.amazon import AmazonItem
from app.pipeline.visual_specs import (
    extract_visual_specs,
    extract_measurements,
    derive_must_preserve,
)
from app.pipeline.product_taxonomy import (
    classify_product,
    get_class_must_not_invent,
)
from app.services.amazon_paapi import AmazonProductEngine


def test_amazon_item_validation_success():
    data = {
        "asin": "B08N5WRWNW",
        "title": "Sony WH-1000XM4 Wireless Premium Noise Canceling Overhead Headphones",
        "brand": "Sony",
        "price": "$348.00",
        "price_amount": 348.0,
        "currency": "USD",
        "primary_image_url": "https://m.media-amazon.com/images/I/71o8Q5XJS5L._AC_SL1500_.jpg",
        "images": [
            "https://m.media-amazon.com/images/I/71o8Q5XJS5L._AC_SL1500_.jpg",
            "https://m.media-amazon.com/images/I/51SKmu2G9FL._AC_SL1500_.jpg",
        ],
        "selected_color": "Black",
        "variation_colors": ["Black", "Silver", "Midnight Blue"],
    }
    item = AmazonItem.model_validate(data)
    assert item.asin == "B08N5WRWNW"
    assert item.title.startswith("Sony WH-1000XM4")
    assert len(item.images) == 2
    assert item.selected_color == "Black"


def test_amazon_item_validation_failures():
    # Invalid ASIN length
    with pytest.raises(ValidationError):
        AmazonItem.model_validate({
            "asin": "INVALID_ASIN_12345",
            "title": "Some valid title",
            "primary_image_url": "https://example.com/img.jpg",
        })

    # Title too short (bot check or empty page)
    with pytest.raises(ValidationError):
        AmazonItem.model_validate({
            "asin": "B08N5WRWNW",
            "title": "Hi",
            "primary_image_url": "https://example.com/img.jpg",
        })

    # Missing primary image
    with pytest.raises(ValidationError):
        AmazonItem.model_validate({
            "asin": "B08N5WRWNW",
            "title": "Valid Product Title",
            "primary_image_url": "not-a-valid-url",
        })


def test_shared_visual_specs_extraction():
    specs = {
        "Fabric Type": "100% Cotton",
        "Collar Style": "Spread Collar",
        "Sleeve Length": "Long Sleeve",
        "Package Dimensions": "30 x 20 x 2 cm; 250 g",
        "Net Quantity": "1 Count",
        "Care Instructions": "Machine Wash",
        "Country of Origin": "India",
    }
    visual = extract_visual_specs(specs)
    visual_dict = dict(visual)
    assert "Fabric Type" in visual_dict
    assert "Collar Style" in visual_dict
    assert "Sleeve Length" in visual_dict
    # Non-visual metadata must be filtered out
    assert "Net Quantity" not in visual_dict
    assert "Care Instructions" not in visual_dict
    assert "Country of Origin" not in visual_dict

    measurements = extract_measurements(specs)
    assert len(measurements) > 0
    assert "30 x 20 x 2 cm; 250 g" in measurements[0]


def test_derive_must_preserve_avoids_marketing_bloat():
    overview = {
        "Material": "Cast Iron",
        "Finish Type": "Enamelled Gloss",
        "Color": "Cherry Red",
    }
    about = [
        "LIFETIME WARRANTY: Guaranteed satisfaction for home cooks everywhere.",
        "SUPERIOR HEAT RETENTION: Heavy-duty cast iron distributes heat evenly.",
        "VERSATILE USE: Great for braising, baking, and stewing.",
    ]
    title = "Best Dutch Oven 6 Quart Enameled Cast Iron Pot Cookware for Kitchen"

    must_preserve = derive_must_preserve(
        overview=overview,
        materials=["Cast Iron", "Enamel"],
        about_this_item=about,
        selected_color="Cherry Red",
        title=title,
    )

    # Must prioritize color, material, visual specs
    facts_str = " ".join(must_preserve).lower()
    assert "cherry red" in facts_str
    assert "cast iron" in facts_str
    # Must NOT include marketing fluff like lifetime warranty
    assert "lifetime warranty" not in facts_str
    # Must NOT be just title[:120]
    assert title[:120] not in must_preserve


def test_class_specific_must_not_invent():
    # 1. Saucepan / Cookware
    kitchen_class = classify_product({"name": "Lodge Enameled Cast Iron Dutch Oven", "category": "Kitchen & Dining"})
    kitchen_constraints = get_class_must_not_invent(kitchen_class)
    kitchen_str = " ".join(kitchen_constraints).lower()
    assert "lid" in kitchen_str or "handles" in kitchen_str or "cookware" in kitchen_str
    assert "sleeve length" not in kitchen_str
    assert "neckline" not in kitchen_str

    # 2. Apparel
    apparel_class = classify_product({"name": "Oversized Vintage Washed Graphic T-Shirt", "category": "Clothing"})
    apparel_constraints = get_class_must_not_invent(apparel_class)
    apparel_str = " ".join(apparel_constraints).lower()
    assert "neckline" in apparel_str or "sleeve" in apparel_str

    # 3. Tech
    tech_class = classify_product({"name": "Apple MacBook Pro M3 Max Space Black", "category": "Electronics"})
    tech_constraints = get_class_must_not_invent(tech_class)
    tech_str = " ".join(tech_constraints).lower()
    assert "port" in tech_str or "button" in tech_str or "device" in tech_str


@pytest.mark.asyncio
async def test_scraper_gallery_and_twister_parsing(tmp_path, monkeypatch):
    engine = AmazonProductEngine()
    engine.html_cache_dir = tmp_path

    asin = "B0SAMPLE12"
    sample_html = """
    <!DOCTYPE html>
    <html>
    <head><title>Test Product</title></head>
    <body>
        <span id="productTitle">Lodge 6 Quart Enameled Cast Iron Dutch Oven with Lid</span>
        <div id="bylineInfo">Brand: Lodge Store</div>
        <div id="corePriceDisplay_desktop_feature_div">
            <span class="a-price"><span class="a-offscreen">$79.90</span></span>
        </div>
        <div id="landingImage" data-old-hires="https://m.media-amazon.com/images/I/81x1.jpg" src="https://m.media-amazon.com/images/I/81x1_small.jpg"></div>
        <div id="altImages">
            <ul>
                <li><img src="https://m.media-amazon.com/images/I/81x1._AC_US40_.jpg" /></li>
                <li><img src="https://m.media-amazon.com/images/I/71x2._AC_US40_.jpg" /></li>
                <li><img src="https://m.media-amazon.com/images/I/61x3._AC_US40_.jpg" /></li>
            </ul>
        </div>
        <div id="variation_color_name">
            <span class="selection">Island Spice Red</span>
            <ul>
                <li><img alt="Island Spice Red" src="c1.jpg"/></li>
                <li><img alt="Caribbean Blue" src="c2.jpg"/></li>
                <li><img alt="Oyster White" src="c3.jpg"/></li>
            </ul>
        </div>
        <div id="variation_size_name">
            <span class="selection">6-Quart</span>
            <ul>
                <li><span>4.5-Quart</span></li>
                <li><span>6-Quart</span></li>
                <li><span>7.5-Quart</span></li>
            </ul>
        </div>
        <div id="productOverview_feature_div">
            <table>
                <tr><th>Material</th><td>Cast Iron</td></tr>
                <tr><th>Finish Type</th><td>Enamel</td></tr>
                <tr><th>Capacity</th><td>6 Quarts</td></tr>
            </table>
        </div>
        <script>
            var data = {
                'colorImages': {
                    'initial': [
                        {'hiRes': 'https://m.media-amazon.com/images/I/91high1.jpg'},
                        {'hiRes': 'https://m.media-amazon.com/images/I/91high2.jpg'}
                    ]
                },
                'colorToAsin': {}
            };
        </script>
    </body>
    </html>
    """
    # Write to local cache
    cache_file = tmp_path / f"{asin}.html"
    cache_file.write_text(sample_html, encoding="utf-8")

    result = await engine._fetch_from_scraper(asin, country="US")
    assert result is not None
    assert result["title"] == "Lodge 6 Quart Enameled Cast Iron Dutch Oven with Lid"
    assert result["brand"] == "Lodge"
    assert result["price_amount"] == 79.9
    assert result["selected_color"] == "Island Spice Red"
    assert "Caribbean Blue" in result["variation_colors"]
    assert result["selected_size"] == "6-Quart"
    assert "4.5-Quart" in result["variation_sizes"]
    # Check gallery has altImages converted to SL1500 and script colorImages
    assert any("71x2._AC_SL1500_.jpg" in img for img in result["images"])
    assert any("91high1.jpg" in img for img in result["images"])
    # Check saucepan must_not_invent does NOT mention neckline
    assert not any("neckline" in c.lower() for c in result["must_not_invent"])
    assert any("cookware" in c.lower() or "handles" in c.lower() for c in result["must_not_invent"])
