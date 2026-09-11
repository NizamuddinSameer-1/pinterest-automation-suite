"""
Verify the four-shot architecture (Task 3).

Two things must both be true:

  1. REGRESSION — with `shot_archetype=None` the compiler must produce text that is
     byte-identical to the pre-archetype compiler. Single-prompt generation is the
     production path and must not shift by a single character.

     The baseline is built from git HEAD + the earlier bugfix patch, so it is the
     real "before" state: post-bugfix, pre-archetype. It is exec'd in isolation
     against its own copy of prompt_modules, so the comparison is honest.

  2. DISTINCTNESS — the four archetype prompts must be genuinely different in the
     ways that matter (shot type, camera, framing, crop, human presence, lighting)
     while sharing a byte-identical product passport and locked world.

Run: python -m scratch.verify_shot_set
"""
from __future__ import annotations

import importlib.util
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "scratch" / "baseline" / "app" / "pipeline"
sys.path.insert(0, str(ROOT))

from app.pipeline.prompt_compiler import compile_prompt, compile_shot_set  # noqa: E402
from app.pipeline.shot_archetypes import SHOT_ORDER  # noqa: E402

DB = ROOT / "data" / "pre.db"


# ─────────────────────────────────────────────────────────────────────
# Load the pre-archetype baseline in isolation
# ─────────────────────────────────────────────────────────────────────


def load_baseline():
    """Baseline prompt_compiler, wired to its own prompt_modules."""
    spec_m = importlib.util.spec_from_file_location(
        "baseline_prompt_modules", BASE / "prompt_modules.py"
    )
    mod_m = importlib.util.module_from_spec(spec_m)
    sys.modules["baseline_prompt_modules"] = mod_m
    spec_m.loader.exec_module(mod_m)

    src = (BASE / "prompt_compiler.py").read_text(encoding="utf-8")
    src = src.replace(
        "from app.pipeline.prompt_modules import", "from baseline_prompt_modules import"
    )
    assert "baseline_prompt_modules" in src, "baseline import rewrite failed"

    mod_c = importlib.util.module_from_spec(
        importlib.util.spec_from_file_location("baseline_prompt_compiler", BASE / "prompt_compiler.py")
    )
    sys.modules["baseline_prompt_compiler"] = mod_c
    exec(compile(src, str(BASE / "prompt_compiler.py"), "exec"), mod_c.__dict__)
    return mod_c


baseline = load_baseline()
assert not hasattr(baseline, "compile_shot_set"), "baseline already has shot-set support"
assert "shot_archetype" not in baseline.compile_prompt.__code__.co_varnames, (
    "baseline already has the shot_archetype parameter"
)
print("baseline loaded: pre-archetype compiler, isolated modules  [OK]")


# ─────────────────────────────────────────────────────────────────────
# Real jobs out of the live DB
# ─────────────────────────────────────────────────────────────────────


def _j(val, default):
    if not val:
        return default
    try:
        return json.loads(val)
    except Exception:
        return default


def load_jobs(limit: int = 6):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute("select * from jobs where scene_json is not null"))
    out = []
    for r in rows:
        d = dict(r)
        try:
            scene = json.loads(d["scene_json"])
        except Exception:
            continue
        if not scene.get("capture_motivation") or not d.get("visual_dna_id") or not d.get("product_id"):
            continue
        dna_row = conn.execute(
            "select dna_json from visual_dnas where id=?", (d["visual_dna_id"],)
        ).fetchone()
        prod_row = conn.execute("select * from products where id=?", (d["product_id"],)).fetchone()
        ref_row = conn.execute(
            'select trend_label from "references" where id=?', (d.get("reference_id"),)
        ).fetchone()
        if not dna_row or not prod_row:
            continue
        p = dict(prod_row)
        product = {
            "name": p.get("name"),
            "brand": p.get("brand"),
            "merchant": p.get("merchant"),
            "category": p.get("category"),
            "price": p.get("price"),
            "currency": p.get("currency"),
            "seasons": _j(p.get("seasons"), []),
            "colors": _j(p.get("colors"), []),
            "materials": _j(p.get("materials"), []),
            "key_attributes": _j(p.get("key_attributes"), []),
        }
        truth = _j(p.get("product_truth_json"), None) or {
            "must_preserve": product["key_attributes"],
            "must_not_invent": [],
            "allowed_scene_variations": [],
        }
        out.append(
            {
                "job_id": d["id"],
                "visual_dna": _j(dna_row["dna_json"], {}),
                "product": product,
                "product_truth": truth,
                "scene": scene,
                "trend_label": ref_row["trend_label"] if ref_row else None,
                "commerce_dna": _j(d.get("commerce_dna_json"), None),
                "concept": None,
            }
        )
        if len(out) >= limit:
            break
    return out


