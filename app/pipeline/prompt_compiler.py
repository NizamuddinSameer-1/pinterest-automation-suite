"""
Stage 4 — Prompt Compiler.

Pure logic — NO LLM call.
Assembles the generation prompt from structured inputs into a cohesive,
photorealistic UGC narrative optimized for diffusion & Google Flow models.
Includes compile-time validation.

Replaces fragmented uppercase metadata headers with a natural sensory
photography brief that enforces concrete optical physics, tactile materials,
lived-in micro-imperfections, and strict product fidelity.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import settings
from app.pipeline.product_taxonomy import (
    avoid_text,
    classify_product,
    format_is_plausible,
    resolve_class,
    subject_line,
)
from app.pipeline.prompt_modules import get_relevant_module_items, get_relevant_modules
from app.pipeline.shot_archetypes import (
    ARCHETYPES,
    SHOT_ORDER,
    crop_phrase,
    human_for,
    niche_slots,
    shot_directive,
)

logger = logging.getLogger("pre.pipeline.prompt_compiler")

# Words to auto-strip from prompts to avoid diffusion over-polishing
BANNED_KEYWORDS = {
    "8k", "masterpiece", "ultra realistic", "ultra-realistic",
    "hyper realistic", "hyper-realistic", "cinematic", "hyperdetailed",
    "hyper detailed", "hyper-detailed", "award winning", "award-winning",
    "photorealistic masterpiece", "unreal engine",
}

# Longest first, preserving hyphenated compounds (e.g. anti-cinematic)
_BANNED_PATTERNS: list[tuple[str, re.Pattern[str]]] = sorted(
    (
        (
            kw,
            re.compile(rf"(?<![\w-]){re.escape(kw)}(?![\w-])", re.IGNORECASE),
        )
        for kw in BANNED_KEYWORDS
    ),
    key=lambda pair: -len(pair[0]),
)


# Internal enum tokens that must never reach the render prompt as-is.
# The Visual DNA analyst returns snake_case enums (`high_tactile`,
# `natural_fabric_grain`, `human_standing`); interpolating them raw produced
# text like "with high_tactile tactile surface texture and natural_fabric_grain
# natural manufacturing/wear imperfections", which the diffusion model reads as
# literal gibberish instead of an instruction.
_ENUM_PHRASES: dict[str, str] = {
    # material_dna — these land inside "with {x} tactile surface texture" and
    # "and {y} natural manufacturing/wear imperfections", so they must read as
    # degrees/qualifiers, not repeat the noun that already follows them.
    "high_tactile": "high",
    "natural_fabric_grain": "authentic",
    "medium": "moderate",
    # composition_dna
    "slightly_off_center": "slightly off-center",
    "off_center": "off-center",
    "rule_of_thirds": "on the rule-of-thirds line",
    "human_standing": "at human standing height",
    "eye_level": "at eye level",
    "pinterest_2_3": "in a 2:3 Pinterest crop",
    "standard": "natural",
    # lighting_dna / camera_dna
    "natural_smartphone": "natural smartphone",
    "subtle_natural_chroma": "subtle natural chroma noise",
    "warm_neutral": "warm neutral",
    "neutral_to_cool": "neutral to cool",
    # human_presence
    "partial_body": "partially in frame",
    "partial_hand_arm": "hands and forearm in frame",
    "hands_only": "hands only in frame",
    "full": "fully in frame",
    # generic
    "very_high": "very high",
    "very_low": "very low",
}


def _humanize(value: Any) -> Any:
    """Render an internal enum token as readable prompt prose.

    Leaves already-prose values untouched; only rewrites snake_case tokens.
    """
    if not isinstance(value, str):
        return value
    s = value.strip()
    if not s:
        return value
    if s in _ENUM_PHRASES:
        return _ENUM_PHRASES[s]
    if "_" in s:
        return s.replace("_", " ")
    return s


# Framing is a fixed photography vocabulary — macro | tight | medium | wide.
# It needs its own pass because `_humanize` maps the bare token "medium" to
# "moderate" for material_dna.texture_visibility, which turned every framing
# clause into "moderate framing". "medium framing" is the term of art.
_FRAMING_WORDS = {"macro", "tight", "medium", "wide"}


def _humanize_framing(value: Any) -> str:
    """Render a framing token without the generic enum map's `medium` rewrite."""
    s = str(value or "").strip().lower()
    if s in _FRAMING_WORDS:
        return s
    human = _humanize(value)
    return str(human).strip() or "medium"


