"""
Offline verification of step 3: one generation path, one publisher.

The VM these checks run in has no network, so `fastapi`, `sqlalchemy`,
`playwright` and friends cannot be imported. Anything that needs those is
checked by reading the source (AST / text) instead; `app.config` is stubbed so
the pure modules can still be imported for real.

Checks:
  1. `app.services.generation` is importable and its contract holds
     (backend ids, AUTO_ORDER excluding pollinations, path normalisation).
  2. Nothing outside `generation.py` imports a generation backend directly.
  3. `POST /generate` exists once, and the old routes only survive as aliases
     that delegate — no second copy of the generation logic.
  4. `record_generation_outputs` is the only writer of JobOutput/PinDraft rows
     for generated images.
  5. No hardcoded Pinterest board and no hardcoded Flow project UUID remain.
"""

import ast
import re
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # project root, works on any machine
sys.path.insert(0, str(ROOT))

pkg = types.ModuleType("app")
pkg.__path__ = [str(ROOT / "app")]
sys.modules.setdefault("app", pkg)
svc = types.ModuleType("app.services")
svc.__path__ = [str(ROOT / "app" / "services")]
sys.modules.setdefault("app.services", svc)
cfg = types.ModuleType("app.config")


class S:
    storage_path = str(Path(tempfile.gettempdir()) / "pre_verify_store")
    jobs_path = Path(tempfile.gettempdir()) / "pre_verify_jobs"
    outputs_path = Path(tempfile.gettempdir()) / "pre_verify_store" / "outputs"
    generation_backend = "auto"
    generation_variation_count = 4
    default_board_name = "Configured Board"
    flow_project_url = ""


cfg.settings = S()
sys.modules["app.config"] = cfg

fails: list[str] = []


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ── 1. the generation contract ──────────────────────────────────────────
from app.services import generation as g  # noqa: E402

if g.AUTO_ORDER != (g.FLOW_UI, g.FLOW_API):
    # Browser automation must lead. The captured replay depends on a reCAPTCHA
    # Enterprise token that is effectively single-use and an OAuth token good for
    # about an hour, so as the head of the order it spends every run's first
    # attempt on a request that can only be rejected.
    fails.append(f"AUTO_ORDER should be (flow_ui, flow_api), got {g.AUTO_ORDER}")
if g.POLLINATIONS in g.AUTO_ORDER:
    fails.append(
        "pollinations is in AUTO_ORDER — it only receives a condensed prompt, so an "
        "automatic fallback to it silently downgrades the 13-section brief."
    )
if set(g._RUNNERS) != {g.FLOW_API, g.FLOW_UI, g.POLLINATIONS}:
    fails.append(f"_RUNNERS keys drifted from the documented backend ids: {sorted(g._RUNNERS)}")

described = {b["id"] for b in g.describe_backends()}
if described != set(g._RUNNERS):
    fails.append(f"describe_backends() does not cover every runner: {described} vs {set(g._RUNNERS)}")
for b in g.describe_backends():
    if not b.get("detail"):
        fails.append(f"backend {b['id']} reports no `detail`, so the UI cannot say what is missing")

# store_relative: every producer's shape must land on data/outputs/<job>/<name>
cases = {
    "data/outputs/j1/flow_var_1.jpg": "data/outputs/j1/flow_var_1.jpg",
    r"data\outputs\j1\flow_var_1.jpg": "data/outputs/j1/flow_var_1.jpg",
    str(Path(S.storage_path).resolve() / "outputs" / "j1" / "flow_api_2.jpg"): "data/outputs/j1/flow_api_2.jpg",
}
for raw, want in cases.items():
    got = g.store_relative(raw)
    if got != want:
        fails.append(f"store_relative({raw!r}) = {got!r}, expected {want!r}")

# The bug this replaced: a filename must never be re-derived from an index.
if re.search(r"flow_var_\{", read("app/services/output_service.py")):
    fails.append("output_service still re-derives a flow_var_<idx> filename instead of trusting disk")
if re.search(r"flow_var_\{", read("scripts/run_flow_bg.py")):
    fails.append("run_flow_bg still re-derives a flow_var_<idx> filename instead of trusting disk")

