"""
Bridge Copilot — Generates high-converting, magazine-grade editorial fashion blog copy.
Produces authentic "I Tested" UGC try-on narratives, above-the-fold comparison matrices,
fabric deep-dives, pros/cons, buyer personas, and objection FAQs.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.providers.llm import llm

logger = logging.getLogger("pre.services.bridge_copilot")


def _get_taxonomy_context(product: dict[str, Any]) -> dict[str, Any]:
    """Derive taxonomy context, curated badges, and tone from product category."""
    raw_cat = (product.get("category") or "").lower()
    raw_name = (product.get("name") or "").lower()
    combined = f"{raw_cat} {raw_name}"

    # Classify into specific taxonomy clusters
    if any(k in combined for k in ("dress", "skirt", "gown", "sundress", "maxi", "mini")):
        klass_key = "dresses"
    elif any(k in combined for k in ("pant", "jean", "legging", "trousers", "jogger", "yoga", "flared")):
        klass_key = "pants_leggings"
    elif any(k in combined for k in ("top", "shirt", "blouse", "sweater", "cardigan", "hoodie", "jacket", "coat")):
        klass_key = "tops_outerwear"
    elif any(k in combined for k in ("shoe", "sneaker", "boot", "sandal", "heel", "loafer")):
        klass_key = "shoes"
    elif any(k in combined for k in ("bag", "tote", "purse", "backpack", "jewelry", "watch", "sunglass", "belt")):
        klass_key = "accessories"
    elif any(k in combined for k in ("serum", "cream", "lotion", "skincare", "makeup", "lipstick", "perfume", "hair")):
        klass_key = "beauty_skincare"
    elif any(k in combined for k in ("kitchen", "cookware", "pan", "pot", "knife", "blender", "home", "decor")):
        klass_key = "home_kitchen"
    elif any(k in combined for k in ("headphone", "earbud", "speaker", "gadget", "charger", "desk", "tech", "keyboard")):
        klass_key = "tech_gadgets"
    else:
        klass_key = "general_fashion"

    if klass_key in ("dresses", "pants_leggings", "tops_outerwear", "shoes", "accessories", "general_fashion"):
        return {
            "domain": "fashion & lifestyle wear-tester",
            "guide_label": "Real-World Styling & Pairings Guide",
            "curator_tag": "30-Day Real-World Try-On Test",
            "review_badge_text": "Verified Wear-Test Evaluation",
            "specs_label": "Fabric Density & Material Breakdown",
            "best_for": "Anyone looking for butter-soft comfort, flattering silhouette, and effortless day-to-night styling",
            "why_worth_it": "Delivers luxury-tier drape and 4-way stretch recovery at a fraction of high-end boutique pricing",
            "scenario_badge": "Editor's Choice • 30-Day Wear Test Winner",
            "testing_badge": "Tested: 30 Days of Daily Wear & 12 Machine Washes",
            "faq_1_q": "Does this run true to size or should I size up?",
            "faq_1_a": "Runs true to size with generous 4-way stretch. If you are between sizes and prefer a compressive fit, size down; for a relaxed fit, order your regular size.",
            "faq_2_q": "Is the fabric 100% squat-proof and non-sheer?",
            "faq_2_a": "Yes, our bright studio and gym testing confirmed zero show-through or sheerness during deep squats and high stretches.",
            "faq_3_q": "How does the waistband hold up during active movement?",
            "faq_3_a": "The reinforced crossover waistband stays anchored above the hips with zero roll-down or pinching throughout all-day wear.",
            "faq_4_q": "Does the fabric pill after repeated machine washing?",
            "faq_4_a": "Tested across 12 wash cycles — zero surface pilling, zero elasticity loss, and shape retention remained identical to day one.",
            "tip": "Style with an oversized boxy knit, tailored trench, or cropped active tank for effortless outfit balance.",
            "hero_cta": "Check Amazon Price & In-Stock Deals",
            "look_cta": "Shop This Look on Amazon",
            "mid_cta": "View Fabric Specs & Deals on Amazon",
            "bottom_cta": "Get the Look on Amazon (Prime Fast Shipping)",
            "sticky_cta": "Check Deal on Amazon",
            "trust_badges": ["Prime Fast Delivery", "30-Day Wear Tested", "100% Squat-Proof"],
            "pros": [
                "Butter-soft brushed 4-way stretch moves with your body with zero resistance",
                "High-rise contour waistband stays securely in place with zero roll-down",
                "100% Non-sheer, squat-proof fabric density verified under bright lighting",
                "Deep, functional drop-in pockets fit large smartphones securely without sagging"
            ],
            "cons": [
                "Popular seasonal colorways occasionally sell out during major restock windows",
                "Inseam length runs slightly generous for petite frames under 5'2\""
            ],
            "who_should_buy": [
                "Anyone wanting luxury-brand activewear drape and comfort without the $100+ price tag",
                "Shoppers needing versatile athleisure that transitions from gym workouts to coffee runs",
                "People who demand squat-proof, non-sheer fabric with real pocket utility"
            ],
            "who_should_skip": [
                "Athletes needing ultra-rigid high-compression racing gear for marathons",
                "Shoppers looking strictly for stiff, non-stretch woven dress tailoring"
            ],
        }
    elif klass_key == "beauty_skincare":
        return {
            "domain": "beauty & dermatological skincare tester",
            "guide_label": "Application & Routine Layering Guide",
            "curator_tag": "30-Day Clinical & Daily Use Evaluation",
            "review_badge_text": "Authentic Ingredient & Efficacy Test",
            "specs_label": "Key Actives & Formulation Details",
            "best_for": "Individuals looking for visible hydration, barrier support, and radiant glow with zero greasy residue",
            "why_worth_it": "Clinically proven active ingredients at an honest price point that competes with luxury counter brands",
            "scenario_badge": "Top Beauty Pick • 4-Week Skin Barrier Trial",
            "testing_badge": "Tested: 4 Weeks of Twice-Daily Application",
            "faq_1_q": "Is this suitable for sensitive or acne-prone skin?",
            "faq_1_a": "Yes, non-comedogenic and fragrance-free formulation tested with zero irritation or breakouts on sensitive skin.",
            "faq_2_q": "How quickly can I expect to see noticeable results?",
            "faq_2_a": "Hydration is immediate upon first application; texture and barrier resilience showed measurable improvement by Day 14.",
            "faq_3_q": "Does this layer well under sunscreen and makeup?",
            "faq_3_a": "Absorbs within 60 seconds with zero pilling or tackiness beneath makeup or SPF.",
            "faq_4_q": "Is it certified cruelty-free and clean?",
            "faq_4_a": "Formulated without parabens, sulfates, or harsh synthetic fragrances, and 100% cruelty-free.",
            "tip": "Apply 2-3 drops onto slightly damp skin morning and night, followed by your favorite moisturizer.",
            "hero_cta": "Check Amazon Price & In-Stock Deals",
            "look_cta": "View on Amazon",
            "mid_cta": "Check Ingredients & Availability on Amazon",
            "bottom_cta": "Order on Amazon (Fast Prime Delivery)",
            "sticky_cta": "Check Amazon Deal",
            "trust_badges": ["Prime 1-2 Day Delivery", "Derm Tested", "Hassle-Free 30-Day Returns"],
            "pros": [
                "Lightweight, fast-absorbing texture leaves zero sticky or greasy residue",
                "Noticeable boost in skin suppleness and natural hydration within 72 hours",
                "Clean, non-comedogenic formula that pairs seamlessly with daily SPF",
                "Exceptional active concentration compared to triple-priced luxury serums"
            ],
            "cons": [
                "Dropper dispenser requires gentle squeezing to dispense exact micro-drops",
                "Fragrance-free formula has a natural clean scent that dissipates in seconds"
            ],
            "who_should_buy": [
                "Anyone wanting supple, glass-like hydration without heavy pore-clogging oils",
                "Skincare enthusiasts looking for proven actives at an accessible price"
            ],
            "who_should_skip": [
                "Users looking for heavy, wax-based night balms"
            ],
        }
    else:
        return {
            "domain": "lifestyle & curated product tester",
            "guide_label": "Everyday Testing & Setup Guide",
            "curator_tag": "30-Day Hands-On Evaluation",
            "review_badge_text": "Authentic Wear & Use Breakdown",
            "specs_label": "Technical Specifications & Materials",
            "best_for": "Anyone looking for a reliable, top-rated solution with proven everyday utility",
            "why_worth_it": "Exceptional price-to-performance ratio backed by verified purchaser satisfaction",
            "scenario_badge": "Editor's Choice • Verified Quality",
            "testing_badge": "Tested: 30 Days of Real-World Daily Use",
            "faq_1_q": "Is this worth the price compared to alternatives?",
            "faq_1_a": "It delivers high-tier performance and durable construction at an accessible price point.",
            "faq_2_q": "What is the return policy if it does not meet my needs?",
            "faq_2_a": "Protected by Amazon's 30-day hassle-free return guarantee for complete peace of mind.",
            "faq_3_q": "Does it arrive quickly with Prime?",
            "faq_3_a": "Yes, fulfilled directly through Amazon Prime for fast 1-2 day tracked delivery.",
            "faq_4_q": "How durable is the build quality for long-term use?",
            "faq_4_a": "Engineered with reinforced materials tested to maintain integrity across prolonged daily use.",
            "tip": "Use according to standard manufacturer guidelines for optimal longevity.",
            "hero_cta": "Check Amazon Price & In-Stock Deals",
            "look_cta": "View Details on Amazon",
            "mid_cta": "View Current Stock & Options on Amazon",
            "bottom_cta": "Check Availability on Amazon (Prime Fast Shipping)",
            "sticky_cta": "Check Deal on Amazon",
            "trust_badges": ["Prime Fast Shipping", "Top Rated Quality", "30-Day Easy Returns"],
            "pros": [
                "Crafted with durable, wear-resistant materials designed for longevity",
                "Intuitive, comfortable design that integrates smoothly into daily routines",
                "Exceptional price-to-quality ratio compared to higher-priced brand names",
                "Backed by direct Amazon fulfillment and customer satisfaction guarantees"
            ],
            "cons": [
                "Popular styles frequently see temporary stock shortages during seasonal promotions",
                "Instruction booklet is concise; standard operation is straightforward"
            ],
            "who_should_buy": [
                "Smart shoppers who value proven quality and real-world durability",
                "Anyone wanting a dependable everyday solution without paying luxury markups"
            ],
            "who_should_skip": [
                "Buyers seeking industrial commercial-grade heavy machinery"
            ],
        }


def _get_fallback_copy(product: dict[str, Any], variations_count: int = 4) -> dict[str, Any]:
    """Deterministic fallback copy generator with full UGC narrative and comparison matrix."""
    name = product.get("name") or "Curated Discovery"
    brand = product.get("brand") or "Curated Collection"
    price_val = product.get("price") or "32.00"
    ctx = _get_taxonomy_context(product)

    looks = []
    look_presets = [
        {
            "title": "Everyday Casual & Morning Movement",
            "subtitle": "Effortless morning comfort paired with relaxed basics",
            "story": f"From the first wear, the {name} stands out for its natural drape and balanced silhouette. The fabric moves effortlessly without bunching, making it ideal for walking, coffee runs, and long hours on your feet.",
            "styling": "Pair with a crisp neutral crewneck, oversized denim jacket, and clean low-profile sneakers for a balanced street-style profile.",
            "badge": "Look #1: Everyday Casual",
        },
        {
            "title": "Studio Work & 360-Degree Silhouette",
            "subtitle": "Testing waistband anchorage, drape, and hip contouring",
            "story": f"During full-day studio wear, the high waistband stayed firmly anchored above the hips without a single instance of rolling down. The contour seam creates an elongated leg line that feels both athletic and tailored.",
            "styling": "Style with a cropped structured blazer and pointed mules or chunky loafers to take this look into casual work settings.",
            "badge": "Look #2: Studio & Workspace",
        },
        {
            "title": "High-Impact Movement & Squat Opacity Test",
            "subtitle": "Testing flex durability under bright direct lighting",
            "story": f"We took this through high-flexion squats and intense stretching under direct fluorescent studio lights. The knit density held up with 100% opacity — zero sheerness, zero show-through, and complete squat-proof confidence.",
            "styling": "Pair with a high-neck performance tank and responsive trainers for studio yoga or gym sessions.",
            "badge": "Look #3: Motion & Gym Test",
        },
        {
            "title": "Tactile Texture & Micro-Weave Detail",
            "subtitle": "Inspecting the seams, waistband recovery, and wash resilience",
            "story": f"Up close, the flatlock stitching shows thorough reinforcement along high-stress points. Even after 12 machine wash cycles, the fabric maintains its rich matte surface with zero pilling or elasticity fatigue.",
            "styling": "Keep the color palette monochromatic or earth-toned to highlight the subtle textural richness of the garment.",
            "badge": "Look #4: Macro Detail & Finish",
        },
    ]

    for i in range(variations_count):
        preset = look_presets[i % len(look_presets)]
        looks.append({
            "look_number": i + 1,
            "look_title": f"Look #{i + 1}: {preset['title']}",
            "look_subtitle": preset["subtitle"],
            "look_story": preset["story"],
            "styling_advice": preset["styling"],
            "angle_badge": preset["badge"],
            "inline_cta": ctx.get("look_cta", "Shop This Look on Amazon"),
        })

    # Fabric details from scraped product data
    materials_list = product.get("materials", [])
    raw_material_str = ", ".join(materials_list) if materials_list else "Premium Dual-Knit Polyamide & Spandex Blend"

    return {
        "headline": f"I Tested The {name} for 30 Days: Here's What Actually Happened",
        "subheadline": f"After 50+ hours of real-world wear-testing and 12 machine wash cycles, here is the unfiltered truth on fit, fabric longevity, and how it compares to $90+ alternatives.",
        "reading_time": "4 min read",
        "author_name": "Elena Vance",
        "author_title": "Fashion & Lifestyle Wear-Tester",
        "testing_badge": ctx.get("testing_badge", "Tested: 30 Days of Daily Wear & 12 Machine Washes"),
        
        # Above-the-Fold Comparison Matrix
        "comparison_matrix": {
            "title": "Quick Comparison: How It Stacks Up",
            "tiers": [
                {
                    "tier": "Our Tested Winner",
                    "name": f"{brand} {name}",
                    "score": "9.8 / 10",
                    "badge": "⭐ Top Pick",
                    "fabric_feel": "Butter-Soft 4-Way Stretch",
                    "squat_opacity": "100% Squat-Proof & Opaque",
                    "price": f"${price_val}",
                    "verdict": "Best overall balance of luxury drape, comfort & price",
                    "is_featured": True,
                },
                {
                    "tier": "Budget Baseline",
                    "name": "Standard Cotton/Poly Alternatives",
                    "score": "8.1 / 10",
                    "badge": "Budget Option",
                    "fabric_feel": "Basic Cotton Blend (Thin)",
                    "squat_opacity": "Slightly Sheer under Gym Light",
                    "price": "$18.99",
                    "verdict": "Low upfront cost, but tends to bag at knees after 5 washes",
                    "is_featured": False,
                },
                {
                    "tier": "Designer Benchmark",
                    "name": "High-End Luxury Boutique Brands",
                    "score": "9.1 / 10",
                    "badge": "Luxury Benchmark",
                    "fabric_feel": "Technical Synthetic",
                    "squat_opacity": "100% Opaque",
                    "price": "$88.00+",
                    "verdict": "Flattering drape, but nearly triple the price point",
                    "is_featured": False,
                },
            ]
        },

        # 5-Stage UGC Experiential Story Narrative
        "ugc_narrative": {
            "friction_title": "The Everyday Struggle: Why Most Alternatives Failed Me",
            "friction_body": f"For months, my daily wardrobe rotation was a constant cycle of frustration. Most active and casual pants I tested suffered from the exact same flaws: waistbands that constantly roll down mid-stride, fabrics that become sheer the second you bend over, and synthetic materials that pill after three gentle wash cycles.",
            "failed_solutions": f"I had already spent over $150 testing both budget fast-fashion pairs and expensive designer brands. The cheap pairs bagged at the knees within two hours of wear, while the luxury pairs required delicate dry-cleaning that made zero sense for everyday life.",
            "discovery_moment": f"When the {name} by {brand} began trending on Pinterest and TikTok with thousands of try-on clips, I was skeptical. At ${price_val}, it claimed to deliver the buttery four-way stretch and structured silhouette of pairs costing three times as much. I ordered it to put it through a strict 30-day wear-test.",
            "testing_log_title": "The 30-Day Wear & Wash Log",
            "testing_log_entries": [
                {
                    "phase": "Week 1: Initial Try-On & Fit",
                    "desc": "Right out of the packaging, the brushed fabric felt substantial with zero synthetic chemical odor. The high waistband stayed firmly anchored above the hips with zero pinching or roll-down."
                },
                {
                    "phase": "Week 2: The Squat & Movement Test",
                    "desc": "Tested through multiple gym sessions and full-day walking. Under bright studio and gym lighting, opacity was 100% squat-proof with zero show-through."
                },
                {
                    "phase": "Week 3 & 4: Wash Durability & Elasticity",
                    "desc": "Ran through 12 standard cold-water wash cycles and tumble dried low. Zero pilling, zero shrinkage, and seam integrity remained as crisp as day one."
                }
            ]
        },

        "quick_verdict": {
            "best_for": ctx["best_for"],
            "why_worth_it": ctx["why_worth_it"],
            "scenario_badge": ctx.get("scenario_badge", "Editor's Pick • 30-Day Wear Test Winner"),
            "star_rating": "4.9",
            "rating_count": "1,420+ Verified Looks",
        },
        "story_intro": (
            f"If you've been searching for a versatile wardrobe staple that effortlessly bridges the gap between butter-soft comfort and modern street-ready polish, the {name} by {brand} demands your attention. "
            f"We took this viral piece through 30 days of rigorous real-world wear testing — evaluating everything from morning coffee runs to full-day active movement. Here is our complete, unfiltered breakdown."
        ),
        "looks": looks,
        "fabric_deep_dive": {
            "title": "Tactile Materiality & Fabric Breakdown",
            "composition": raw_material_str,
            "hand_feel": "Buttery-soft brushed finish with substantial weight and zero synthetic crunch",
            "stretch_recovery": "4-Way omni-stretch with high elasticity that recovers shape instantly without knee-bagging",
            "opacity_test": "100% Non-sheer, squat-proof fabric density verified under bright direct lighting",
            "wash_longevity": "Maintains color depth, elasticity, and anti-pilling surface finish after repeated gentle washes",
        },
        "pros_cons": {
            "pros": ctx.get("pros", [
                "Buttery-soft, four-way stretch fabric with zero break-in stiffness",
                "High-waisted silhouette stays securely in place throughout active movement",
                "Substantial fabric density provides complete squat-proof opacity",
                "Versatile styling transitions seamlessly from morning errands to evening casual"
            ]),
            "cons": ctx.get("cons", [
                "Higher-demand colorways occasionally sell out during peak restock windows",
                "Inseam length runs slightly generous for petite frames under 5'2\""
            ]),
        },
        "buyer_persona": {
            "who_should_buy": ctx.get("who_should_buy", [
                "Shoppers seeking designer-tier comfort and flattering drape at an accessible price",
                "Anyone looking for a versatile wardrobe staple that pairs with sneakers and jackets",
                "People who prioritize non-sheer, durable activewear with functional pockets"
            ]),
            "who_should_skip": ctx.get("who_should_skip", [
                "Athletes requiring rigid high-compression racing gear for competitive marathons",
                "Anyone looking exclusively for stiff, non-stretch woven tailoring"
            ]),
        },
        "objections_faq": [
            {"question": ctx["faq_1_q"], "answer": ctx["faq_1_a"]},
            {"question": ctx["faq_2_q"], "answer": ctx["faq_2_a"]},
            {"question": ctx["faq_3_q"], "answer": ctx["faq_3_a"]},
            {"question": ctx.get("faq_4_q", "Is the fabric opaque and squat-proof?"), "answer": ctx.get("faq_4_a", "Yes, dense dual-knit weave ensures 100% opacity even under bright daylight and deep stretching.")},
        ],
        "styling_tips": ctx["tip"],
        "staged_ctas": {
            "hero_cta": ctx["hero_cta"],
            "look_cta": ctx.get("look_cta", "Shop This Look on Amazon"),
            "mid_cta": ctx["mid_cta"],
            "bottom_cta": ctx["bottom_cta"],
            "sticky_cta": ctx["sticky_cta"],
        },
        "final_verdict": {
            "summary": f"The {name} successfully proves that high-end aesthetic styling and all-day cloud-like comfort don't have to cost three figures. Whether styled casually with an oversized knit or dressed up with tailored layers, it delivers an exceptionally flattering silhouette.",
            "bottom_line": "An absolute wardrobe workhorse that outperforms competitors at double its price point. Highly recommended.",
        },
        "trust_badges": ctx["trust_badges"],
        "guide_label": ctx["guide_label"],
        "curator_tag": ctx["curator_tag"],
        "review_badge_text": ctx["review_badge_text"],
        "specs_label": ctx["specs_label"],
    }


async def generate_bridge_copy(
    product_data: dict[str, Any],
    scene_data: dict[str, Any] | None = None,
    variations_count: int = 4,
) -> dict[str, Any]:
    """
    Generate rich multi-look editorial blog copy via a single LLM structured call.
    Produces full sequential styling narratives for all candidate pin variations,
    above-the-fold comparison table, and first-person UGC testing logs.
    """
    ctx = _get_taxonomy_context(product_data)
    scene = scene_data or {}
    
    product_brief = {
        "product_name": product_data.get("name", "Curated Item"),
        "brand": product_data.get("brand", "Curated Collection"),
        "category": product_data.get("category", "Fashion & Lifestyle"),
        "materials": product_data.get("materials", []),
        "key_attributes": product_data.get("key_attributes", []),
        "price": product_data.get("price", "32.00"),
        "currency": product_data.get("currency", "$"),
        "scene_location": scene.get("location", ""),
        "creative_format": scene.get("creative_format", ""),
        "variations_count": variations_count,
        "curator_perspective": ctx["domain"],
    }

    system_prompt = (
        f"You are an authentic, high-taste {ctx['domain']} writing a first-person UGC try-on review blog post. "
        f"Your tone is personal, tactile, candid, and credible ('I tested this for 30 days', 'Here is what happened'). "
        f"Avoid generic marketing fluff or 3rd-person PR speak.\n\n"
        f"You MUST generate:\n"
        f"1. A first-person 'I Tested' headline (e.g. 'I Tested The [Product] for 30 Days: Here's What Happened').\n"
        f"2. A 3-item quick comparison matrix comparing the Featured Pick vs Budget Baseline vs Luxury Benchmark.\n"
        f"3. A 5-stage UGC testing narrative: Friction, Failed Past Solutions, Discovery, and a 3-Phase Testing Log.\n"
        f"4. Exactly {variations_count} distinct styled looks (Look #1 to Look #{variations_count}) with unique scenarios, rich try-on stories, and styling advice.\n\n"
        f"Return ONLY valid JSON matching this exact structure:\n"
        f"{{\n"
        f'  "headline": "I Tested The [Product Name] for 30 Days: Here Is What Actually Happened",\n'
        f'  "subheadline": "After 50+ hours of real-world wear-testing and 12 wash cycles, here is the unfiltered breakdown on fit, fabric longevity, and how it holds up.",\n'
        f'  "reading_time": "4 min read",\n'
        f'  "author_name": "Elena Vance",\n'
        f'  "author_title": "Fashion & Lifestyle Wear-Tester",\n'
        f'  "testing_badge": "Tested: 30 Days of Daily Wear & 12 Machine Washes",\n'
        f'  "comparison_matrix": {{\n'
        f'    "title": "Quick Comparison: How It Stacks Up",\n'
        f'    "tiers": [\n'
        f'      {{\n'
        f'        "tier": "Our Tested Winner",\n'
        f'        "name": "{product_brief["brand"]} {product_brief["product_name"]}",\n'
        f'        "score": "9.8 / 10",\n'
        f'        "badge": "⭐ Top Pick",\n'
        f'        "fabric_feel": "Butter-Soft 4-Way Stretch",\n'
        f'        "squat_opacity": "100% Squat-Proof & Opaque",\n'
        f'        "price": "${product_brief["price"]}",\n'
        f'        "verdict": "Best overall balance of luxury drape, comfort & price",\n'
        f'        "is_featured": true\n'
        f'      }},\n'
        f'      {{\n'
        f'        "tier": "Budget Baseline",\n'
        f'        "name": "Standard Cotton/Poly Alternatives",\n'
        f'        "score": "8.1 / 10",\n'
        f'        "badge": "Budget Option",\n'
        f'        "fabric_feel": "Basic Cotton Blend (Thin)",\n'
        f'        "squat_opacity": "Slightly Sheer under Gym Light",\n'
        f'        "price": "$18.99",\n'
        f'        "verdict": "Low upfront cost, but tends to pill after 5 washes",\n'
        f'        "is_featured": false\n'
        f'      }},\n'
        f'      {{\n'
        f'        "tier": "Designer Benchmark",\n'
        f'        "name": "High-End Luxury Boutique Brands",\n'
        f'        "score": "9.1 / 10",\n'
        f'        "badge": "Luxury Benchmark",\n'
        f'        "fabric_feel": "Technical Synthetic",\n'
        f'        "squat_opacity": "100% Opaque",\n'
        f'        "price": "$88.00+",\n'
        f'        "verdict": "Flattering drape, but nearly triple the price point",\n'
        f'        "is_featured": false\n'
        f'      }}\n'
        f'    ]\n'
        f'  }},\n'
        f'  "ugc_narrative": {{\n'
        f'    "friction_title": "The Everyday Struggle: Why Most Alternatives Failed Me",\n'
        f'    "friction_body": "Personal frustration with waistbands rolling down, sheer see-through moments, and cheap fabric pilling.",\n'
        f'    "failed_solutions": "Why spending money on past budget and luxury pairs left me disappointed.",\n'
        f'    "discovery_moment": "How I discovered this piece on Pinterest and why I decided to put it through a strict 30-day wear test.",\n'
        f'    "testing_log_title": "The 30-Day Wear & Wash Log",\n'
        f'    "testing_log_entries": [\n'
        f'      {{"phase": "Week 1: Initial Try-On & Fit", "desc": "Fit observations, waistband anchorage, and immediate skin feel."}},\n'
        f'      {{"phase": "Week 2: Squat & Movement Stress Test", "desc": "Opacity under bright lighting and motion flexibility."}},\n'
        f'      {{"phase": "Week 3 & 4: Wash Durability & Elasticity", "desc": "Results after 12 wash cycles and long-term shape retention."}}\n'
        f'    ]\n'
        f'  }},\n'
        f'  "quick_verdict": {{\n'
        f'    "best_for": "{ctx["best_for"]}",\n'
        f'    "why_worth_it": "{ctx["why_worth_it"]}",\n'
        f'    "scenario_badge": "{ctx.get("scenario_badge", "Editor Choice • Verified Fit Test")}",\n'
        f'    "star_rating": "4.9",\n'
        f'    "rating_count": "1,420+ Verified Looks"\n'
        f'  }},\n'
        f'  "story_intro": "Engaging first-person intro setting up the 30-day wear test.",\n'
        f'  "looks": [\n'
        f'    {{\n'
        f'      "look_number": 1,\n'
        f'      "look_title": "Look #1: Morning Coffee Run & Effortless Movement",\n'
        f'      "look_subtitle": "Casual street styling paired with oversized knitwear and low-top sneakers",\n'
        f'      "look_story": "Rich first-person wear test describing drape, waistband comfort, stretch feel, and street movement.",\n'
        f'      "styling_advice": "Specific pairing advice (e.g. style with cropped trench coat, chunky retro sneakers).",\n'
        f'      "angle_badge": "Look #1: Everyday Casual"\n'
        f'    }}\n'
        f'  ],\n'
        f'  "fabric_deep_dive": {{\n'
        f'    "title": "Tactile Materiality & Fabric Breakdown",\n'
        f'    "composition": "Exact material blend (e.g. 80% Nylon, 20% Spandex dual-knit blend)",\n'
        f'    "hand_feel": "Description of buttery softness, brushed touch, and breathability",\n'
        f'    "stretch_recovery": "Description of 4-way stretch and non-sagging elasticity recovery",\n'
        f'    "opacity_test": "100% Squat-proof and non-sheer test verdict under direct lighting",\n'
        f'    "wash_longevity": "Machine wash test notes and shape retention"\n'
        f'  }},\n'
        f'  "pros_cons": {{\n'
        f'    "pros": ["4 clear, compelling strength bullet points"],\n'
        f'    "cons": ["2 realistic, honest considerations/nuances that build authentic buyer trust"]\n'
        f'  }},\n'
        f'  "buyer_persona": {{\n'
        f'    "who_should_buy": ["3 bullet points detailing who will love this product most"],\n'
        f'    "who_should_skip": ["2 bullet points detailing who might prefer an alternative"]\n'
        f'  }},\n'
        f'  "objections_faq": [\n'
        f'    {{"question": "Does this run true to size?", "answer": "Detailed sizing recommendation."}},\n'
        f'    {{"question": "Is the fabric 100% squat-proof?", "answer": "Clear opacity reassurance."}},\n'
        f'    {{"question": "How does it hold up after machine washing?", "answer": "Care instructions."}},\n'
        f'    {{"question": "What is the return policy?", "answer": "Protected by Amazon 30-day returns."}}\n'
        f'  ],\n'
        f'  "final_verdict": {{\n'
        f'    "summary": "Closing verdict summarizing the try-on experience and value.",\n'
        f'    "bottom_line": "Punchy 1-sentence final takeaway."\n'
        f'  }},\n'
        f'  "staged_ctas": {{\n'
        f'    "hero_cta": "{ctx["hero_cta"]}",\n'
        f'    "look_cta": "{ctx.get("look_cta", "Shop This Look on Amazon")}",\n'
        f'    "mid_cta": "{ctx["mid_cta"]}",\n'
        f'    "bottom_cta": "{ctx["bottom_cta"]}",\n'
        f'    "sticky_cta": "{ctx["sticky_cta"]}"\n'
        f'  }}\n'
        f"}}"
    )

    user_prompt = (
        f"Generate a comprehensive, high-converting first-person UGC review blog post for the following product:\n"
        f"{json.dumps(product_brief, indent=2)}\n\n"
        f"Generate exactly {variations_count} distinct 'looks' sections in the JSON matching each candidate image variation. "
        f"Include the 3-tier comparison matrix and 5-stage UGC testing narrative. Return ONLY valid JSON."
    )

    try:
        parsed = await llm.structured_output(user_prompt, system=system_prompt)
        fb = _get_fallback_copy(product_data, variations_count=variations_count)
        
        # Ensure looks array matches variations_count
        looks = parsed.get("looks", [])
        if not isinstance(looks, list) or len(looks) < variations_count:
            looks = fb["looks"]
        
        # Enforce exact length and attach look_number
        for idx, l in enumerate(looks[:variations_count]):
            l["look_number"] = idx + 1
            if "inline_cta" not in l:
                l["inline_cta"] = ctx.get("look_cta", "Shop This Look on Amazon")
        parsed["looks"] = looks[:variations_count]

        # Ensure comparison_matrix is populated
        if not parsed.get("comparison_matrix") or not isinstance(parsed["comparison_matrix"], dict):
            parsed["comparison_matrix"] = fb["comparison_matrix"]

        # Ensure ugc_narrative is populated
        if not parsed.get("ugc_narrative") or not isinstance(parsed["ugc_narrative"], dict):
            parsed["ugc_narrative"] = fb["ugc_narrative"]

        # Ensure objections_faq has items
        faqs = parsed.get("objections_faq", [])
        if not isinstance(faqs, list) or len(faqs) < 3:
            parsed["objections_faq"] = fb["objections_faq"]

        # Ensure fabric_deep_dive is populated
        if not parsed.get("fabric_deep_dive") or not isinstance(parsed["fabric_deep_dive"], dict):
            parsed["fabric_deep_dive"] = fb["fabric_deep_dive"]

        # Ensure pros_cons is populated
        if not parsed.get("pros_cons") or not isinstance(parsed["pros_cons"], dict):
            parsed["pros_cons"] = fb["pros_cons"]

        # Ensure buyer_persona is populated
        if not parsed.get("buyer_persona") or not isinstance(parsed["buyer_persona"], dict):
            parsed["buyer_persona"] = fb["buyer_persona"]

        # Ensure quick_verdict is populated
        if not parsed.get("quick_verdict") or not isinstance(parsed["quick_verdict"], dict):
            parsed["quick_verdict"] = fb["quick_verdict"]

        # Ensure staged_ctas is populated
        if not parsed.get("staged_ctas") or not isinstance(parsed["staged_ctas"], dict):
            parsed["staged_ctas"] = fb["staged_ctas"]

        # Ensure reading_time, author & testing_badge
        parsed.setdefault("headline", fb["headline"])
        parsed.setdefault("subheadline", fb["subheadline"])
        parsed.setdefault("reading_time", "4 min read")
        parsed.setdefault("author_name", "Elena Vance")
        parsed.setdefault("author_title", "Fashion & Lifestyle Wear-Tester")
        parsed.setdefault("testing_badge", fb["testing_badge"])
        parsed.setdefault("trust_badges", ctx["trust_badges"])
        parsed.setdefault("guide_label", ctx["guide_label"])
        parsed.setdefault("curator_tag", ctx["curator_tag"])
        parsed.setdefault("specs_label", ctx["specs_label"])

        logger.info("Successfully generated UGC review copy for %s (Category: %s)", product_data.get("name"), product_data.get("category"))
        return parsed
    except Exception as e:
        logger.warning("LLM bridge copy generation failed (%s) — using deterministic fallback", e)
        return _get_fallback_copy(product_data, variations_count=variations_count)
