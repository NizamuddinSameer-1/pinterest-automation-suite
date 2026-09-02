"""
Offline check that scenes and prompts are built from the product's CLASS.

The bug this guards against was never a hardcoded "assume apparel" line. It was
emergent: the Scene Director offered one fixed menu of ten creative formats, six
of them apparel or retail idioms, and four of its five `capture_motivation`
examples were clothing; the compiler's fallbacks were `Crop: natural`, `Camera
height: human standing` and `Clutter: moderate`; and one frozen AVOID sentence
told a toy to avoid `plastic textures` and a serum bottle to avoid `sterile
backgrounds` and `perfect symmetry` — the exact look those products have in real
photographs. Nothing was wrong with any single line, so nothing failed; every
product just drifted toward the same bedroom-mirror photograph.

Asserts five things:

  1. the taxonomy itself is internally consistent (every class's formats exist,
     no class can lift an unliftable negative, no illegal literals);
  2. six real products — a toy, jeans, press-on nails, a body oil, a laptop stand
     and a costume — each classify correctly;
  3. the Scene Director's brief offers ONLY that class's formats, and its
     validator rejects an apparel-shaped scene for a non-apparel product;
  4. the compiled prompt takes framing, crop, camera height, clutter, subject
     wording and AVOID clauses from the class, with no apparel default leaking in;
  5. the two stages cannot disagree — the compiler follows the class recorded on
     the scene, not its own re-classification of the product.

Runs with no network, no LLM and no database: the taxonomy is pure data, the
compiler is pure logic, and the two Scene Director helpers under test are lifted
out of their module by AST so that importing `app.providers.llm` is not required.
"""
import __future__
import ast
import json
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# The VM has no network, so pydantic-settings cannot be installed. Stub app.config.
pkg = types.ModuleType("app"); pkg.__path__ = [str(ROOT / "app")]
sys.modules.setdefault("app", pkg)
cfg = types.ModuleType("app.config")
class S:
    jobs_path = Path(tempfile.gettempdir()) / "pre_verify_jobs"
    storage_path = Path(tempfile.gettempdir()) / "pre_verify_store"
cfg.settings = S()
sys.modules["app.config"] = cfg

from app.pipeline.product_taxonomy import (
    BASE_AVOID,
    CLASSES,
    CREATIVE_FORMATS,
    UNLIFTABLE_AVOID,
    Classification,
    avoid_text,
    classify_product,
    director_brief,
    format_is_plausible,
    resolve_class,
    subject_line,
)
from app.pipeline.prompt_compiler import compile_prompt

fails: list[str] = []

# ── lift the two Scene Director helpers ───────────
# Importing scene_director pulls in app.providers.llm -> httpx, which is not
# installed here. The validator and the brief builder are pure functions, so they
# are lifted out of the source instead. If either is renamed this fails loudly,
# which is the point: they are the two places where the class becomes binding.
sd_src = (ROOT / "app" / "pipeline" / "scene_director.py").read_text(encoding="utf-8")
sd_ns = {
    "json": json, "Any": object, "Classification": Classification,
    "director_brief": director_brief, "format_is_plausible": format_is_plausible,
}
_wanted = {"_scene_problems", "_build_user_prompt"}
_picked = [
    n for n in ast.parse(sd_src).body
    if isinstance(n, ast.FunctionDef) and n.name in _wanted
]
if {n.name for n in _picked} != _wanted:
    fails.append(f"scene_director is missing {sorted(_wanted - {n.name for n in _picked})}")
else:
    exec(
        compile(
            ast.Module(body=_picked, type_ignores=[]), "scene_director", "exec",
            __future__.annotations.compiler_flag,  # so `str | None` parses on 3.10
        ),
        sd_ns,
    )
_scene_problems = sd_ns.get("_scene_problems")
_build_user_prompt = sd_ns.get("_build_user_prompt")