def _scrub(value: Any, stripped: set[str]) -> Any:
    """
    Remove banned keywords from data-derived text only.
    """
    if isinstance(value, str):
        out = value
        for kw, pattern in _BANNED_PATTERNS:
            if pattern.search(out):
                out = pattern.sub("", out)
                stripped.add(kw)
        if out != value:
            out = re.sub(r"\s{2,}", " ", out)
            out = re.sub(r"\s+([,.;:])", r"\1", out)
            out = re.sub(r",+\s*([.;:])", r"\1", out)
            out = re.sub(r"(,\s*){2,}", ", ", out)
            out = re.sub(r"[,\s]+$", "", out)
            out = re.sub(r"^[,\s]+", "", out)
            # Removing a mid-phrase keyword can strand its article: "A cinematic,
            # 8k masterpiece of the dress" -> "A, of the dress". Drop the orphan
            # article + comma so the sentence stays readable.
            out = re.sub(r"\b([Aa]n?|[Tt]he)\s*,\s+", "", out)
            out = re.sub(r"^[,\s]+", "", out)
        return out
    if isinstance(value, list):
        cleaned = [_scrub(v, stripped) for v in value]
        return [v for v in cleaned if not (isinstance(v, str) and not v.strip())]
    if isinstance(value, dict):
        return {k: _scrub(v, stripped) for k, v in value.items()}
    return value


@dataclass
class CompileWarning:
    severity: str  # error, warning, info
    message: str


from app.pipeline.visual_specs import (
    extract_measurements as _measurements,
    extract_visual_specs as _visual_specs,
    normalize_fact as _normalize_fact,
)

_MAX_SPECS_IN_PROMPT = 8


def _spec_sheet_block(
    product_truth: dict[str, Any],
    product: dict[str, Any],
    already_said: str,
) -> str | None:
    """
    The verified-facts block: colour, fabric, cut and fittings as the listing states them.

    Everything here was read off the merchant's own page by the Amazon engine and
    stored on the Product Truth. Without this block the compiler forwarded only
    `must_preserve`, so a scraped "Neck style: Scoop Neck / Sleeve type:
    Sleeveless / 97% Polyester, 3% Elastane" reached the render as nothing at all
    and the model invented a neckline.

    `already_said` is the text of the preceding product block: a fact that has
    just been stated is not repeated here.
    """
    said = _normalize_fact(already_said)

    def is_new(text: str) -> bool:
        norm = _normalize_fact(text)
        return bool(norm) and norm not in said

    parts: list[str] = []

    colors = [str(c).strip() for c in (product.get("colors") or []) if str(c).strip()]
    colors = [c for c in colors if is_new(c)]
    if colors:
        parts.append(f"colour — {', '.join(colors[:3])}")

    specs = _visual_specs(product_truth.get("product_overview")) + _visual_specs(
        product_truth.get("technical_specs")
    )
    seen: set[str] = set()
    for key, value in specs:
        fact = f"{key}: {value}"
        norm = _normalize_fact(fact)
        if norm in seen or not is_new(fact):
            continue
        seen.add(norm)
        parts.append(f"{key.lower()} — {value}")
        if len(parts) >= _MAX_SPECS_IN_PROMPT:
            break

    block = ""
    if parts:
        block = (
            "Verified product specifications from the merchant listing "
            "(render these exactly, do not substitute): " + "; ".join(parts) + "."
        )

    sizes = _measurements(product_truth.get("technical_specs")) or _measurements(
        product_truth.get("product_overview")
    )
    if sizes:
        sentence = f" Real physical size for scale: {', '.join(sizes)}."
        block = (block + sentence) if block else sentence.strip()

    return block or None