# A verified result must reject files that are missing or too small.
kept, rejected = g._verify_produced(["data/outputs/nope/missing.jpg"], "test")
if kept or not rejected:
    fails.append("_verify_produced accepted a path that does not exist on disk")


# ── 2. backends are reached only through generation.py ──────────────────
BACKEND_MODULES = {
    "app.services.flow_direct_api",
    "app.services.flow_automator",
    "app.services.image_gen",
}
ALLOWED_DIRECT = {
    "app/services/generation.py",       # the one dispatcher
    "scripts/verify/verify_generation.py",
}

for path in sorted(list((ROOT / "app").rglob("*.py")) + list((ROOT / "scripts").rglob("*.py"))):
    rel = path.relative_to(ROOT).as_posix()
    if rel in ALLOWED_DIRECT or "/verify/" in rel:
        continue
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        fails.append(f"{rel} does not parse: {e}")
        continue
    for node in ast.walk(tree):
        mod = None
        if isinstance(node, ast.ImportFrom) and node.module:
            mod = node.module
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name in BACKEND_MODULES:
                    mod = a.name
        if mod in BACKEND_MODULES:
            # capture/login helper scripts are allowed to drive a backend directly
            if rel.startswith("scripts/") and ("capture" in rel or "init_" in rel):
                continue
            fails.append(
                f"{rel}:{node.lineno} imports {mod} directly — generation must go through "
                "app.services.generation.generate_variations"
            )


# ── 3. one generation endpoint, aliases that only delegate ─────────────
gen_api = read("app/api/generation.py")
api_tree = ast.parse(gen_api)
routes: dict[str, str] = {}
for node in ast.walk(api_tree):
    if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.args:
                arg = dec.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    routes[f"{dec.func.attr.upper()} {arg.value}"] = node.name

for want in ("POST /{job_id}/generate", "GET /{job_id}/generate/status",
             "POST /{job_id}/generate-flow", "GET /{job_id}/generate-flow/status",
             "POST /{job_id}/generate-auto", "GET /generation/backends"):
    if want not in routes:
        fails.append(f"missing route {want} in app/api/generation.py (have: {sorted(routes)})")

