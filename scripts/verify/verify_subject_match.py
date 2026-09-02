"""
Offline check that a reference and a product describing different things cannot be
combined silently, and that a photograph can become a product.

The failure, in the operator's words: *"i providd this refrence product those two
ghost type lamp or ehat evrr that ws and see what flow give me genrted image why
pants"*. Nothing had crashed. Stage 1 read the photo correctly (`home_decor`,
"illuminated ghost figures"); the Creative Lab had pre-selected the first seeded
product row with `setSelectedProdId(prods[0].id)`; PRE takes SUBJECT and PRODUCT
TRUTH from the product and only the photographic style from the reference; so the
pipeline rendered "Pumpkin Fleece Pajama Pants" faithfully and the operator watched
four mirror selfies come back from a photo of two lamps.

Asserts, with no network, no LLM and no database:

  1. the real ghost-lamp analysis classifies as `home_decor` with confidence, and
     every seeded product blocks against it;
  2. near neighbours inside one family (costume/apparel) are reported but allowed,
     because a costume really is shot like a garment;
  3. anything undecidable — no analysis, GENERIC, low confidence — never blocks: a
     guess must not stop a run;
  4. the drafter turns that same analysis into a product whose PRESERVE list
     describes the lamps, and never invents a price, merchant or affiliate URL;
  5. the wiring is present: the generation endpoint checks the match before the
     scene director, the override is a per-run parameter, and the Creative Lab no
     longer pre-selects a product.

`subject_match` and `product_drafter` are pure by design (no LLM, no I/O, no
`app.config`), so they are imported directly rather than lifted by AST.
"""
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# pydantic-settings is not installed here and neither module needs it, but
# `app/__init__.py` may pull it in. Stub the package the same way the others do.
pkg = types.ModuleType("app")
pkg.__path__ = [str(ROOT / "app")]
sys.modules.setdefault("app", pkg)
cfg = types.ModuleType("app.config")


class S:
    pass


cfg.settings = S()
sys.modules["app.config"] = cfg

from app.pipeline.product_taxonomy import GENERIC, classify_product  # noqa: E402
from app.pipeline.subject_match import (  # noqa: E402
    FAMILIES,
    check_subject_match,
    classify_reference,
    family_of,
    reference_objects,
    reference_textures,
)
from app.services.product_drafter import (  # noqa: E402
    UNKNOWABLE_FROM_A_PHOTO,
    draft_product_from_analysis,
)

fails: list[str] = []

# ── fixtures ──────────────────────────────────────
# Trimmed from the real `reference_analyses` row for reference
# 2c3b785e-7208-4a73-93c3-8dab04a51718 — the photograph that started this.
GHOST_LAMPS = {
    "subject": {
        "primary_category": "home_decor",
        "secondary_category": "seasonal_decor",
        "objects": [
            "illuminated ghost figures",
            "ceramic vase with branches",
            "candlestick with lit candle",
            "miniature pumpkin",
            "bat wall decals",
            "wooden mantel",
        ],
        "product_visibility": "high",
        "human_presence": "none",
    },
    "scene": {"type": "seasonal_staging", "context": "Halloween mantel styling"},
    "materials": {
        "primary_textures": ["soft draped fabric", "matte ceramic", "smooth wood"],
        "texture_visibility": "high",
        "imperfection_level": "low",
    },
    "psychology": {"primary_hooks": ["seasonal_urgency", "inspiration", "discovery"]},
}

# The same photograph as a *newer* analysis would describe it: with product_facts.
GHOST_LAMPS_WITH_FACTS = {
    **GHOST_LAMPS,
    "product_facts": {
        "is_single_product": True,
        "product_name_guess": "two illuminated ghost figurines",
        "product_type": "illuminated ghost figurine lamps",
        "visible_colors": ["white", "warm amber glow"],
        "visible_materials": ["draped fabric", "frosted plastic"],
        "shape_or_silhouette": "rounded draped ghost form with a pointed hood",
        "distinguishing_features": ["black oval eyes", "internal warm LED light"],
        "text_or_branding_visible": [],
        "confidence": "high",
    },
}

