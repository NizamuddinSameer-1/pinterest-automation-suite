"""
Every API client method must be reachable from the UI.

The bug this exists to catch: `api.analyzeReference` was correctly implemented and
`POST /api/references/{id}/analyze` worked, but **no component ever called it**.
Visual DNA is produced only by that call, so the database sat at 0
`reference_analyses` rows and every attempt to generate failed with a 409 that
told the operator to click a button that did not exist.

A dead client method is a feature with no way to reach it. This check is a
ratchet, not a purity test:

  * REQUIRED — methods on the live create → generate → publish path. If one stops
    being called from a component, that path has been broken. Hard failure.
  * KNOWN_UNREACHED — endpoints that exist server-side but are not wired into the
    UI yet. Listed explicitly so the debt is visible and countable. Removing one
    from the UI's reach without listing it here fails; wiring one up and deleting
    it from the list is the intended direction of travel.

Anything unreached and unlisted fails, so new dead methods cannot accumulate.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "frontend" / "src"

# Must be called from at least one component — the wired pipeline path.
REQUIRED = {
    "getReferences",
    "uploadReference",
    "analyzeReference",      # the only producer of Visual DNA
    "getProducts",
    "createJob",
    "getJob",
    "getJobs",
    "compilePrompt",
    "generate",              # the one generation entry point
    "getGenerationBackends",
    "getGenerationStatus",
    "uploadBatch",
    "getPins",
    "publishPin",
    "schedulePin",
}

# Server-side features with no UI affordance yet. Each line is real, known debt.
KNOWN_UNREACHED = {
    "getCampaign": "campaign detail view not built",
    "createCampaign": "campaigns are seeded, not created in the UI",
    "getReference": "reference detail view not built; the list carries has_visual_dna",
    "updateVisualDNA": "manual DNA editing not built",
    "getProduct": "product detail view not built",
    "getFlowSessionStatus": "superseded by getGenerationBackends",
    "generateScene": "the scene director runs inside POST /generate",
    "uploadJobOutputs": "deprecated alias for uploadBatch",
    "runCritique": "PENDING: the realism critique loop has no UI trigger",
    "reworkJob": "PENDING: rework has no UI trigger",
    "createPinDraft": "pin drafts are created by output_service during a run",
    "getScheduledPins": "PENDING: scheduler queue not surfaced",
    "cancelScheduledPin": "PENDING: scheduler queue not surfaced",
    "getSchedulerStatus": "PENDING: scheduler status not surfaced",
    "runSchedulerNow": "PENDING: scheduler status not surfaced",
    "approvePin": "PENDING: approve/reject not wired in Pin Composer",
    "rejectPin": "PENDING: approve/reject not wired in Pin Composer",
}

api_src = (SRC / "api.ts").read_text(encoding="utf-8")
declared = re.findall(r"^  ([a-zA-Z][A-Za-z0-9_]*): async", api_src, re.M)

callers = "\n".join(
    p.read_text(encoding="utf-8") for p in sorted(SRC.rglob("*.ts*")) if p.name != "api.ts"
)

fails: list[str] = []

unknown_required = REQUIRED - set(declared)
if unknown_required:
    fails.append(
        f"REQUIRED names not declared in api.ts (renamed or deleted?): {sorted(unknown_required)}"
    )

unreached = [n for n in declared if not re.search(rf"\bapi\.{n}\b", callers)]

for name in unreached:
    if name in REQUIRED:
        fails.append(
            f"api.{name} is on the live pipeline path but no component calls it — "
            "the feature is unreachable from the UI"
        )
    elif name not in KNOWN_UNREACHED:
        fails.append(
            f"api.{name} is declared but never called. Either wire it into a component or "
            "add it to KNOWN_UNREACHED with the reason, so dead client code stays counted."
        )

stale = [n for n in KNOWN_UNREACHED if n in declared and n not in unreached]
for name in stale:
    fails.append(
        f"api.{name} is listed in KNOWN_UNREACHED but IS now called — delete its entry "
        "so the list keeps reflecting real debt."
    )

if fails:
    print("FAIL — API client reachability")
    for f in fails:
        print(f"  • {f}")
    sys.exit(1)

pending = sorted(n for n in unreached if KNOWN_UNREACHED.get(n, "").startswith("PENDING"))
print("PASS — API client reachability")
print(f"  {len(declared)} methods declared, {len(declared) - len(unreached)} reached from components")
print(f"  {len(REQUIRED)} pipeline-critical methods all reachable")
print(f"  {len(pending)} endpoint(s) still awaiting a UI trigger:")
for name in pending:
    print(f"    - {name}: {KNOWN_UNREACHED[name]}")
