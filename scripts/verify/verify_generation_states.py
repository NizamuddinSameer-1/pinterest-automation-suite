"""
Offline dry run of the unified generation endpoint's decision-making.

`fastapi`, `sqlalchemy` and `playwright` are not installed in the check
environment, so the endpoint module cannot be imported. Its two decisions that
matter — which states may start a run, and where a run leaves the job — are
reimplemented here *from the same source* by exec'ing only the state helpers out
of `app/api/generation.py`. If those helpers change, this check changes with
them; if the state machine changes, it fails.

Covers: the happy path, a retry after FAILED, a rework loop, a job that already
has outputs, and WAITING_FOR_FLOW.
"""

import ast
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

pkg = types.ModuleType("app")
pkg.__path__ = [str(ROOT / "app")]
sys.modules.setdefault("app", pkg)
cfg = types.ModuleType("app.config")


class S:
    jobs_path = Path(tempfile.gettempdir()) / "pre_verify_jobs"
    storage_path = str(Path(tempfile.gettempdir()) / "pre_verify_store")


cfg.settings = S()
sys.modules["app.config"] = cfg

from app.services.job_service import InvalidTransitionError, validate_transition  # noqa: E402

# Lift the state helpers straight out of the endpoint module so this test can
# never drift from the code it is checking.
src = (ROOT / "app" / "api" / "generation.py").read_text(encoding="utf-8")
tree = ast.parse(src)
wanted = {"_FORWARD_CHAIN", "_advance_job_state", "_rewind_for_retry"}
picked: list[ast.stmt] = []
for node in tree.body:
    if isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id in wanted for t in node.targets
    ):
        picked.append(node)
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted:
        picked.append(node)

ns: dict = {"validate_transition": validate_transition, "InvalidTransitionError": InvalidTransitionError, "Job": object}
exec(compile(ast.Module(body=picked, type_ignores=[]), "<generation-helpers>", "exec"), ns)

if len(picked) != 3:
    print(f"FAIL — expected to lift 3 helpers from app/api/generation.py, got {len(picked)}")
    sys.exit(1)

_advance = ns["_advance_job_state"]
_rewind = ns["_rewind_for_retry"]

fails: list[str] = []


class FakeJob:
    def __init__(self, state: str) -> None:
        self.current_state = state
        self.failure_reason = "an old error"


def start_run(state: str) -> tuple[str, str | None]:
    """
    Mirror `generate_endpoint`'s state handling. Returns (final_state, refusal).

    `_prepare_brief` is represented by its two hops (SCENE_READY, PROMPT_READY),
    with the SCENE_READY hop tolerated when the job is already past it.
    """
    job = FakeJob(state)
    if job.current_state == "WAITING_FOR_FLOW":
        return job.current_state, "waiting for a manual Flow upload"
    _rewind(job)
    try:
        _advance(job, "SCENE_READY")
    except InvalidTransitionError:
        pass  # already past SCENE_READY (a rework, for instance)
    try:
        _advance(job, "PROMPT_READY")
    except InvalidTransitionError as e:
        return job.current_state, str(e)
    try:
        _advance(job, "GENERATING")
    except InvalidTransitionError as e:
        return job.current_state, str(e)
    return job.current_state, None


CASES = [
    # (starting state, must reach GENERATING?, note)
    ("DRAFT", True, "a brand-new job walks the whole chain"),
    ("ANALYZED", True, "reference analysed"),
    ("PRODUCT_MATCHED", True, "product matched"),
    ("SCENE_READY", True, "scene already directed"),
    ("PROMPT_READY", True, "prompt already compiled"),
    ("REWORK", True, "rework returns to PROMPT_READY, then generates"),
    ("FAILED", True, "a failed run may be retried"),
    ("OUTPUT_UPLOADED", False, "already has outputs — critique + rework first"),
    ("CRITIQUED", False, "already critiqued — rework first"),
    ("PASS", False, "passed the critic — regenerating would erase that verdict"),
    ("WAITING_FOR_FLOW", False, "operator is generating by hand"),
]

for state, should_run, note in CASES:
    final, refusal = start_run(state)
    ran = refusal is None
    if ran != should_run:
        fails.append(
            f"{state}: expected {'a run' if should_run else 'a refusal'} ({note}), "
            f"got {'a run' if ran else f'refusal: {refusal}'}"
        )
        continue
    if ran and final != "GENERATING":
        fails.append(f"{state}: run started but job left in {final}, not GENERATING")

# A retry must clear the stale failure reason, or the UI shows an old error
# beside a live run.
retried = FakeJob("FAILED")
_rewind(retried)
if retried.current_state != "DRAFT":
    fails.append(f"FAILED retry should rewind to DRAFT, got {retried.current_state}")
if retried.failure_reason is not None:
    fails.append("FAILED retry left the old failure_reason attached to a job that is running again")

# Every hop the chain takes must be legal in the real state machine.
chain = ns["_FORWARD_CHAIN"]
for a, b in zip(chain, chain[1:]):
    try:
        validate_transition(a, b)
    except InvalidTransitionError as e:
        fails.append(f"_FORWARD_CHAIN hop {a} -> {b} is not legal: {e}")

if fails:
    print("FAIL — generation endpoint state handling")
    for f in fails:
        print(f"  • {f}")
    sys.exit(1)

print("PASS — generation endpoint state handling")
print(f"  chain: {' -> '.join(chain)}")
starts = [s for s, ok, _ in CASES if ok]
refuses = [s for s, ok, _ in CASES if not ok]
print(f"  starts a run from: {', '.join(starts)}")
print(f"  refuses (with a reason): {', '.join(refuses)}")