@dataclass
class CompileResult:
    prompt: str
    warnings: list[CompileWarning] = field(default_factory=list)
    is_valid: bool = True
    module_keys: list[str] = field(default_factory=list)
    shot_archetype: str | None = None
    shot_label: str = ""
    aspect_ratio: str = ""


def compile_prompt(
    visual_dna: dict[str, Any],
    product: dict[str, Any],
    product_truth: dict[str, Any],
    scene: dict[str, Any],
    trend_label: str | None = None,
    commerce_dna: dict[str, Any] | None = None,
    concept: dict[str, Any] | None = None,
    shot_archetype: str | None = None,
) -> CompileResult:
    """
    Assemble a sensory, conversion-focused generation prompt.
    Validates inputs and returns compiled prompt with warnings/errors.

    `shot_archetype` selects multi-shot mode. When it is None the compiler behaves
    exactly as it always has (one prompt, six directed variation axes). When it is
    one of SHOT_ORDER the compiler emits that archetype's own camera, framing,
    human presence, lighting and crop, and replaces the six-axis FLOW VARIATION
    block with that archetype's Block C directive.

    Multi-shot mode exists because Flow's `count` parameter takes ONE prompt and
    returns N stochastic samples of it — four near-identical compositions, not four
    distinct photographs. Four distinct shots require four prompts and four
    submissions, which is what `compile_shot_set()` produces.
    """
    warnings: list[CompileWarning] = []
    stripped: set[str] = set()

    # Scrub data-derived inputs
    visual_dna = _scrub(visual_dna, stripped)
    product = _scrub(product, stripped)
    product_truth = _scrub(product_truth, stripped)
    scene = _scrub(scene, stripped)
    trend_label = _scrub(trend_label, stripped) if trend_label else None

    # ── Validation ────────────────────────────────
    if not scene.get("capture_motivation"):
        warnings.append(CompileWarning("error", "Missing capture_motivation in scene. Cannot compile."))
        return CompileResult(prompt="", warnings=warnings, is_valid=False)

    if not product_truth.get("must_preserve"):
        from app.pipeline.visual_specs import derive_must_preserve
        fallback = derive_must_preserve(
            materials=product.get("materials"),
            title=product.get("name") or "",
        )
        if fallback:
            product_truth["must_preserve"] = fallback
            warnings.append(CompileWarning("info", f"Auto-derived fallback must_preserve: {fallback}"))
        else:
            warnings.append(CompileWarning("error", "Missing must_preserve in Product Truth. Cannot compile."))
            return CompileResult(prompt="", warnings=warnings, is_valid=False)

    # ── Product class ─────────────────────────────
    class_key = scene.get("product_class")
    if class_key:
        klass = resolve_class(str(class_key))
    else:
        classification = classify_product(product)
        klass = classification.product_class
        warnings.append(CompileWarning(
            "info",
            f"Scene carries no product_class; classified as '{klass.key}' "
            f"({classification.confidence} confidence) at compile time."
        ))

    scene_format = str(scene.get("creative_format") or "")
    ok, why = format_is_plausible(scene_format, klass)
    if not ok:
        warnings.append(CompileWarning("warning", f"{why}."))

    if not trend_label:
        warnings.append(CompileWarning(
            "info",
            "No trend_label on the reference, so the prompt has no trend anchor."
        ))

    # ── Shot archetype (multi-shot mode) ──────────
    # One Flow submission takes ONE prompt and returns N stochastic samples of it,
    # so a genuinely four-shot set needs four compiles. Each archetype takes
    # ownership of the values that would otherwise contradict it: a flat lay cannot
    # be "handheld at chest level", and a macro cannot carry a 2:3 crop.
    arch = None
    arch_slots = None
    if shot_archetype:
        arch = ARCHETYPES.get(str(shot_archetype).strip().lower())
        if arch is None:
            warnings.append(CompileWarning(
                "error",
                f"Unknown shot archetype {shot_archetype!r}; expected one of "
                f"{', '.join(SHOT_ORDER)}. Cannot compile.",
            ))
            return CompileResult(prompt="", warnings=warnings, is_valid=False)

        arch_slots = niche_slots(klass.key)
        scene = dict(scene)  # never mutate the caller's scene
        # `framing` is read from the scene both by this compiler and by
        # prompt_modules (which gates the macro/closeup module set on it).
        scene["framing"] = arch.framing
        # `human_presence` is read from the scene by the camera block *and* by
        # prompt_modules, which is what decides whether hand modules are eligible.
        scene["human_presence"] = human_for(klass, arch.wants_human)
        # The scene's own location belongs to the "world" shot; the others take the
        # archetype's setting so two different places never appear in one prompt.
        if arch.key in ("flat_lay", "macro"):
            scene["location"] = "a clean, controlled setting"
        else:
            scene["location"] = arch_slots.setting
        if arch.key == "flat_lay":
            scene["surface"] = arch_slots.surface
        elif arch.key == "macro":
            # A 1:1 magnification frame is filled by the detail itself; naming a
            # surface here invites the model to render that material prominently.
            scene["surface"] = ""

    # ── Build Narrative Blocks ────────────────────

    # 1. SCENE INTENT & AUTHENTIC MOMENT
    motivation = scene["capture_motivation"].rstrip(".")
    action = scene.get("action", "").strip().rstrip(".")
    location = scene.get("location", "an authentic real-world setting").strip().rstrip(".")
    # Scene locations are often already prepositional phrases ("in a changing
    # room"), which rendered as "photograph taken in in a changing room".
    if location.lower().startswith("in "):
        location = location[3:]
    surface = scene.get("surface", "").strip().rstrip(".")
    state = scene.get("product_state", "").strip().rstrip(".")

    scene_intro = (
        f"A spontaneous, candid UGC smartphone photograph taken in {location}. "
        f"Moment: {motivation}."
    )
    if action:
        scene_intro += f" {action}."
    if state or surface:
        bits = []
        if state:
            bits.append(state)
        if surface:
            bits.append(f"resting on {surface}")
        scene_intro += f" In frame, the product is {', '.join(bits)}."
    if trend_label:
        scene_intro += f" Aesthetic context: subtle {trend_label} mood naturally integrated through surrounding props and styling."

    # 2. PRODUCT TRUTH & TACTILE MATERIALITY
    subject_desc = subject_line(product, klass).rstrip(".")
    scale = klass.scale_note.rstrip(".") if klass.scale_note else ""
    preserve = ", ".join(product_truth.get("must_preserve", []))
    not_invent = ", ".join(product_truth.get("must_not_invent", []))
    may_vary = ", ".join(product_truth.get("allowed_scene_variations", []))
    prod_materials = product.get("materials", [])

    mat_dna = visual_dna.get("material_dna", {})
    mat_visibility = _humanize(mat_dna.get("texture_visibility") or "high")
    mat_imperfection = _humanize(mat_dna.get("surface_imperfection") or "moderate")

    product_block = f"Featuring {subject_desc}"
    if scale:
        product_block += f" (scale: {scale})"
    product_block += f". Strictly accurate product details: {preserve}."

    if prod_materials:
        product_block += f" Realistic physical materials ({', '.join(prod_materials)}) with {mat_visibility} tactile surface texture and {mat_imperfection} natural manufacturing/wear imperfections."
    else:
        product_block += f" Realistic tactile surface texture with {mat_imperfection} natural micro-imperfections."

    if not_invent:
        product_block += f" (Do not invent: {not_invent})."
    if may_vary:
        product_block += f" (Allowed variations: {may_vary})."

    # 2b. VERIFIED SPEC SHEET — the merchant's own stated facts (Amazon ingestion
    #     stores them on the Product Truth; hand-made rows simply have none).
    spec_sheet = _spec_sheet_block(product_truth, product, product_block)
    if spec_sheet is None:
        warnings.append(CompileWarning(
            "info",
            "Product Truth carries no listing specifications (colour, fabric, cut), so "
            "the prompt states only must_preserve. Re-ingest the product from Amazon, or "
            "fill in its colours and materials, for a fact-anchored brief."
        ))

    # 3. ENVIRONMENT & REAL-WORLD CLUTTER
    env_dna = visual_dna.get("environment_dna", {})
    clutter = _humanize(env_dna.get("clutter") or klass.clutter)
    # A hero flat lay and a macro detail shot are deliberately clean — the clutter
    # brief belongs to the lifestyle and environment shots, not to these two.
    if arch is not None and arch.key in ("flat_lay", "macro"):
        clutter = "minimal"
    bg_elements = scene.get("background_elements", [])
    
    env_block = f"Environment: {location} with {clutter} lived-in clutter and believable real-world asymmetry."
    if bg_elements:
        env_block += f" Background details include: {', '.join(bg_elements)}."
    env_block += " Authentic casual domestic reality with natural room textures and organic lived-in surroundings."

    # 4. OPTICAL PHYSICS & CAMERA REALISM
    cam_dna = visual_dna.get("camera_dna", {})
    comp_dna = visual_dna.get("composition_dna", {})
    light_dna = visual_dna.get("lighting_dna", {})
    realism_dna = visual_dna.get("realism_markers", {})

    # The archetype owns the camera entirely. A flat lay cannot be "handheld at
    # chest level" and a macro cannot carry a 2:3 crop, so in multi-shot mode these
    # four values come from the archetype rather than from the DNA or the class.
    if arch is not None:
        framing = arch.framing
        camera_height = arch.camera_height
        camera_pos = arch.camera_pos
        crop = crop_phrase(arch.aspect_ratio)
    else:
        framing = _humanize_framing(
            scene.get("framing") or comp_dna.get("framing") or klass.framing
        )
        crop = _humanize(comp_dna.get("crop") or klass.crop)
        camera_height = _humanize(comp_dna.get("camera_height") or klass.camera_height)
        camera_pos = _humanize(scene.get("camera_position") or "handheld at chest level")

    centering = _humanize(comp_dna.get("centering") or "slightly off-center")
    human = _humanize(scene.get("human_presence") or "none")

    # The DNA analyst does not always honour the declared key names — 45% of
    # stored DNA carries lighting_dna.{type,quality,color_cast} and
    # camera_dna.{sensor_noise,dynamic_range} instead of {source,contrast,warmth}
    # and {noise,hdr}. Reading only the declared spelling silently dropped the
    # whole reference-specific lighting/camera brief and replaced it with the
    # hardcoded defaults below, which is why unrelated references produced
    # near-identical prompts. Accept both spellings.
    light_source = _humanize(light_dna.get("source") or light_dna.get("type") or "natural daylight")
    contrast = _humanize(light_dna.get("contrast") or light_dna.get("quality") or "natural")
    warmth = _humanize(light_dna.get("warmth") or light_dna.get("color_cast") or "neutral")
    sharpness = _humanize(cam_dna.get("sharpness") or "natural smartphone")
    noise = _humanize(cam_dna.get("noise") or cam_dna.get("sensor_noise") or "subtle sensor grain")
    hdr = _humanize(cam_dna.get("hdr") or cam_dna.get("dynamic_range") or "restrained computational dynamic range")
    device = str(cam_dna.get("device_family") or "").strip()
    focal = str(cam_dna.get("focal_length") or "").strip()

    camera_block = (
        f"Camera & Composition: Handheld modern smartphone lens, {framing} framing with a {crop} crop, "
        f"positioned {camera_height} ({camera_pos}). Composition is naturally {centering} with organic edge overlap."
    )
    if human != "none":
        camera_block += f" Human presence is {human} with natural, unposed body posture and authentic skin texture."

    measured_facts = visual_dna.get("measured_facts") or {}
    palette = measured_facts.get("dominant_palette") or []
    palette_text = f" Grounded environmental tones: {', '.join(palette[:4])}." if palette else ""

    optics = [x for x in (f"{sharpness} sharpness", noise, f"{hdr} dynamic range") if x]
    # Each archetype needs its own light: a raking 45° side light for a macro and a
    # soft overhead key for a flat lay are not the same photograph. Warmth, contrast
    # and palette stay shared so the set still reads as one shoot — only the
    # direction and quality of the light change from shot to shot.
    if arch is not None:
        light_clause = (
            f"{arch.lighting}, holding {warmth} color balance and {contrast} contrast"
        )
    else:
        light_clause = (
            f"Authentic {light_source} lighting with {warmth} color balance "
            f"and {contrast} contrast"
        )
    lighting_block = (
        f"Lighting: {light_clause}.{palette_text} "
        f"Realistic light bounce and natural soft shadows. Optical specs: {', '.join(optics)}, "
        "natural focal falloff with organic lens depth and authentic ambient falloff."
    )

    # 4b. FLOW VARIATION — class-specific direction from the Scene Director
    # (scene_variation_matrix, six seeded axes). Only present on scenes directed
    # after the matrix landed; older scenes skip this block with no behavior change.
    #
    # In multi-shot mode this block is REPLACED by the archetype's Block C, not
    # appended to it. Keeping both would make them fight: the six axes name one
    # camera angle and one lighting setup, while the archetype deliberately
    # overrides both.
    var_keys = ("camera_angle", "lighting_setup", "color_grading",
                "scene_environment", "style_aesthetic", "creative_context")
    var_lines = [f"- {k}: {scene[k]}" for k in var_keys if scene.get(k)]

    shot_block = None
    if arch is not None:
        shot_block = shot_directive(
            arch.key,
            klass,
            product,
            locked_world={
                "colour grading": str(scene.get("color_grading") or "").strip(),
                "visual aesthetic": str(scene.get("style_aesthetic") or "").strip(),
            },
        )
        # The aspect ratio is a Flow API parameter, but restating it keeps the
        # prompt and the request in agreement for anyone reading the job package.
        shot_block += f"\nFRAME: a single image at {arch.aspect_ratio} aspect ratio."

    # 5. ASSEMBLE SECTIONS
    sections = [
        scene_intro,
        product_block,
    ]
    if spec_sheet:
        sections.append(spec_sheet)
    sections += [
        env_block,
        camera_block,
        lighting_block,
    ]
    if shot_block:
        sections.append(shot_block)
    elif var_lines:
        sections.append(
            "FLOW VARIATION — honour all six directed axes in the composition:\n"
            + "\n".join(var_lines)
        )

    if realism_dna.get("anti_studio") or realism_dna.get("anti_cinematic"):
        sections.append("Style: Authentic everyday lifestyle photograph, un-staged UGC, anti-studio, anti-cinematic.")

    # ── Commerce Intent & Triggers — layer 1 (commercial reason to exist)
    if commerce_dna:
        sections.append(f"COMMERCE INTENT: Hero {commerce_dna.get('hero_product')} prominence {commerce_dna.get('hero_prominence')} — must show {', '.join(commerce_dna.get('must_show',[]))}")
        try:
            from app.pipeline.commerce_modules import get_commerce_triggers

            commerce_triggers = get_commerce_triggers(commerce_dna, klass)
            if commerce_triggers:
                sections.append("COMMERCE TRIGGERS:\n- " + "\n- ".join(commerce_triggers))
        except Exception as e:
            logger.warning("Commerce module injection skipped: %s", e)

    # ── Dynamic Realism Modules — inject viral-pin micro-triggers
    selected_module_keys: list[str] = []
    try:
        module_items = get_relevant_module_items(scene, klass, visual_dna)
        selected_module_keys = [k for k, _ in module_items]
        realism_modules = [text for _, text in module_items]
        if realism_modules:
            sections.append(
                "REALISM MICRO-TRIGGERS — concrete physical details to enforce authenticity:\n"
                + "\n".join(f"- {m}" for m in realism_modules)
            )
    except Exception as e:
        logger.warning("Module injection skipped: %s", e)

    # Negative constraints (appended strictly per product class)
    sections.append(avoid_text(klass))

    if klass.notes:
        sections.append("RULES:\n" + "\n".join(f"- {n}" for n in klass.notes))

    prompt = "\n\n".join(sections)

    if stripped:
        warnings.append(CompileWarning(
            "warning",
            f"Auto-stripped banned keywords from the inputs: {', '.join(sorted(stripped))}"
        ))

    return CompileResult(
        prompt=prompt.strip(),
        warnings=warnings,
        is_valid=True,
        module_keys=selected_module_keys,
        shot_archetype=arch.key if arch else None,
        shot_label=arch.label if arch else "",
        aspect_ratio=arch.aspect_ratio if arch else "",
    )