# ── 1. taxonomy invariants ────────────────────────
LEGAL_PRESENCE = {"full", "partial_hand_arm", "partial_body", "none"}
LEGAL_FRAMING = {"macro", "tight", "medium", "wide"}

for key, klass in CLASSES.items():
    if klass.key != key:
        fails.append(f"class {key!r} carries mismatched key {klass.key!r}")
    unknown = [f for f in klass.formats if f not in CREATIVE_FORMATS]
    if unknown:
        fails.append(f"class {key}: formats not in CREATIVE_FORMATS: {unknown}")
    if not klass.formats:
        fails.append(f"class {key}: no creative formats, so the director has no menu")
    bad_presence = [h for h in klass.human_presence if h not in LEGAL_PRESENCE]
    if bad_presence:
        fails.append(f"class {key}: illegal human_presence {bad_presence}")
    if klass.framing not in LEGAL_FRAMING:
        fails.append(f"class {key}: framing {klass.framing!r} is not one of {sorted(LEGAL_FRAMING)}")
    if not klass.motivations:
        fails.append(f"class {key}: no capture_motivation examples, the weakest field in the schema")
    # A class may lift a negative that does not apply to it; these four are never
    # negotiable, because an image that fails them is broken rather than stylised.
    clauses = klass.avoid_clauses()
    missing = [c for c in UNLIFTABLE_AVOID if c not in clauses]
    if missing:
        fails.append(f"class {key}: lifted unliftable AVOID clauses {missing}")
    lifted_unknown = [c for c in klass.avoid_lift if c not in BASE_AVOID]
    if lifted_unknown:
        fails.append(f"class {key}: avoid_lift names clauses that are not in BASE_AVOID: {lifted_unknown}")
    if any(k != k.lower() for k in klass.keywords):
        fails.append(f"class {key}: keywords must be lowercase (matching lowercases its input)")

if resolve_class("no_such_class").key != "generic":
    fails.append("resolve_class must fall back to generic, not raise")
if resolve_class(None).key != "generic":
    fails.append("resolve_class(None) must fall back to generic")

# ── 2. six real products classify correctly ───────
# Every one of these is a product an affiliate marketer would actually pin, and
# every one of them used to compile into the same standing-height room shot.
FIXTURES = [
    ("toys", {"name": "Montessori Wooden Stacking Toy", "category": "kids",
              "materials": ["beech wood"], "key_attributes": ["five rings", "natural finish"]}),
    ("apparel", {"name": "High-Waisted Straight Leg Jeans", "category": "fashion",
                 "materials": ["denim"], "key_attributes": ["five pockets"]}),
    ("nail_art", {"name": "Press-On Nails in Chrome Cherry", "category": "beauty",
                  "key_attributes": ["24 nails", "almond shape"]}),
    ("skincare", {"name": "OSEA Undaria Algae Body Oil", "category": "beauty",
                  "key_attributes": ["amber glass bottle", "pump top"]}),
    ("tech", {"name": "Aluminium Laptop Stand", "category": "electronics",
              "materials": ["aluminium"], "key_attributes": ["adjustable hinge"]}),
    ("costume", {"name": "Two-Piece Ruffled French Maid Halloween Costume Set",
                 "category": "costumes", "key_attributes": ["ruffled apron"]}),
]

classified: dict[str, Classification] = {}
for expected, product in FIXTURES:
    c = classify_product(product)
    classified[expected] = c
    if c.key != expected:
        fails.append(
            f"{product['name']!r} classified as {c.key!r}, expected {expected!r} ({c.describe()})"
        )
    if expected != "generic" and c.confidence == "low":
        fails.append(f"{product['name']!r} classified {c.key} with low confidence: {c.describe()}")

# An unlabelled product must land in generic — never in apparel, which is what a
# "first plausible format wins" menu did.
vague = classify_product({"name": "Item 4471", "category": ""})
if vague.key != "generic":
    fails.append(f"an unlabelled product landed in {vague.key!r}; it must be generic")

