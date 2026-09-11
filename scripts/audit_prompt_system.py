"""
Prompt System Audit — one command, four checks.

    python -m scripts.audit_prompt_system

1. API contract  — every frontend call has a matching backend route.
2. DNA conformance — how often the Visual DNA the analyst WRITES fails to match
   the keys prompt_compiler READS (a miss means a hardcoded default silently
   replaced a reference-specific value).
3. Prompt hygiene — recompiles a real job and looks for internal enum tokens,
   broken templates, and irrelevant realism modules leaking into the prompt.
4. Shot set — the four archetype prompts are genuinely distinct, share one product
   passport, and single-prompt mode still emits the six-axis block.

Exit code is non-zero when a check finds a problem, so it can gate CI.
"""

from __future__ import annotations

import io
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

FAILURES: list[str] = []


def header(title: str) -> None:
    print("\n" + "=" * 74)
    print(title)
    print("=" * 74)


# ───────────────────────── 1. API CONTRACT ─────────────────────────
def check_api_contract() -> None:
    header("1. API CONTRACT — frontend calls vs registered backend routes")
    from app.main import app

    backend = []
    for r in app.routes:
        methods = getattr(r, "methods", None)
        path = getattr(r, "path", None)
        if not path or not methods:
            continue
        for m in methods:
            if m not in ("HEAD", "OPTIONS"):
                backend.append((m, path))

    api_base = "/api"
    if not (ROOT / "frontend" / "src" / "api.ts").is_file():
        print("  frontend/src/api.ts not found — skipped")
        return
    m = re.search(r"const API_BASE\s*=\s*['\"]([^'\"]+)['\"]",
                  (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8"))
    if m:
        api_base = m.group(1)

    def parse_template(raw: str) -> str:
        out, i, n = [], 0, len(raw)
        while i < n:
            ch = raw[i]
            if ch == "$" and i + 1 < n and raw[i + 1] == "{":
                depth, j = 1, i + 2
                while j < n and depth:
                    depth += (raw[j] == "{") - (raw[j] == "}")
                    j += 1
                inner = raw[i + 2: j - 1].strip()
                if inner in ("API_BASE", "API_URL"):
                    out.append(api_base)
                elif not ("?" in inner or inner in ("qs", "query", "params")):
                    out.append("{}")
                i = j
                continue
            if ch == "?":
                break
            out.append(ch)
            i += 1
        return re.sub(r"\{[^}]*\}", "{}", "".join(out)).rstrip("/") or "/"

    calls = []
    src = ROOT / "frontend" / "src"
    for f in sorted(list(src.rglob("*.ts")) + list(src.rglob("*.tsx"))):
        text = f.read_text(encoding="utf-8", errors="replace")
        for mm in re.finditer(r"(?:fetch|apiFetch)\(\s*`((?:[^`\\]|\\.)*)`", text, re.S):
            calls.append((parse_template(mm.group(1)), f.name, text[: mm.start()].count("\n") + 1))

    def matches(fe: str, be: str) -> bool:
        a, b = fe.strip("/").split("/"), be.strip("/").split("/")
        return len(a) == len(b) and all(x == "{}" or y == "{}" or x == y for x, y in zip(a, b))

    broken = [(p, f, l) for p, f, l in calls if not any(matches(p, b) for _, b in backend)]
    print(f"  backend routes : {len(backend)}")
    print(f"  frontend calls : {len(calls)}")
    if broken:
        FAILURES.append(f"{len(broken)} frontend call(s) have no backend route")
        for p, f, l in broken:
            print(f"  BROKEN  {p:46} {f}:{l}")
    else:
        print("  OK — every frontend call resolves to a registered route")


# ───────────────────────── 2. DNA CONFORMANCE ─────────────────────────
READS = {
    "lighting_dna": ["source", "contrast", "warmth"],
    "camera_dna": ["sharpness", "noise", "hdr"],
    "material_dna": ["texture_visibility", "surface_imperfection"],
    "composition_dna": ["centering", "crop", "camera_height"],
    "environment_dna": ["clutter"],
    "measured_facts": ["dominant_palette"],
    "realism_markers": ["anti_studio", "anti_cinematic"],
}
ALT_KEYS = {
    ("lighting_dna", "source"): "type",
    ("lighting_dna", "contrast"): "quality",
    ("lighting_dna", "warmth"): "color_cast",
    ("camera_dna", "noise"): "sensor_noise",
    ("camera_dna", "hdr"): "dynamic_range",
}

# Known-acceptable gaps — reported as INFO, never as a failure.
#   dominant_palette : the pixel-measurement feature post-dates the stored DNA,
#                      so every legacy row lacks it. Re-analysing a reference
#                      repopulates it; nothing to fix in code.
#   sharpness        : the stored camera schema carries no sharpness equivalent
#                      (only device_family / focal_length), so the default is
#                      the only honest answer.
EXPECTED_FALLBACK = {
    "measured_facts.dominant_palette": "legacy DNA predates pixel measurements — re-analyse a reference",
    "camera_dna.sharpness": "no sharpness equivalent exists in the stored camera schema",
}


def check_dna_conformance() -> None:
    header("2. DNA CONFORMANCE — what the analyst writes vs what the compiler reads")
    db = ROOT / "data" / "pre.db"
    if not db.is_file():
        print("  data/pre.db not found — skipped")
        return
    con = sqlite3.connect(db)
    rows = con.execute("SELECT dna_json FROM visual_dnas").fetchall()
    if not rows:
        print("  no visual_dnas rows — skipped")
        return

    miss, rescued = {}, {}
    for (raw,) in rows:
        try:
            d = json.loads(raw)
        except Exception:
            continue
        for block, keys in READS.items():
            b = d.get(block) if isinstance(d.get(block), dict) else {}
            for k in keys:
                if k not in b:
                    miss[f"{block}.{k}"] = miss.get(f"{block}.{k}", 0) + 1
                    alt = ALT_KEYS.get((block, k))
                    if alt and alt in b:
                        rescued[f"{block}.{k}"] = rescued.get(f"{block}.{k}", 0) + 1

    total = len(rows)
    print(f"  DNA records: {total}\n")
    print(f"  {'lookup':44} {'missing':>9} {'recovered by dual-key read':>28}")
    for key in sorted(miss, key=lambda k: -miss[k]):
        pct = 100.0 * miss[key] / total
        rec = rescued.get(key, 0)
        flag = "  <-- HARDCODED DEFAULT" if pct > 25 and rec == 0 else ""
        print(f"  {key:44} {miss[key]:4}/{total} {pct:5.1f}% {rec:>20}{flag}")

    if rescued:
        print("\n  Dual-key reads recover (previously silently defaulted):")
        for k, v in sorted(rescued.items(), key=lambda x: -x[1]):
            print(f"    {k:42} {v}")

    hard, info = [], []
    for key in miss:
        if 100.0 * miss[key] / total <= 25 or rescued.get(key, 0) > 0:
            continue
        (info if key in EXPECTED_FALLBACK else hard).append(key)

    if info:
        print("\n  INFO — falls back by design, not a bug:")
        for k in info:
            print(f"    {k:42} {EXPECTED_FALLBACK[k]}")

    if hard:
        FAILURES.append(f"{len(hard)} DNA lookup(s) fall back to hardcoded defaults >25% of the time")
    else:
        print("\n  OK — no unexpected hardcoded-default fallback")


# ───────────────────────── 3. PROMPT HYGIENE ─────────────────────────
LEAK_TOKENS = ["high_tactile", "natural_fabric_grain", "slightly_off_center",
               "human_standing", "partial_body", "partial_hand_arm",
               "rule_of_thirds", "eye_level", "natural_smartphone", "medium,"]
BAD_PHRASES = ["Captured with the product is", "in in a", "with the product is",
               "None", "undefined", "{", "}"]
HAND_TOKENS = ["cuticle", "fingertip", "knuckle", "hangnail", "wrist", "grip"]


def _load_audit_job() -> dict | None:
    """The most recent job that has a scene, a DNA and a product, as compile inputs."""
    db = ROOT / "data" / "pre.db"
    if not db.is_file():
        return None
    con = sqlite3.connect(db)
    row = con.execute(
        "SELECT j.scene_json, j.visual_dna_id, j.product_id FROM jobs j "
        "JOIN visual_dnas d ON d.id = j.visual_dna_id "
        "WHERE j.scene_json IS NOT NULL ORDER BY j.updated_at DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None
    scene_json, dna_id, prod_id = row
    scene = json.loads(scene_json)
    dna = json.loads(
        con.execute("SELECT dna_json FROM visual_dnas WHERE id=?", (dna_id,)).fetchone()[0]
    )
    p = con.execute(
        "SELECT name, materials, category FROM products WHERE id=?", (prod_id,)
    ).fetchone()
    product = {
        "name": p[0] if p else "Product",
        "materials": json.loads(p[1]) if p and p[1] else [],
        "category": p[2] if p else None,
    }
    pt = con.execute("SELECT product_truth_json FROM products WHERE id=?", (prod_id,)).fetchone()
    truth = json.loads(pt[0]) if pt and pt[0] else {"must_preserve": ["as listed"]}
    return {"scene": scene, "dna": dna, "product": product, "truth": truth}


def check_prompt_hygiene() -> None:
    header("3. PROMPT HYGIENE — recompile a real job and inspect the output")
    job = _load_audit_job()
    if job is None:
        print("  no usable job row — skipped")
        return
    scene, dna, product, truth = job["scene"], job["dna"], job["product"], job["truth"]

    from app.pipeline.prompt_compiler import compile_prompt
    res = compile_prompt(dna, product, truth, scene, trend_label=None)
    text = res.prompt
    print(f"  human_presence : {scene.get('human_presence')!r}")
    print(f"  prompt length  : {len(text)}\n")

    problems = []
    for tok in LEAK_TOKENS:
        if tok in text:
            problems.append(f"internal enum token leaked: {tok!r} x{text.count(tok)}")
    for ph in BAD_PHRASES:
        if ph in text:
            problems.append(f"broken/placeholder text: {ph!r}")
    hp = str(scene.get("human_presence") or "none")
    if hp in ("none", "partial_body"):
        n = sum(text.lower().count(t) for t in HAND_TOKENS)
        if n:
            problems.append(f"{n} hand/skin detail(s) in a scene with human_presence={hp!r}")

    if problems:
        FAILURES.extend(problems)
        for pr in problems:
            print(f"  PROBLEM  {pr}")
    else:
        print("  OK — no enum leakage, no broken templates, modules match the scene")
    print("\n  --- prompt preview ---")
    for line in text.split("\n")[:6]:
        if line.strip():
            print("   " + line[:150])


# ───────────────────────── 4. SHOT SET ─────────────────────────


def check_shot_set() -> None:
    """
    The four-shot architecture: one prompt per archetype.

    Flow's `count` parameter takes ONE prompt and returns N stochastic samples of
    it, so four genuinely distinct photographs need four prompts and four
    submissions. This check guards the two ways that silently breaks:

      - the four prompts collapse back into variations of one prompt, or
      - single-prompt mode (shot_archetype=None) stops emitting the six-axis block.

    It also asserts the product passport is shared byte-for-byte, because four
    shots that disagree about the product are four unusable images.
    """
    header("4. SHOT SET — four archetype prompts, genuinely distinct")
    job = _load_audit_job()
    if job is None:
        print("  no usable job row — skipped")
        return
    scene, dna, product, truth = job["scene"], job["dna"], job["product"], job["truth"]

    from app.pipeline.prompt_compiler import compile_prompt, compile_shot_set
    from app.pipeline.shot_archetypes import SHOT_ORDER

    problems: list[str] = []

    # Single-prompt mode must still emit the six directed axes.
    single = compile_prompt(dna, product, truth, scene, trend_label=None)
    if "FLOW VARIATION — honour all six directed axes" not in single.prompt:
        problems.append(
            "single-prompt mode no longer emits the six-axis FLOW VARIATION block"
        )
    if "SHOT TYPE —" in single.prompt:
        problems.append("single-prompt mode leaked a shot-archetype directive")

    results = compile_shot_set(dna, product, truth, scene, trend_label=None)
    if len(results) != 4:
        problems.append(f"compile_shot_set returned {len(results)} results, expected 4")
    if not all(r.is_valid for r in results):
        bad = [r.shot_archetype for r in results if not r.is_valid]
        problems.append(f"archetypes failed to compile: {bad}")
    else:
        prompts = [r.prompt for r in results]
        if len(set(prompts)) != 4:
            problems.append("the four archetype prompts are not all distinct")

        print(f"  product        : {product.get('name')!r}")
        for r in results:
            print(f"    {r.shot_archetype:12} {r.aspect_ratio:6} {len(r.prompt):5}d  {r.shot_label}")

        # Each prompt carries its own directive and no other.
        for r in results:
            if f"SHOT TYPE — {r.shot_label}." not in r.prompt:
                problems.append(f"{r.shot_archetype}: own directive missing")
            if "FLOW VARIATION — honour all six directed axes" in r.prompt:
                problems.append(
                    f"{r.shot_archetype}: six-axis block still present alongside a directive"
                )

        # The product passport must be identical across the set.
        try:
            passport = prompts[0].split("Featuring ")[1].split(". Strictly accurate")[0]
        except IndexError:
            passport = ""
        if passport and any(passport not in p for p in prompts[1:]):
            problems.append("product passport differs between shots")

        # Aspect ratios must differ — four identical crops defeat the purpose.
        ratios = [r.aspect_ratio for r in results]
        if len(set(ratios)) < 3:
            problems.append(f"archetype aspect ratios are not varied: {ratios}")

        # Human presence belongs on the lifestyle shot only.
        if "Human presence is" not in prompts[0]:
            problems.append("the lifestyle shot carries no human presence")
        for r in results[1:]:
            if "Human presence is" in r.prompt:
                problems.append(f"{r.shot_archetype}: carries human presence")

        # Enum leakage, checked per archetype.
        for r in results:
            for tok in LEAK_TOKENS:
                if tok in r.prompt:
                    problems.append(f"{r.shot_archetype}: enum token leaked {tok!r}")

        print(f"  archetypes     : {', '.join(SHOT_ORDER)}")

    if problems:
        FAILURES.extend(problems)
        for pr in problems:
            print(f"  PROBLEM  {pr}")
    else:
        print("  OK — four distinct prompts, shared passport, six-axis mode intact")


def main() -> int:
    print("PROMPT SYSTEM AUDIT")
    print(f"root: {ROOT}")
    check_api_contract()
    check_dna_conformance()
    check_prompt_hygiene()
    check_shot_set()

    header("SUMMARY")
    if FAILURES:
        print(f"  {len(FAILURES)} problem(s) found:")
        for f in FAILURES:
            print(f"    - {f}")
        return 1
    print("  All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