# The four seeded rows, as `_product_to_dict` hands them to the guard.
PAJAMAS = {
    "name": "Pumpkin Fleece Pajama Pants",
    "category": "sleepwear",
    "key_attributes": ["black base colour", "orange pumpkin print", "soft fleece"],
    "materials": ["fleece"],
}
MAID_COSTUME = {
    "name": "Gothic Maid Costume Set",
    "category": "costumes",
    "key_attributes": ["lace trim", "apron", "black and white"],
    "materials": ["polyester"],
}
LIP_OIL = {
    "name": "Glazed Cherry Lip Oil",
    "category": "beauty",
    "key_attributes": ["glossy finish", "tinted"],
    "materials": ["glass bottle"],
}
GHOST_LAMP_PRODUCT = {
    "name": "Illuminated Ghost Figurine Lamps",
    "category": "home_decor",
    "key_attributes": ["warm LED glow", "draped fabric form"],
    "materials": ["frosted plastic", "fabric"],
}

# ── 1. the photograph is read, and the mismatch blocks ──
ref_class = classify_reference(GHOST_LAMPS)
if ref_class is None:
    fails.append("the ghost-lamp analysis produced no classification at all")
elif ref_class.key != "home_decor":
    fails.append(f"the ghost-lamp photo classified as {ref_class.key!r}, not home_decor")
elif ref_class.confidence == "low":
    fails.append("the ghost-lamp photo classified with low confidence, so nothing would block")

if reference_objects(GHOST_LAMPS)[0] != "illuminated ghost figures":
    fails.append("reference_objects lost the object Stage 1 named first")
if "matte ceramic" not in reference_textures(GHOST_LAMPS):
    fails.append("reference_textures lost the photograph's textures")

pants = check_subject_match(PAJAMAS, GHOST_LAMPS)
if not pants.blocking:
    fails.append(f"the pyjama pants did NOT block against the ghost lamps: {pants.summary()}")
if pants.agrees:
    fails.append("the pyjama pants were reported as agreeing with a photo of lamps")
for phrase in ("ghost", "generate anyway", "Use this photo as the product"):
    if phrase.lower() not in pants.message.lower():
        fails.append(f"the refusal message never mentions {phrase!r} — a block must say the way out")

# The way out must name a control that exists. The first version told the operator to
# click "Use this reference as the product"; the button reads "Use this photo as the
# product", so the instruction pointed at nothing.
lab_labels = (ROOT / "frontend" / "src" / "components" / "CreativeLab.tsx").read_text(encoding="utf-8")
for quoted in ("Use this photo as the product",):
    if quoted not in lab_labels:
        fails.append(f"the refusal message quotes {quoted!r}, which is not a label in the Creative Lab")

# The matching product must sail through.
same = check_subject_match(GHOST_LAMP_PRODUCT, GHOST_LAMPS)
if same.blocking or not same.agrees:
    fails.append(f"a ghost-lamp product did not agree with a ghost-lamp photo: {same.summary()}")

# A beauty product against a home photo: different families, both confident.
if not check_subject_match(LIP_OIL, GHOST_LAMPS).blocking:
    fails.append("a lip oil did not block against a photo of home decor")

# ── 2. near neighbours are reported, not refused ──
costume_shot = {
    "subject": {
        "primary_category": "apparel",
        "secondary_category": "dresses",
        "objects": ["black lace dress", "white apron", "ruffled headband"],
        "product_visibility": "high",
        "human_presence": "partial",
    },
    "materials": {"primary_textures": ["lace", "polyester satin"]},
}
neighbour = check_subject_match(MAID_COSTUME, costume_shot)
if neighbour.blocking:
    fails.append(f"a costume blocked against a photo of a dress: {neighbour.summary()}")
if neighbour.agrees and neighbour.product_class == neighbour.reference_class:
    pass  # classified identically, which is also fine
elif "close enough" not in neighbour.message:
    fails.append("a same-family disagreement should be reported as allowed, and was not")

for family, members in FAMILIES.items():
    for member in members:
        if family_of(member) != family:
            fails.append(f"family_of({member!r}) disagrees with FAMILIES[{family!r}]")

# ── 3. nothing undecidable may block ──
no_analysis = check_subject_match(PAJAMAS, None)
if no_analysis.blocking or not no_analysis.agrees:
    fails.append("a reference with no analysis blocked a run")
if check_subject_match(PAJAMAS, {}).blocking:
    fails.append("an empty analysis blocked a run")

vague_photo = {
    "subject": {"primary_category": "", "secondary_category": "", "objects": ["an object"]},
    "materials": {"primary_textures": []},
}
if check_subject_match(PAJAMAS, vague_photo).blocking:
    fails.append("an unreadable photograph blocked a run — a guess must never block")
