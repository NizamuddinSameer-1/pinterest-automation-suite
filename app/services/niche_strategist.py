"""
Niche Strategist & EPC Monetization Intelligence Engine.

Based on the Elite Affiliate Marketing Strategist framework:
- Analyzes product/campaign monetization opportunities
- Evaluates buyer intent, commercial value, commission rates, and aesthetic desire
- Scores products on an EPC (Earnings Per Click) rating matrix (Tier S / A / B / C)
- Provides actionable Pinterest pin angles, psychological triggers, and conversion roadmaps
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.pipeline.product_taxonomy import classify_product

logger = logging.getLogger("pre.niche_strategist")


@dataclass(frozen=True)
class NicheProfile:
    id: str
    name: str
    target_demographic: str
    pinterest_intent: str
    typical_aov: str
    avg_commission_rate: str
    impulse_score: int  # 1 to 10
    return_risk: str   # low | medium | high
    estimated_epc: str
    recommended_pin_angles: tuple[str, ...]
    psychological_buying_triggers: tuple[str, ...]


NICHE_EPC_MATRIX: dict[str, NicheProfile] = {
    "capsule_wardrobe": NicheProfile(
        id="capsule_wardrobe",
        name="Capsule Wardrobe & Elevated Streetwear Outerwear",
        target_demographic="Fashion-conscious buyers looking for effortless, high-end layering",
        pinterest_intent="Outfit formula discovery, seasonal lookbooks, viral try-on aesthetic",
        typical_aov="$50 – $130",
        avg_commission_rate="4.0% – 7.0%",
        impulse_score=9,
        return_risk="medium",
        estimated_epc="$0.45 – $1.15",
        recommended_pin_angles=(
            "Oversized silhouette mirror selfie with coffee",
            "3-way outfit transition flat-lay",
            "Street-style in-motion walking shot",
            "Close-up texture / hardware macro detail",
        ),
        psychological_buying_triggers=(
            "Fear of looking cheap or boxy (relieved by drape notes)",
            "Desire for multi-season versatility (styling formula)",
            "Impulse validation ('viral find under $100')",
        ),
    ),
    "aesthetic_kitchen": NicheProfile(
        id="aesthetic_kitchen",
        name="Aesthetic Barista Coffee & Functional Kitchenware",
        target_demographic="Home baristas, meal preppers, and interior aesthetic enthusiasts",
        pinterest_intent="Morning routine aesthetic, counter setup inspiration, gift guides",
        typical_aov="$40 – $180",
        avg_commission_rate="4.5% – 8.0%",
        impulse_score=8,
        return_risk="low",
        estimated_epc="$0.50 – $1.40",
        recommended_pin_angles=(
            "Morning sunlight counter pour shot",
            "Minimalist coffee corner overhead flat-lay",
            "Hands-on unboxing / mid-use action frame",
        ),
        psychological_buying_triggers=(
            "Aspiration for a daily ritual upgrade",
            "Countertop aesthetic integration",
            "Food-grade durability and effortless cleaning",
        ),
    ),
    "desk_setup_tech": NicheProfile(
        id="desk_setup_tech",
        name="Minimalist Desk Setup & Productivity Tech",
        target_demographic="Remote professionals, creators, and workspace modernizers",
        pinterest_intent="Desk tour inspiration, cable-free setups, ergonomic upgrade guides",
        typical_aov="$60 – $220",
        avg_commission_rate="3.0% – 6.0%",
        impulse_score=7,
        return_risk="low",
        estimated_epc="$0.60 – $1.50",
        recommended_pin_angles=(
            "Moody warm desk light overhead workspace view",
            "Macro port / mechanical texture detail",
            "Dual-monitor clean setup POV",
        ),
        psychological_buying_triggers=(
            "Productivity boost and focus mindset",
            "Universal device compatibility",
            "Clutter-free cable management",
        ),
    ),
    "clean_beauty_skincare": NicheProfile(
        id="clean_beauty_skincare",
        name="Clean Beauty, Glass Skin & Vanity Organization",
        target_demographic="Skincare-focused shoppers seeking glow routine essentials",
        pinterest_intent="Glass skin morning routine, ingredient pairing, vanity aesthetic",
        typical_aov="$25 – $65",
        avg_commission_rate="5.0% – 10.0%",
        impulse_score=10,
        return_risk="low",
        estimated_epc="$0.55 – $1.25",
        recommended_pin_angles=(
            "Golden hour bathroom counter droplet shot",
            "Texture swatch on skin close-up",
            "Clean vanity flat-lay with natural foliage",
        ),
        psychological_buying_triggers=(
            "Instant gratification texture proof",
            "Sensitive skin safety / clean ingredient reassurance",
            "Seamless routine layering without pilling",
        ),
    ),
    "cozy_home_decor": NicheProfile(
        id="cozy_home_decor",
        name="Cozy Living Sanctuary & Ambient Lighting",
        target_demographic="Homebody aesthetic lovers and apartment decorators",
        pinterest_intent="Cozy bedroom vibes, warm lighting corners, seasonal room refreshes",
        typical_aov="$35 – $110",
        avg_commission_rate="4.0% – 8.0%",
        impulse_score=9,
        return_risk="low",
        estimated_epc="$0.40 – $0.95",
        recommended_pin_angles=(
            "Nighttime warm lamp glow bedside view",
            "Linen throw texture draped on couch",
            "Diffuser mist in morning window light",
        ),
        psychological_buying_triggers=(
            "Comfort and emotional sanctuary",
            "Immediate room ambiance transformation",
            "Affordable luxury look for budget home spaces",
        ),
    ),
}


def score_product_opportunity(product_data: dict[str, Any]) -> dict[str, Any]:
    """
    Score a product for affiliate EPC monetization potential based on:
    Traffic Potential, Buyer Intent, Commercial Value, Price Point, and Taxonomy Fit.
    """
    classification = classify_product(product_data)
    klass_key = classification.key if classification else "generic"
    name = product_data.get("name", "")
    price_val = product_data.get("price")

    # Determine matched niche profile
    if klass_key in ("clothing", "footwear", "bags", "jewelry", "watches", "eyewear"):
        niche = NICHE_EPC_MATRIX["capsule_wardrobe"]
        intent_score = 9
        aesthetic_score = 10
    elif klass_key in ("kitchen", "tableware"):
        niche = NICHE_EPC_MATRIX["aesthetic_kitchen"]
        intent_score = 9
        aesthetic_score = 9
    elif klass_key in ("tech_gadgets", "audio", "stationery"):
        niche = NICHE_EPC_MATRIX["desk_setup_tech"]
        intent_score = 8
        aesthetic_score = 8
    elif klass_key in ("beauty", "skincare", "haircare", "bodycare", "fragrance"):
        niche = NICHE_EPC_MATRIX["clean_beauty_skincare"]
        intent_score = 10
        aesthetic_score = 10
    elif klass_key in ("home_decor", "bedding"):
        niche = NICHE_EPC_MATRIX["cozy_home_decor"]
        intent_score = 9
        aesthetic_score = 9
    else:
        niche = NICHE_EPC_MATRIX["capsule_wardrobe"]
        intent_score = 7
        aesthetic_score = 7

    # Evaluate Price Point & Margin
    price_num = 0.0
    if price_val:
        try:
            price_num = float(str(price_val).replace("$", "").replace(",", "").strip())
        except ValueError:
            price_num = 45.0
    else:
        price_num = 45.0

    # High sweet spot for impulse Amazon affiliate buying: $25 to $120
    if 25.0 <= price_num <= 120.0:
        commercial_value = 9
        buyer_friction = "Low (Prime 1-Click Impulse Range)"
    elif price_num < 25.0:
        commercial_value = 6
        buyer_friction = "Ultra-Low Friction (Smaller absolute commission per unit)"
    else:
        commercial_value = 8
        buyer_friction = "Moderate (Requires stronger objection handling & reviews)"

    # Compute Composite Opportunity Score (out of 10)
    traffic_potential = 9
    composite_score = round(
        (intent_score * 0.35) + (commercial_value * 0.25) + (aesthetic_score * 0.25) + (traffic_potential * 0.15),
        1,
    )

    if composite_score >= 8.8:
        epc_tier = "Tier S (Elite EPC — High Commercial Intent & Impulse Potential)"
    elif composite_score >= 7.8:
        epc_tier = "Tier A (High EPC — Strong Conversion & Aesthetic Fit)"
    elif composite_score >= 6.8:
        epc_tier = "Tier B (Solid EPC — Reliable Daily Volume)"
    else:
        epc_tier = "Tier C (Standard Informational Opportunity)"

    return {
        "product_name": name,
        "niche_id": niche.id,
        "niche_name": niche.name,
        "composite_opportunity_score": composite_score,
        "epc_tier": epc_tier,
        "traffic_potential_score": traffic_potential,
        "buyer_intent_score": intent_score,
        "commercial_value_score": commercial_value,
        "aesthetic_score": aesthetic_score,
        "buyer_friction": buyer_friction,
        "estimated_epc_range": niche.estimated_epc,
        "typical_commission_rate": niche.avg_commission_rate,
        "recommended_pin_angles": list(niche.recommended_pin_angles),
        "psychological_buying_triggers": list(niche.psychological_buying_triggers),
        "conversion_strategy_summary": (
            f"Target Pinterest visual searches for '{name}' using aspirational '{niche.recommended_pin_angles[0]}'. "
            f"Direct to the UGC Lookbook bridge page with above-the-fold Prime price validation to trigger a qualified Amazon click "
            f"within the first 20 seconds of session time."
        ),
    }