# ── 3. the director's brief and validator are class-bound ──
def native_scene(klass) -> dict:
    """The scene a compliant director would return for this class."""
    return {
        "creative_format": klass.formats[0],
        "capture_motivation": klass.motivations[0],
        "location": klass.locations[0] if klass.locations else "a small apartment",
        "action": "the moment just after it was picked up",
        "camera_position": "handheld, one arm's length away",
        "framing": klass.framing,
        "product_state": klass.product_states[0] if klass.product_states else "in use",
        "surface": klass.surfaces[0] if klass.surfaces else "a wooden table",
        "human_presence": klass.human_presence[0],
        "background_elements": ["a half-drunk mug", "a folded towel"],
        "staging_level": "minimal",
        "product_class": klass.key,
    }

for expected, product in FIXTURES:
    c = classified[expected]
    klass = c.product_class
    brief = director_brief(klass, c)
    if f"PRODUCT CLASS: {klass.key}" not in brief:
        fails.append(f"{klass.key}: brief does not name the class")
    for fmt in klass.formats:
        if f"  {fmt} — " not in brief:
            fails.append(f"{klass.key}: brief omits its own format {fmt!r}")
    for fmt in CREATIVE_FORMATS:
        if fmt not in klass.formats and f"  {fmt} — " in brief:
            fails.append(f"{klass.key}: brief offers foreign format {fmt!r}")
    for needed in (klass.framing, klass.camera_height, klass.motivations[0]):
        if needed not in brief:
            fails.append(f"{klass.key}: brief omits {needed!r}")

    problems = _scene_problems(native_scene(klass), c)
    if problems:
        fails.append(f"{klass.key}: a class-native scene was rejected: {problems}")

    # The apparel reflex, stated explicitly. For any class that cannot support it,
    # the director must reject it rather than pass it downstream.
    apparel_shaped = {"creative_format": "mirror_pov", "human_presence": "full",
                      "capture_motivation": "She checked the fit in the mirror."}
    rejected = _scene_problems(apparel_shaped, c)
    if "mirror_pov" not in klass.formats and not rejected:
        fails.append(f"{klass.key}: accepted a mirror_pov scene it cannot support")
    if not _scene_problems(dict(native_scene(klass), capture_motivation=""), c):
        fails.append(f"{klass.key}: accepted a scene with no capture_motivation")

# ── 4. the compiled prompt carries no apparel default ──
# Deliberately silent on composition and environment: this is the case where the
# compiler used to substitute `Crop: natural`, `Camera height: human standing` and
# `Clutter: moderate` for every product on earth.
QUIET_DNA = {
    "camera_dna": {"smartphone_behavior": True, "sharpness": "moderate",
                   "noise": "subtle", "hdr": "restrained"},
    "composition_dna": {"centering": "slightly off-center"},
    "lighting_dna": {"source": "window daylight", "contrast": "low", "warmth": "warm"},
    "material_dna": {"texture_visibility": "high", "surface_imperfection": "moderate"},
    "environment_dna": {"real_world_context": True, "background_activity": "low"},
    "realism_markers": {"imperfection_level": "moderate", "anti_studio": True,
                        "anti_cinematic": True},
}
TRUTH = {
    "must_preserve": ["shape", "colour"],
    "must_not_invent": ["logos"],
    "allowed_scene_variations": ["lighting", "background props"],
}