if classify_product({"name": "Thing", "category": ""}).product_class is not GENERIC:
    fails.append("a nameless product no longer falls back to GENERIC, so the guard may over-block")

# ── 4. the photograph can become the product ──
draft = draft_product_from_analysis(GHOST_LAMPS_WITH_FACTS, trend_label="Halloween")
if "ghost" not in draft.name.lower():
    fails.append(f"the drafted product is not named after the object: {draft.name!r}")
if draft.name[:1].islower():
    fails.append(f"the drafted name is not shop-style capitalised: {draft.name!r}")
if draft.name.lower().startswith(("two ", "a ", "the ")):
    fails.append(f"the drafted name kept a leading count word: {draft.name!r}")
if draft.class_key != "home_decor" or draft.category != "home_decor":
    fails.append(f"the draft is filed as {draft.category}/{draft.class_key}, not home_decor")
if draft.seasons != ["Halloween"]:
    fails.append(f"the trend label did not reach the draft's seasons: {draft.seasons}")
if draft.confidence != "high":
    fails.append(f"the draft lost Stage 1's confidence: {draft.confidence!r}")

preserve = " | ".join(draft.product_truth["must_preserve"]).lower()
for needed in ("ghost", "colour:", "material and finish:", "silhouette:", "led"):
    if needed not in preserve:
        fails.append(f"the PRESERVE list is missing {needed!r} — that is the line that described pants")
if "pumpkin" in preserve or "fleece" in preserve:
    fails.append("the drafted PRESERVE list describes the seeded pyjamas, not the photograph")
if not draft.product_truth["must_not_invent"]:
    fails.append("the draft invented nothing to hold the model back with")
if not any("branding" in c or "logo" in c for c in draft.product_truth["must_not_invent"]):
    fails.append("a product with no visible branding must forbid invented logos")
if not draft.product_truth["allowed_scene_variations"]:
    fails.append("the draft has no FREE TO VARY list, so the model will copy the reference scene")

# Nothing readable off a photograph may be invented.
fields = draft.as_product_fields()
for banned in UNKNOWABLE_FROM_A_PHOTO:
    if banned in fields:
        fails.append(f"the drafter tried to fill in {banned!r}, which no photograph shows")
if set(draft.needs) != set(UNKNOWABLE_FROM_A_PHOTO):
    fails.append("the draft's `needs` list no longer matches UNKNOWABLE_FROM_A_PHOTO")

# The older analysis (no product_facts) must still draft, and must say it is thin.
older = draft_product_from_analysis(GHOST_LAMPS, trend_label="Halloween")
if "ghost" not in older.name.lower():
    fails.append(f"the pre-product_facts fallback lost the object: {older.name!r}")
if not any("re-analyse" in n.lower() for n in older.notes):
    fails.append("a reconstructed draft must say it was reconstructed and can be re-analysed")
if not older.materials:
    fails.append("the fallback did not borrow the photograph's textures as materials")

many_things = {
    "subject": {"primary_category": "home_decor", "objects": ["a shelf of unrelated items"]},
    "product_facts": {"is_single_product": False, "product_type": "shelf display",
                      "visible_colors": [], "visible_materials": [], "confidence": "low"},
}
if not any("one main product" in n for n in draft_product_from_analysis(many_things).notes):
    fails.append("a flat-lay of many items must be flagged, not drafted silently")

try:
    draft_product_from_analysis({"subject": {"objects": []}})
    fails.append("an analysis naming nothing produced a draft instead of refusing")
except ValueError:
    pass


# ── 5. the wiring ─────────────────────────────────
def code_only(text: str) -> str:
    """
    Source with comments removed.

    Necessary because the fixes deliberately quote what they replaced: the comment
    above the product dropdown names `setSelectedProdId(prods[0].id)`, and a naive
    substring search would report the bug it documents.

    Line comments go first. One of them contains "/data/*", and stripping block
    comments first made that stray "/*" swallow half the component.
    """
    text = re.sub(r"^\s*(//|#).*$", "", text, flags=re.M)      # // line and # line
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)          # /* … */ and {/* … */}
    return text


gen = code_only((ROOT / "app" / "api" / "generation.py").read_text(encoding="utf-8"))
if "check_subject_match(" not in gen:
    fails.append("app/api/generation.py never calls check_subject_match — the guard is not wired in")
elif gen.index("check_subject_match(") > gen.index("generate_scene("):
    fails.append("the subject guard runs after the scene director; it must refuse before any LLM call")
