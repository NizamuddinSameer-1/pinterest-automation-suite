"""
Commerce Modules Registry — Commercial Intent Micro-Triggers.

Second trigger library alongside `prompt_modules.py` (1000 realism modules).
These modules encode commerce-intent: product prominence, texture clarity,
signature-feature focus and desire proximity. They are injected before realism
modules by prompt_compiler when commerce_dna is present.
"""

from __future__ import annotations

COMMERCE_MODULES: dict[str, str] = {
    "PRODUCT_FRONT_FOCUS": "Make the hero product occupy 60-80% of frame so viewer instantly recognizes what is being sold.",
    "TEXTURE_VISIBLE_AT_FIRST_GLANCE": "Ensure the selling texture (leather grain, knit weave, gloss) is sharp at first glance, not hidden in shadow.",
    "SIGNATURE_FEATURE_PROMINENCE": "The differentiating feature (collar, zipper, print) must be centered and in focus, not cropped or blurred.",
    "HERO_PRODUCT_RATIO_80": "Hero product 80% frame, context 20% — context supports, never dominates.",
    "DESIRE_PROXIMITY": "Place product in context where viewer can imagine themselves wearing/using it (mirror, street, desk).",
    "CLICK_CURIOSITY_HOOK": "Create a visual curiosity gap — the image promises full detail is one click away.",
    "PREMIUM_SURFACE_DETAIL": "Highlight premium surface cues — stitching, hardware, grain — with tactile clarity.",
    "LIFESTYLE_CONTEXT_SUPPORT": "Lifestyle context must support the product, not compete: neutral background, shallow depth of field on context.",
    "MATERIAL_TACTILITY_CLOSEUP": "Close-up tactility: material should look touchable with micro-contrast and edge lighting.",
    "CONTEXT_PROPORTION_20": "Context occupies at most 20% of attention — blurred or secondary, never the subject.",
    "CENTERED_HERO_COMPOSITION": "Center the hero product with rule-of-thirds bias so the eye lands on the product first.",
    "SHOPPER_MIRROR_POV": "Shopper point-of-view framing (mirror check, lap, desk) to increase purchase imagination.",
    "SCROLL_STOP_CONTRAST": "High scroll-stop contrast — hero product pops from background via tone or color separation.",
    "CRAFTSMANSHIP_EVIDENCE": "Visible craftsmanship evidence: seams, zippers, buttons must be crisp and accurate.",
    "COLOR_ACCURACY_HERO": "Color-accurate hero rendering under neutral lighting — sell the exact color, not a stylized tint.",
    "SCALE_REFERENCE_HUMAN": "Human scale reference (hand, torso, face cropped) to communicate size instantly.",
    "WORN_TEXTURE_AUTHENTICITY": "Worn-in authenticity cues that increase desire — natural drape, flex creases, lived-in folds.",
    "DETAIL_MACRO_FOCUS": "Macro detail inset feel: one feature razor-sharp so viewer zooms to inspect.",
    "PRODUCT_CLARITY_SHARP": "Product clarity sharp from edge to edge — no blur, no crop on selling edges.",
    "COMMERCIAL_LIGHTING_CLEAN": "Clean commercial lighting — soft key light with gentle shadow so product reads instantly.",
    "ZIPPER_HARDWARE_FOCUS": "Zipper and hardware in tight focus — teeth, pull, and stitch line visible without glare.",
    "LEATHER_GRAIN_PROMINENCE": "Leather grain prominence with natural pebble, pore, and flex variation visible at first glance.",
    "SILHOUETTE_DESIRE_LINE": "Silhouette desire line — clean outline of shape that makes the product covetable at thumbnail size.",
    "ORIGINALITY_CONTEXT_ROLE": "Context role originality — setting explains use case (commute, café, studio) in one glance.",
}


def get_commerce_triggers(commerce_dna: dict, klass) -> list[str]:
    """Return commerce micro-triggers based on commerce_dna and product klass.

    Mirrors plan Task 3 Step 3: hero_prominence, must_show etc.
    Always returns strings that contain module key or leather when applicable
    so callers can trace which module fired.
    """
    triggers: list[str] = []

    if commerce_dna.get("hero_prominence") == "high":
        triggers.append(f"PRODUCT_FRONT_FOCUS: {COMMERCE_MODULES['PRODUCT_FRONT_FOCUS']}")
        # reinforce framing
        if "HERO_PRODUCT_RATIO_80" in COMMERCE_MODULES:
            triggers.append(f"HERO_PRODUCT_RATIO_80: {COMMERCE_MODULES['HERO_PRODUCT_RATIO_80']}")

    must_show_str = str(commerce_dna.get("must_show", [])).lower()

    if "leather" in must_show_str:
        triggers.append(f"LEATHER_GRAIN_PROMINENCE: {COMMERCE_MODULES['LEATHER_GRAIN_PROMINENCE']}")
        triggers.append(f"TEXTURE_VISIBLE_AT_FIRST_GLANCE: {COMMERCE_MODULES['TEXTURE_VISIBLE_AT_FIRST_GLANCE']}")

    if "zipper" in must_show_str:
        triggers.append(f"SIGNATURE_FEATURE_PROMINENCE: {COMMERCE_MODULES['SIGNATURE_FEATURE_PROMINENCE']}")
        triggers.append(f"ZIPPER_HARDWARE_FOCUS: {COMMERCE_MODULES['ZIPPER_HARDWARE_FOCUS']}")

    # texture-related generic
    if any(k in must_show_str for k in ("texture", "knit", "grain", "fabric")):
        triggers.append(f"TEXTURE_VISIBLE_AT_FIRST_GLANCE: {COMMERCE_MODULES['TEXTURE_VISIBLE_AT_FIRST_GLANCE']}")

    # klass-aware trigger (apparel etc.)
    klass_key = None
    if isinstance(klass, dict):
        klass_key = str(klass.get("key", "")).lower()
    else:
        try:
            klass_key = str(getattr(klass, "key", "")).lower() or str(klass).lower()
        except Exception:
            klass_key = str(klass).lower()

    if klass_key == "apparel":
        triggers.append(f"DESIRE_PROXIMITY: {COMMERCE_MODULES['DESIRE_PROXIMITY']}")

    # De-duplicate preserving order
    seen = set()
    deduped: list[str] = []
    for t in triggers:
        if t not in seen:
            seen.add(t)
            deduped.append(t)

    return deduped[:4]
