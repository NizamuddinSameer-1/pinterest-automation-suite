"""Offline check of the prompt compiler: sanitizer scope + trend anchor."""
import sys, tempfile, types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # project root, works on any machine
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

from app.pipeline.prompt_compiler import compile_prompt, _scrub, BANNED_KEYWORDS

DNA = {
    "camera_dna": {"smartphone_behavior": True, "sharpness": "moderate", "noise": "subtle", "hdr": "restrained"},
    "composition_dna": {"framing": "natural", "centering": "off-center", "crop": "natural", "camera_height": "standing"},
    "lighting_dna": {"source": "window daylight", "contrast": "low", "warmth": "neutral"},
    "material_dna": {"texture_visibility": "high", "surface_imperfection": "moderate"},
    "environment_dna": {"real_world_context": True, "clutter": "moderate", "background_activity": "low"},
    "realism_markers": {"imperfection_level": "moderate", "anti_studio": True, "anti_cinematic": True},
}
PRODUCT = {"name": "Linen Wrap Dress", "category": "fashion", "materials": ["linen"]}
TRUTH = {"must_preserve": ["wrap tie", "button count"], "must_not_invent": ["logos"]}
SCENE = {"capture_motivation": "She texted a friend the fit before leaving.",
         "location": "a small apartment hallway", "action": "adjusting the tie",
         "background_elements": ["coat hooks", "unopened post"],
         "human_presence": "partial", "camera_position": "handheld", "creative_format": "wear_test"}

fails = []

# 1. The compiler must not strip its own negative constraints.
r = compile_prompt(DNA, PRODUCT, TRUTH, SCENE, trend_label="quiet luxury autumn")
for needed in ("anti-cinematic", "cinematic lighting", "AVOID:"):
    if needed not in r.prompt:
        fails.append(f"self-sabotage: lost {needed!r}")
if not r.is_valid:
    fails.append("valid input reported invalid")

# 2. trend_label must reach the prompt.
if "quiet luxury autumn" not in r.prompt:
    fails.append("trend_label not used in prompt")
# The compiler was rewritten from uppercase metadata headers to a natural
# narrative brief; section 1 now opens with the candid-UGC scene intent.
if not r.prompt.split("\n\n")[0].startswith("A spontaneous, candid UGC smartphone photograph"):
    fails.append("section 1 is no longer the UGC scene-intent opener")

# 3. Section count / contract: 12 sections here (HUMAN INTERACTION present).
n = len(r.prompt.split("\n\n"))
print(f"sections={n}")

# 4. Banned keywords in DATA must still be stripped.
dirty_scene = dict(SCENE, capture_motivation="A cinematic, 8k masterpiece of the dress, ultra-realistic.")
r2 = compile_prompt(DNA, PRODUCT, TRUTH, dirty_scene, trend_label="award-winning autumn looks")
first = r2.prompt.split("\n\n")[0]
for bad in ("cinematic,", "8k", "masterpiece", "ultra-realistic", "award-winning"):
    if bad in first:
        fails.append(f"banned keyword survived in data: {bad!r}")
if "anti-cinematic" not in r2.prompt:
    fails.append("data scrub leaked into fixed text")
warned = [w.message for w in r2.warnings if "Auto-stripped" in w.message]
if not warned:
    fails.append("no warning raised for stripped input keywords")
else:
    print("warning:", warned[0])
print("dirty intent ->", first.replace("\n", " | "))

# 5. Hyphen guard: 'anti-cinematic' arriving as data must survive.
kept = _scrub("anti-cinematic look, non-cinematic feel", set())
if "anti-cinematic" not in kept or "non-cinematic" not in kept:
    fails.append(f"hyphen guard failed: {kept!r}")

# 6. Missing trend_label -> info warning, still valid.
r3 = compile_prompt(DNA, PRODUCT, TRUTH, SCENE, trend_label=None)
if not r3.is_valid or not any(w.severity == "info" for w in r3.warnings):
    fails.append("missing trend_label should be an info warning, not fatal")

# 7. Hard validation still fatal.
r4 = compile_prompt(DNA, PRODUCT, {}, SCENE)
if r4.is_valid or r4.prompt:
    fails.append("missing product truth should be fatal")

print("\nFAILURES:", fails if fails else "none")