for expected, product in FIXTURES:
    klass = classified[expected].product_class
    scene = native_scene(klass)
    r = compile_prompt(QUIET_DNA, product, TRUTH, scene, trend_label="early autumn")
    if not r.is_valid:
        fails.append(f"{klass.key}: valid inputs reported invalid: {[w.message for w in r.warnings]}")
        continue
    p = r.prompt

    if f"Camera height: {klass.camera_height}" not in p:
        fails.append(f"{klass.key}: camera height is not the class's {klass.camera_height!r}")
    if f"Crop: {klass.crop}" not in p:
        fails.append(f"{klass.key}: crop is not the class's {klass.crop!r}")
    if f"Clutter: {klass.clutter}" not in p:
        fails.append(f"{klass.key}: clutter is not the class's {klass.clutter!r}")
    if f"Framing: {klass.framing}" not in p:
        fails.append(f"{klass.key}: framing is not the scene's {klass.framing!r}")
    # The specific default that used to be applied to everything. Costume and
    # apparel legitimately want it; a manicure, a bottle and a laptop stand do not.
    if "human standing" not in klass.camera_height and "human standing" in p:
        fails.append(f"{klass.key}: the apparel camera height leaked in")

    # SUBJECT used to be f"{name} — a {category}", i.e. "…Costume Set — a costumes."
    if subject_line(product, klass) not in p:
        fails.append(f"{klass.key}: SUBJECT is not the class's subject line")
    if f"— a {product.get('category')}." in p:
        fails.append(f"{klass.key}: SUBJECT still pastes the raw category ({product.get('category')!r})")

    # AVOID is per-class now. A toy really is made of plastic; a serum bottle
    # really is symmetrical against a clean surface.
    if avoid_text(klass) not in p:
        fails.append(f"{klass.key}: AVOID block is not the class's")
    for lifted in klass.avoid_lift:
        if lifted in UNLIFTABLE_AVOID:
            continue
        if lifted in p:
            fails.append(f"{klass.key}: AVOID still bans {lifted!r}, which this class lifts")
    for never in UNLIFTABLE_AVOID:
        if never not in p:
            fails.append(f"{klass.key}: AVOID dropped the unliftable {never!r}")

    # Fields the director now emits that the compiler used to ignore entirely.
    if f"Product state: {scene['product_state']}" not in p:
        fails.append(f"{klass.key}: product_state never reached the prompt")
    if scene["surface"] not in p:
        fails.append(f"{klass.key}: surface never reached the prompt")
    if "FREE TO VARY: lighting, background props." not in p:
        fails.append(f"{klass.key}: allowed_scene_variations still never reaches the prompt")
    if "early autumn" not in p:
        fails.append(f"{klass.key}: trend anchor missing")
    if klass.scale_note and klass.scale_note not in p:
        fails.append(f"{klass.key}: scale note missing, so the model has no sense of size")

# Two products from different classes must not compile to the same instructions.
nails_p = compile_prompt(QUIET_DNA, FIXTURES[2][1], TRUTH,
                         native_scene(classified["nail_art"].product_class)).prompt
jeans_p = compile_prompt(QUIET_DNA, FIXTURES[1][1], TRUTH,
                         native_scene(classified["apparel"].product_class)).prompt
if nails_p == jeans_p:
    fails.append("a manicure and a pair of jeans compiled to an identical prompt")
if "plastic textures" in compile_prompt(
    QUIET_DNA, FIXTURES[0][1], TRUTH, native_scene(classified["toys"].product_class)
).prompt:
    fails.append("a wooden/plastic toy is still told to avoid plastic textures")

# ── 5. the two stages cannot disagree ─────────────
# The director records the class it directed for. If the compiler re-derived the
# class from the product it could reach a different answer and compile macro
# instructions for a room shot, or vice versa.
jeans = FIXTURES[1][1]
nail_class = classified["nail_art"].product_class
crossed = compile_prompt(QUIET_DNA, jeans, TRUTH, native_scene(nail_class))
if f"Camera height: {nail_class.camera_height}" not in crossed.prompt:
    fails.append("the compiler ignored scene['product_class'] and re-classified the product")
if avoid_text(nail_class) not in crossed.prompt:
    fails.append("the compiler used the product's AVOID block, not the directed class's")

