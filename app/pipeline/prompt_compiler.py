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


#: Listing rows that describe the object as a camera would see it. Ordered, because
#: a spec sheet reads better as colour → fabric → cut → fittings than alphabetically.
_VISUAL_SPEC_ORDER = (
    "colour", "color", "fabric", "material", "composition", "print", "pattern",
    "silhouette", "shape", "fit", "style", "cut", "neck", "collar", "sleeve",
    "length", "waist", "rise", "hem", "lining", "closure", "strap", "buckle",
    "toe", "heel", "sole", "finish", "trim", "embellish", "occasion", "season",
)

#: Rows that are facts about the *listing*, not the object in front of the lens.
#: "Care instructions: Machine Wash" cannot be photographed.
_SKIP_SPEC_KEYS = (
    "care instruction", "wash", "origin", "net quantity", "department", "warranty",
    "country", "batteries", "asin", "best sellers", "customer review", "manufacturer",
    "date first available", "item model number", "packer", "importer", "supplier",
    "generic name", "included components", "unit count", "is discontinued",
)

#: Measurements are kept apart: they tell the model how big the thing is, which is
#: a scale instruction rather than a look instruction.
_MEASUREMENT_KEYS = ("dimension", "weight", "capacity", "volume", "diameter")

#: A "spec" longer than this is a paragraph of marketing copy wearing a key.
_MAX_SPEC_VALUE_CHARS = 90
_MAX_SPECS_IN_PROMPT = 8


def _normalize_fact(text: str) -> str:
    """Lowercased, punctuation-light form used only to compare two facts."""
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def _spec_rank(key: str) -> int:
    """Position in `_VISUAL_SPEC_ORDER`, or the end of the queue."""
    low = key.lower()
    for index, token in enumerate(_VISUAL_SPEC_ORDER):
        if token in low:
            return index
    return len(_VISUAL_SPEC_ORDER)


def _visual_specs(specs: Any) -> list[tuple[str, str]]:
    """
    The rows of an Amazon spec table that describe how the product looks.

    Takes the `product_overview` / `technical_specs` dicts the Amazon engine
    scrapes and drops everything a photograph cannot show, so the prompt gets
    "Neck style: Scoop Neck" without "Net Quantity: 1 Count".
    """
    if not isinstance(specs, dict):
        return []
    rows: list[tuple[str, str]] = []
    for raw_key, raw_value in specs.items():
        key = str(raw_key).strip().rstrip(":")
        value = str(raw_value).strip().rstrip(".")
        if not key or not value or len(value) > _MAX_SPEC_VALUE_CHARS:
            continue
        low = key.lower()
        if any(skip in low for skip in _SKIP_SPEC_KEYS):
            continue
        if any(m in low for m in _MEASUREMENT_KEYS):
            continue
        if _spec_rank(key) == len(_VISUAL_SPEC_ORDER):
            continue
        rows.append((key, value))
    rows.sort(key=lambda row: _spec_rank(row[0]))
    return rows


def _measurements(specs: Any) -> list[str]:
    """
    Dimension and weight rows, phrased as `"31.8 x 25.9 x 1.4 cm"`.

    Amazon states the weight twice — `Package Dimensions` ends with "; 299 g" and
    `Item Weight` repeats it — so a row already contained in one that was kept is
    dropped instead of producing "… 299 g, 299 g".
    """
    if not isinstance(specs, dict):
        return []
    out: list[str] = []
    for raw_key, raw_value in specs.items():
        low = str(raw_key).lower()
        value = str(raw_value).strip().rstrip(".")
        if not value or len(value) > _MAX_SPEC_VALUE_CHARS:
            continue
        if not any(m in low for m in _MEASUREMENT_KEYS):
            continue
        if any(value in kept or kept in value for kept in out):
            continue
        out.append(value)
    return out[:2]


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


def compile_prompt(
    visual_dna: dict[str, Any],
    product: dict[str, Any],
    product_truth: dict[str, Any],
    scene: dict[str, Any],
    trend_label: str | None = None,
    commerce_dna: dict[str, Any] | None = None,
    concept: dict[str, Any] | None = None,
) -> CompileResult:
    """
    Assemble a sensory, conversion-focused generation prompt.
    Validates inputs and returns compiled prompt with warnings/errors.
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

    # ── Build Narrative Blocks ────────────────────

    # 1. SCENE INTENT & AUTHENTIC MOMENT
    motivation = scene["capture_motivation"].rstrip(".")
    action = scene.get("action", "").strip().rstrip(".")
    location = scene.get("location", "an authentic real-world setting").strip().rstrip(".")
    surface = scene.get("surface", "").strip().rstrip(".")
    state = scene.get("product_state", "").strip().rstrip(".")

    scene_intro = (
        f"A spontaneous, candid UGC smartphone photograph taken in {location}. "
        f"Moment: {motivation}."
    )
    if action:
        scene_intro += f" {action}."
    if state or surface:
        details = []
        if state:
            details.append(f"product is {state}")
        if surface:
            details.append(f"resting on {surface}")
        scene_intro += f" Captured with the {', '.join(details)}."
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
    mat_visibility = mat_dna.get("texture_visibility", "high")
    mat_imperfection = mat_dna.get("surface_imperfection", "moderate")

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
    clutter = env_dna.get("clutter") or klass.clutter
    bg_elements = scene.get("background_elements", [])
    
    env_block = f"Environment: {location} with {clutter} lived-in clutter and believable real-world asymmetry."
    if bg_elements:
        env_block += f" Background details include: {', '.join(bg_elements)}."
    env_block += " Avoid empty showroom staging or artificial sterile backgrounds."

    # 4. OPTICAL PHYSICS & CAMERA REALISM
    cam_dna = visual_dna.get("camera_dna", {})
    comp_dna = visual_dna.get("composition_dna", {})
    light_dna = visual_dna.get("lighting_dna", {})
    realism_dna = visual_dna.get("realism_markers", {})

    framing = scene.get("framing") or comp_dna.get("framing") or klass.framing
    centering = comp_dna.get("centering", "slightly off-center")
    crop = comp_dna.get("crop") or klass.crop
    camera_height = comp_dna.get("camera_height") or klass.camera_height
    camera_pos = scene.get("camera_position", "handheld at chest level")
    human = scene.get("human_presence", "none")

    light_source = light_dna.get("source", "natural daylight")
    contrast = light_dna.get("contrast", "natural")
    warmth = light_dna.get("warmth", "neutral")
    sharpness = cam_dna.get("sharpness", "natural smartphone sharpness")
    noise = cam_dna.get("noise", "subtle sensor grain")
    hdr = cam_dna.get("hdr", "restrained computational dynamic range")

    camera_block = (
        f"Camera & Composition: Handheld modern smartphone lens, {framing} framing with a {crop} crop, "
        f"positioned {camera_height} ({camera_pos}). Composition is naturally {centering} with organic edge overlap."
    )
    if human != "none":
        camera_block += f" Human presence is {human} with natural, unposed body posture and authentic skin texture."

    measured_facts = visual_dna.get("measured_facts") or {}
    palette = measured_facts.get("dominant_palette") or []
    palette_text = f" Grounded environmental tones: {', '.join(palette[:4])}." if palette else ""

    lighting_block = (
        f"Lighting: Authentic {light_source} lighting with {warmth} color balance and {contrast} contrast.{palette_text} "
        f"Realistic light bounce and natural soft shadows. Optical specs: {sharpness}, {noise}, {hdr}, "
        "natural focal falloff without artificial digital blur or fake studio rim lights."
    )

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
    )


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