jobs = load_jobs()
print(f"loaded {len(jobs)} compilable jobs from the live DB\n")
assert jobs, "no compilable jobs found"


def kw(job):
    return {k: v for k, v in job.items() if k != "job_id"}


# ─────────────────────────────────────────────────────────────────────
# CHECK 1 — regression: shot_archetype=None is byte-identical
# ─────────────────────────────────────────────────────────────────────

print("=" * 78)
print("CHECK 1 — REGRESSION (shot_archetype=None must be byte-identical)")
print("=" * 78)

regressions = 0
for job in jobs:
    before = baseline.compile_prompt(**kw(job))
    after = compile_prompt(**kw(job), shot_archetype=None)
    same = before.prompt == after.prompt
    status = "IDENTICAL" if same else "*** CHANGED ***"
    print(f"  {job['job_id'][:8]}  {len(before.prompt):5}d -> {len(after.prompt):5d}d  {status}")
    if not same:
        regressions += 1
        b, a = before.prompt.splitlines(), after.prompt.splitlines()
        import difflib

        for line in list(difflib.unified_diff(b, a, lineterm="", n=1))[:40]:
            print("      " + line)
    # the single-prompt path must still emit the six-axis block, not a directive
    assert "FLOW VARIATION — honour all six directed axes" in after.prompt or not any(
        after.prompt.count(k) for k in ("camera_angle",)
    ), f"{job['job_id']}: six-axis block vanished without a directive"

assert regressions == 0, f"{regressions} job(s) regressed"
print("\nno regressions: single-prompt output is byte-identical  [PASS]\n")


# ─────────────────────────────────────────────────────────────────────
# CHECK 2 — scene must not be mutated by the archetype path
# ─────────────────────────────────────────────────────────────────────

print("=" * 78)
print("CHECK 2 — SCENE NOT MUTATED")
print("=" * 78)
for job in jobs[:3]:
    scene = job["scene"]
    snapshot = json.dumps(scene, sort_keys=True)
    compile_shot_set(**kw(job))
    assert json.dumps(scene, sort_keys=True) == snapshot, f"{job['job_id']}: scene mutated"
    print(f"  {job['job_id'][:8]}  scene unchanged after a 4-shot compile  [OK]")
print("\nno input mutation  [PASS]\n")


# ─────────────────────────────────────────────────────────────────────
# CHECK 3 — the four prompts are genuinely distinct
# ─────────────────────────────────────────────────────────────────────

print("=" * 78)
print("CHECK 3 — FOUR DISTINCT PROMPTS")
print("=" * 78)

ENUM_LEAK = re.compile(r"\b(?:[a-z]+_[a-z]+(?:_[a-z]+)*)\b")