for alias in ("generate_flow_alias", "generate_auto_alias", "generate_flow_status_alias"):
    fn = next((n for n in ast.walk(api_tree)
               if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == alias), None)
    if fn is None:
        fails.append(f"alias {alias} is gone; CreativeLab and older clients still call it")
        continue
    called = {n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    if not called & {"generate_endpoint", "generate_status_endpoint"}:
        fails.append(f"{alias} does not delegate — an alias must not hold its own generation logic")

jobs_api = read("app/api/jobs.py")
for gone in ("/generate-auto", "/generate-flow", "generate_flow_batch", "generate_images_via_direct_flow_api"):
    if gone in jobs_api:
        fails.append(f"app/api/jobs.py still references {gone!r}; generation now lives in app/api/generation.py")

if "generation.router" not in read("app/main.py"):
    fails.append("app/main.py does not register generation.router — /generate would 404")

# The endpoint must not be able to invent a Visual DNA or skip states.
if "no Visual DNA" not in gen_api:
    fails.append("the generate endpoint no longer refuses a job without Visual DNA")
if "validate_transition" not in gen_api:
    fails.append("the generate endpoint no longer validates state transitions")
if "generate_scene" not in gen_api or "compile_prompt" not in gen_api:
    fails.append("the generate endpoint must run the real scene director and the real compiler")


# ── 4. one writer of outputs + pin drafts ──────────────────────────────
# ── 4. one writer of outputs + pin drafts ──────────────────────────────
# Matched on real instantiations (`ast.Call`), not on the substring: the model
# definitions themselves read `class JobOutput(Base)`.
ALLOWED_WRITERS = {"app/services/output_service.py", "app/models/models.py", "app/api/pins.py"}
for path in sorted(list((ROOT / "app").rglob("*.py")) + list((ROOT / "scripts").rglob("*.py"))):
    rel = path.relative_to(ROOT).as_posix()
    if rel in ALLOWED_WRITERS or "/verify/" in rel:
        continue
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        continue  # already reported above
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in ("JobOutput", "PinDraft"):
            fails.append(
                f"{rel}:{node.lineno} constructs {node.func.id} rows directly — recording "
                "belongs to output_service.record_generation_outputs"
            )

runner = read("scripts/run_flow_bg.py")
for need in ("generate_variations", "record_generation_outputs"):
    if need not in runner:
        fails.append(f"scripts/run_flow_bg.py does not use {need}")
if "generate_pin_seo" in runner:
    fails.append("run_flow_bg calls generate_pin_seo itself again — that is output_service's job")
for phase in ('"generating"', '"saving"', '"done"', '"error"'):
    if phase not in runner:
        fails.append(f"run_flow_bg no longer writes status {phase}; the UI polls for it")


# ── 5. no operator-specific values compiled into the source ────────────
BOARD = "Just Random Photography"
for path in sorted(list((ROOT / "app").rglob("*.py")) + list((ROOT / "scripts").rglob("*.py"))):
    rel = path.relative_to(ROOT).as_posix()
    if rel == "app/config.py" or "/verify/" in rel:
        continue
    if BOARD in path.read_text(encoding="utf-8"):
        fails.append(f"{rel} hardcodes the board {BOARD!r}; use settings.default_board_name")

flow_src = read("app/services/flow_automator.py")
if re.search(r"/flow/project/[0-9a-f]{8}-[0-9a-f]{4}", flow_src):
    fails.append("flow_automator still has a hardcoded Flow project UUID; use settings.flow_project_url")
if "settings.flow_project_url" not in flow_src:
    fails.append("flow_automator does not read settings.flow_project_url")
if "settings.default_board_name" not in read("app/services/pinterest_publisher.py"):
    fails.append("pinterest_publisher does not read settings.default_board_name")

# One publisher, reached one way: through a publish run, never inside a request.
#
# `publish_pin_via_browser` and `run_pin_batch` both launch Chromium, so the only
# module allowed to call either is the child process `scripts/publish_bg.py`.
# uvicorn's reloader gives the API a SelectorEventLoop, which cannot spawn
# Playwright's driver — in-request publishing died there with an empty
# NotImplementedError, and both the API and the queue scheduler now start a run
# instead. Calls only: pinterest_service names the publisher in a docstring to
# point callers at it.
launchers = ("publish_pin_via_browser", "run_pin_batch")
for launcher in launchers:
    callers = []
    for path in sorted(list((ROOT / "app").rglob("*.py")) + list((ROOT / "scripts").rglob("*.py"))):
        rel = path.relative_to(ROOT).as_posix()
        if "/verify/" in rel or rel == "app/services/pinterest_publisher.py":
            continue
        if re.search(rf"{launcher}\s*\(", path.read_text(encoding="utf-8")):
            callers.append(rel)
    unexpected = set(callers) - {"scripts/publish_bg.py"}
    if unexpected:
        fails.append(
            f"{launcher} is called from {sorted(unexpected)}; only scripts/publish_bg.py may "
            "launch the browser, because the API's event loop cannot spawn Playwright's driver"
        )
if not re.search(r"run_pin_batch\s*\(", read("scripts/publish_bg.py")):
    fails.append("scripts/publish_bg.py does not call run_pin_batch, so nothing publishes at all")

# …and both callers must reach it through publish_runs.
for starter in ("app/api/pins.py", "app/services/scheduler.py"):
    if "publish_runs.start_run(" not in read(starter):
        fails.append(f"{starter} does not start a publish run; its publishes would never happen")


# ── report ─────────────────────────────────────────────────────────────
if fails:
    print("FAIL — one generation path / one publisher")
    for f in fails:
        print(f"  • {f}")
    sys.exit(1)

print("PASS — generation collapsed to one path")
print(f"  auto order: {' -> '.join(g.AUTO_ORDER)} (pollinations named-only)")
print(f"  routes: {', '.join(sorted(routes))}")
print("  one recorder: output_service.record_generation_outputs")
print("  one publisher: pinterest_publisher.publish_pin_via_browser")
print("  no hardcoded board, no hardcoded Flow project")