def compile_shot_set(
    visual_dna: dict[str, Any],
    product: dict[str, Any],
    product_truth: dict[str, Any],
    scene: dict[str, Any],
    trend_label: str | None = None,
    commerce_dna: dict[str, Any] | None = None,
    concept: dict[str, Any] | None = None,
    archetypes: tuple[str, ...] = SHOT_ORDER,
) -> list[CompileResult]:
    """
    Compile the full multi-shot set — one prompt per archetype, in submission order.

    Each result is an independent prompt meant to be submitted to Flow on its own
    with `count=1`. The product passport and the locked world are byte-identical
    across the set (they come from the same inputs and the same scene), while the
    camera, framing, lighting, crop and Block C directive differ per shot.

    The inputs are never mutated: `compile_prompt` copies the scene before applying
    archetype overrides, so four compiles from one scene cannot contaminate each
    other.
    """
    results: list[CompileResult] = []
    for key in archetypes:
        results.append(
            compile_prompt(
                visual_dna=visual_dna,
                product=product,
                product_truth=product_truth,
                scene=scene,
                trend_label=trend_label,
                commerce_dna=commerce_dna,
                concept=concept,
                shot_archetype=key,
            )
        )
    return results


def create_job_package(
    job_id: str,
    prompt_text: str,
    visual_dna: dict[str, Any],
    product_truth: dict[str, Any],
    scene: dict[str, Any],
    reference_image_path: str,
    product_image_path: str | None = None,
) -> Path:
    """
    Create the job package directory with all files needed for Google Flow.
    """
    job_dir = settings.jobs_path / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    (job_dir / "PROMPT.txt").write_text(prompt_text, encoding="utf-8")
    (job_dir / "VISUAL_DNA.json").write_text(
        json.dumps(visual_dna, indent=2), encoding="utf-8"
    )
    (job_dir / "PRODUCT_TRUTH.json").write_text(
        json.dumps(product_truth, indent=2), encoding="utf-8"
    )
    (job_dir / "SCENE.json").write_text(
        json.dumps(scene, indent=2), encoding="utf-8"
    )

    ref_path = Path(reference_image_path)
    if ref_path.exists():
        shutil.copy2(ref_path, job_dir / f"REFERENCE_STYLE{ref_path.suffix}")

    if product_image_path:
        prod_path = Path(product_image_path)
        if prod_path.exists():
            shutil.copy2(prod_path, job_dir / f"PRODUCT_REFERENCE{prod_path.suffix}")

    logger.info("Created job package at %s", job_dir)
    return job_dir