def shared_prefix_len(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


for job in jobs:
    results = compile_shot_set(**kw(job))
    prompts = [r.prompt for r in results]

    assert len(results) == 4, "expected four results"
    assert all(r.is_valid for r in results), f"{job['job_id']}: an archetype failed to compile"
    assert len(set(prompts)) == 4, f"{job['job_id']}: prompts are not all distinct"

    print(f"\n  --- {job['job_id'][:8]}  product={job['product']['name']!r} ---")
    for r in results:
        print(
            f"      {r.shot_archetype:12} {r.aspect_ratio:6} {len(r.prompt):5}d  {r.shot_label}"
        )

    # each prompt must carry exactly its own directive and no other
    for r in results:
        own = f"SHOT TYPE — {r.shot_label}."
        assert own in r.prompt, f"{job['job_id']}/{r.shot_archetype}: own directive missing"
        for other in SHOT_ORDER:
            if other == r.shot_archetype:
                continue
            other_label = next(x.shot_label for x in results if x.shot_archetype == other)
            assert f"SHOT TYPE — {other_label}." not in r.prompt, (
                f"{job['job_id']}/{r.shot_archetype}: leaked {other} directive"
            )

    # the six-axis block must be gone from every shot prompt
    for r in results:
        assert "FLOW VARIATION — honour all six directed axes" not in r.prompt, (
            f"{job['job_id']}/{r.shot_archetype}: six-axis block still present"
        )

    # product passport must be identical across all four
    passport = results[0].prompt.split("Featuring ")[1].split(". Strictly accurate")[0]
    for r in results[1:]:
        assert passport in r.prompt, (
            f"{job['job_id']}/{r.shot_archetype}: product passport differs"
        )

    # aspect ratio must differ across the set
    ratios = [r.aspect_ratio for r in results]
    assert ratios == ["4:5", "1:1", "1:1", "9:16"], f"{job['job_id']}: bad ratios {ratios}"

    # no snake_case enum leakage in any prompt
    for r in results:
        leaks = set()
        for m in ENUM_LEAK.finditer(r.prompt):
            tok = m.group(0)
            if tok in {
                "must_preserve",
                "must_not_invent",
                "allowed_scene_variations",
                "capture_motivation",
                "partial_hand_arm",
                "partial_body",
            }:
                leaks.add(tok)
        assert not leaks, f"{job['job_id']}/{r.shot_archetype}: enum leak {sorted(leaks)}"

    # the four prompts must diverge well before the end (not just in the last line)
    for i in range(1, 4):
        cpl = shared_prefix_len(prompts[0], prompts[i])
        assert cpl < len(prompts[0]) * 0.85, (
            f"{job['job_id']}: shot {i} shares {cpl}/{len(prompts[0])} prefix with shot 0"
        )

print("\nfour distinct prompts per job, shared passport, no leakage  [PASS]\n")


# ─────────────────────────────────────────────────────────────────────
# CHECK 4 — the per-shot deltas are the ones we intended
# ─────────────────────────────────────────────────────────────────────

print("=" * 78)
print("CHECK 4 — PER-SHOT DELTAS")
print("=" * 78)

job = jobs[0]
results = {r.shot_archetype: r.prompt for r in compile_shot_set(**kw(job))}

EXPECT = {
    "lifestyle": ["medium framing", "4:5 vertical", "at chest height", "window light"],
    "flat_lay": ["wide framing", "square", "directly overhead", "diffused overhead key"],
    "macro": ["macro framing", "square", "macro working distance", "raking side light"],
    "environment": ["medium framing", "9:16 vertical", "eye level", "ambient light"],
}
for key, needles in EXPECT.items():
    text = results[key]
    for n in needles:
        assert n in text, f"{key}: expected {n!r} in its prompt"
    print(f"  {key:12} camera+crop+light all archetype-specific  [OK]")

# human presence: lifestyle has a person, the other three must not
assert "Human presence is" in results["lifestyle"], "lifestyle lost its human presence"
for key in ("flat_lay", "macro", "environment"):
    assert "Human presence is" not in results[key], f"{key} should have no human presence"
print("  human presence only on the lifestyle shot  [OK]")

# macro must not carry a surface or styling props
assert "STYLING PROPS" not in results["macro"], "macro carries styling props"
assert "BACKDROP:" in results["macro"], "macro lost its backdrop"
assert "SURFACE:" not in results["macro"], "macro carries a bare surface"
print("  macro has a defocused backdrop and no props  [OK]")

print("\nper-shot deltas correct  [PASS]\n")
print("=" * 78)
print("ALL SHOT-SET CHECKS PASSED")
print("=" * 78)