if "load_reference_analysis" not in gen:
    fails.append("generation.py stopped loading the Stage 1 analysis, so the guard has nothing to compare")

# The "load once, before the scene branch" rule is about a single request path, not
# about the file: `_prepare_brief` (every generate route) and `/preview-prompt` each
# load the analysis once, legitimately. Counting file-wide reported the second,
# correct call as a bug, so each path is now checked on its own.
GUARDED_PATHS = {
    "_prepare_brief": ("async def _prepare_brief", "def _launch_background_run"),
    "/preview-prompt": ("async def preview_prompt_endpoint", None),
}
for path_name, (opens, closes) in GUARDED_PATHS.items():
    start = gen.find(opens)
    if start < 0:
        fails.append(f"{path_name} is gone from generation.py; the guard's home has moved")
        continue
    end = gen.find(closes, start) if closes else len(gen)
    region = gen[start:end if end > start else len(gen)]
    loads = region.count("load_reference_analysis(db")
    if loads != 1:
        fails.append(
            f"{path_name} loads the analysis {loads} times; it must be loaded once, "
            "before the scene branch, not per-branch"
        )
    if "check_subject_match(" not in region:
        fails.append(f"{path_name} does not run the subject guard at all")
    elif "generate_scene(" in region and region.index("check_subject_match(") > region.index("generate_scene("):
        fails.append(f"{path_name} runs the guard after the scene director; it must refuse before any LLM call")
if "allow_subject_mismatch" not in gen:
    fails.append("there is no per-run override, so a style-only reference cannot be used at all")
if 'allow_subject_mismatch=False, db=db' not in gen:
    fails.append("a deprecated alias may pass its Query() default (truthy) and disable the guard")
if '"error": "subject_mismatch"' not in gen:
    fails.append("the 409 body has no machine-readable marker, so the UI cannot offer the ways out")

refs_api = code_only((ROOT / "app" / "api" / "references.py").read_text(encoding="utf-8"))
if "draft-product" not in refs_api:
    fails.append("POST /api/references/{id}/draft-product is missing")
if 'availability="unverified"' not in refs_api:
    fails.append("a product drafted from a photograph must be marked unverified")
for invented in ("price=", "merchant=", "affiliate_url="):
    if invented in refs_api:
        fails.append(f"the draft endpoint sets {invented} — nothing here was checked against a shop")

lab = code_only((ROOT / "frontend" / "src" / "components" / "CreativeLab.tsx").read_text(encoding="utf-8"))
if "setSelectedProdId(prods[0].id)" in lab:
    fails.append("the Creative Lab still pre-selects the first product — this is the pyjama-pants bug")
if "uploadPendingFile" not in lab:
    fails.append("a chosen-but-unuploaded file can still be ignored by Analyze and Generate")
if lab.count("uploadPendingFile") < 4:
    fails.append("not every path (choose, upload, analyse, generate, draft) handles the pending file")
if "SubjectMismatchError" not in lab:
    fails.append("the Creative Lab does not handle the mismatch 409, so the operator sees raw JSON")
if "draftProductFromReference" not in lab:
    fails.append("there is no way in the UI to make the photograph the product")

api_ts = code_only((ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8"))
if "allow_subject_mismatch" not in api_ts:
    fails.append("api.ts cannot send the override, so 'generate anyway' would 409 forever")
if "class SubjectMismatchError" not in api_ts:
    fails.append("api.ts does not raise a typed mismatch error")

# ── report ────────────────────────────────────────
print(f"reference -> {ref_class.key if ref_class else 'none'} "
      f"({ref_class.confidence if ref_class else '-'}; {', '.join(reference_objects(GHOST_LAMPS)[:3])})")
for label, product in (("pyjama pants", PAJAMAS), ("maid costume", MAID_COSTUME),
                       ("lip oil", LIP_OIL), ("ghost lamps", GHOST_LAMP_PRODUCT)):
    m = check_subject_match(product, GHOST_LAMPS)
    verdict = "BLOCKS" if m.blocking else ("agrees" if m.agrees else "allowed")
    print(f"  {label:14s} {m.product_class:11s} vs {m.reference_class:11s} -> {verdict}")
print(f"draft: {draft.name!r} [{draft.class_key}] preserve={len(draft.product_truth['must_preserve'])} "
      f"needs={len(draft.needs)}")
print("\nFAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)

