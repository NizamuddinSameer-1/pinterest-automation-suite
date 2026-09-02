"""Offline verification of the repaired job state machine + vault sync neutrality."""
import sys, types, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # project root, works on any machine
sys.path.insert(0, str(ROOT))

pkg = types.ModuleType("app"); pkg.__path__ = [str(ROOT / "app")]
sys.modules.setdefault("app", pkg)
cfg = types.ModuleType("app.config")
class S:
    jobs_path = Path(tempfile.gettempdir()) / "pre_verify_jobs"; storage_path = Path(tempfile.gettempdir()) / "pre_verify_store"
cfg.settings = S()
sys.modules["app.config"] = cfg

from app.services.job_service import (
    TRANSITIONS, ALL_STATES, validate_transition, InvalidTransitionError,
    can_compile_prompt, can_upload_outputs, can_run_critique,
)

fails = []

# ── 1. The happy path a real job must be able to walk, end to end.
HAPPY = ["DRAFT", "ANALYZED", "PRODUCT_MATCHED", "SCENE_READY", "PROMPT_READY",
         "GENERATING", "OUTPUT_UPLOADED", "CRITIQUED", "PASS", "PIN_DRAFT",
         "APPROVED", "EXPORTED"]
for a, b in zip(HAPPY, HAPPY[1:]):
    try:
        validate_transition(a, b)
    except InvalidTransitionError as e:
        fails.append(f"happy path blocked: {a} -> {b}")
print("happy path:", " -> ".join(HAPPY))

# ── 2. The rework loop must close.
LOOP = ["OUTPUT_UPLOADED", "CRITIQUED", "REWORK", "PROMPT_READY", "GENERATING", "OUTPUT_UPLOADED"]
for a, b in zip(LOOP, LOOP[1:]):
    try:
        validate_transition(a, b)
    except InvalidTransitionError:
        fails.append(f"rework loop blocked: {a} -> {b}")
print("rework loop:", " -> ".join(LOOP))

# ── 3. The old illegal shortcut must stay illegal.
for a, b in [("OUTPUT_UPLOADED", "PASS"), ("OUTPUT_UPLOADED", "REWORK"),
             ("GENERATING", "PASS"), ("PASS", "PROMPT_READY")]:
    try:
        validate_transition(a, b)
        fails.append(f"illegal shortcut still allowed: {a} -> {b}")
    except InvalidTransitionError:
        pass

# ── 4. Every target named anywhere must be a real state (no typos, no orphans).
for src, targets in TRANSITIONS.items():
    for t in targets:
        if t not in ALL_STATES:
            fails.append(f"{src} points at unknown state {t}")

# ── 5. Every state must be reachable from DRAFT (except DRAFT itself).
seen, stack = {"DRAFT"}, ["DRAFT"]
while stack:
    for t in TRANSITIONS[stack.pop()]:
        if t not in seen:
            seen.add(t); stack.append(t)
unreachable = ALL_STATES - seen
if unreachable:
    fails.append(f"unreachable states: {sorted(unreachable)}")

# ── 6. Guard helpers must agree with the transition table.
if not can_upload_outputs("GENERATING"):
    fails.append("can_upload_outputs rejects GENERATING (the Flow subprocess state)")
if not can_run_critique("OUTPUT_UPLOADED"):
    fails.append("can_run_critique rejects OUTPUT_UPLOADED")
if can_run_critique("GENERATING"):
    fails.append("can_run_critique accepts GENERATING")
for st in ("SCENE_READY", "REWORK"):
    if not can_compile_prompt(st) or "PROMPT_READY" not in TRANSITIONS[st]:
        fails.append(f"can_compile_prompt({st}) disagrees with TRANSITIONS")

# ── 7. FAILED must be reachable from every non-terminal state (nothing gets stuck).
TERMINAL = {"REJECTED", "EXPORTED", "FAILED", "APPROVED"}
for st in ALL_STATES - TERMINAL:
    if "FAILED" not in TRANSITIONS[st]:
        fails.append(f"{st} cannot fail — a stuck job there is unrecoverable")

# ── 8. vault_sync must no longer hardcode the seasonal campaign.
import app.services.vault_sync as vs
vs.VAULT_PATH = Path(tempfile.mkdtemp()) / "vault"
print("campaign links:", vs._campaign_link(), "|",
      vs._campaign_link(None, "coastal summer"), "|",
      vs._campaign_link("Spring Basics 2027", "ignored"))
if vs._campaign_link() != "[[Campaign - Unassigned]]":
    fails.append("no-campaign fallback is not neutral")

p = vs.sync_pin_node(
    pin_id="pin_test_0001", job_id="job_test", title="A Linen Dress Worth Rewearing",
    description="Real daylight, no studio.", keywords=["linen dress"],
    destination_url="https://example.com/x", board_name="Everyday Outfits",
    status="draft", product_name="Linen Wrap Dress",
)
text = p.read_text(encoding="utf-8")
for bad in ("Halloween", "🎃"):
    if bad in text:
        fails.append(f"pin node still contains {bad!r}")
if "[x] **Product Truth Verified" in text or "100% matched" in text:
    fails.append("pin node still pre-ticks unverified compliance claims")
if "[[Campaign - Unassigned]]" not in text:
    fails.append("pin node lost its campaign link")

ref = vs.sync_reference_node(
    reference_id="ref_test", trend_label="coastal summer", category="fashion",
    image_path="data/products/x.jpg", analysis=None, visual_dna=None,
)
if "Halloween" in ref.read_text(encoding="utf-8"):
    fails.append("reference node still defaults to Halloween campaign")
if "[[Campaign - coastal summer]]" not in ref.read_text(encoding="utf-8"):
    fails.append("reference node did not derive its campaign from the trend")

print("\nFAILURES:", fails if fails else "none")