# A scene with no product_class (a hand-written one, or an older row) must still
# compile — classified at compile time, and said out loud as an info warning.
legacy = {k: v for k, v in native_scene(nail_class).items() if k != "product_class"}
r = compile_prompt(QUIET_DNA, FIXTURES[2][1], TRUTH, legacy)
if not r.is_valid:
    fails.append("a scene without product_class should still compile")
if not any("no product_class" in w.message for w in r.warnings):
    fails.append("compiling without product_class should say so")

# Implausible input is a WARNING at compile time, never a hard failure: the
# director already refuses these, and a compiler that raised here would turn a
# stylistic mismatch into a dead job.
odd = dict(native_scene(nail_class), creative_format="product_rack", human_presence="partial")
r = compile_prompt(QUIET_DNA, FIXTURES[2][1], TRUTH, odd)
if not r.is_valid or not r.prompt:
    fails.append("an implausible creative_format must warn, not fail the compile")
if not any(w.severity == "warning" and "product_rack" in w.message for w in r.warnings):
    fails.append("an implausible creative_format produced no warning")

ok, _ = format_is_plausible("wear_test", classified["apparel"].product_class)
bad, why = format_is_plausible("product_rack", nail_class)
if not ok or bad or "not believable" not in why:
    fails.append(f"format_is_plausible is wrong: apparel/wear_test={ok}, nails/rack={bad} ({why})")

# ── 6. Stage 1's reading of the reference is used ──
# `subject.primary_category` and `subject.objects` were computed by the reference
# analyst, written to reference_analyses.analysis_json, and read by nothing.
ANALYSIS = {
    "subject": {"primary_category": "kids", "secondary_category": "wooden toys",
                "objects": ["wooden stacking rings", "a play mat"],
                "product_visibility": "clear", "human_presence": "partial_hand_arm"},
    "scene": {"type": "closeup_ugc", "location": {"value": "a living room floor"},
              "context": "afternoon play", "capture_motivation": "showing a gift that landed well"},
    "psychology": {"why_it_works": "it looks like a real afternoon, not a catalogue"},
    "camera": {"device": "phone"},
}
toy_class = classified["toys"].product_class
brief = _build_user_prompt(
    QUIET_DNA, FIXTURES[0][1], TRUTH, classified["toys"], ANALYSIS, "back to school"
)
if "REFERENCE READING" not in brief:
    fails.append("the Stage 1 analysis is still discarded by the director")
for needed in ("wooden stacking rings", "closeup_ugc", "why_it_works"):
    if needed not in brief:
        fails.append(f"the reference reading dropped {needed!r}")
if "\"camera\"" in brief or '"device"' in brief:
    fails.append("the whole analysis was pasted in; only subject/scene/psychology should be")
if brief.index("PRODUCT CLASS") > brief.index("VISUAL DNA"):
    fails.append("the class block must come first so it frames everything after it")
if "TREND CONTEXT: back to school" not in brief:
    fails.append("trend context missing from the director's brief")
if _build_user_prompt(QUIET_DNA, FIXTURES[0][1], TRUTH, classified["toys"], None, None) \
        .count("REFERENCE READING"):
    fails.append("a missing analysis must not produce an empty REFERENCE READING block")

# A picture of a toy classified by Stage 1 must not be pulled into apparel by a
# vague product record.
mixed = classify_product({"name": "Gift Set", "category": ""}, ANALYSIS)
if mixed.key != "toys":
    fails.append(f"Stage 1's reading did not steer classification: got {mixed.key!r} ({mixed.describe()})")

# ── report ────────────────────────────────────────
print(f"classes={len(CLASSES)}  formats={len(CREATIVE_FORMATS)}  fixtures={len(FIXTURES)}")
for expected, product in FIXTURES:
    k = classified[expected].product_class
    print(f"  {product['name'][:38]:38s} -> {k.key:11s} {k.framing:6s} "
          f"avoid={len(k.avoid_clauses())}")
print("\nFAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
