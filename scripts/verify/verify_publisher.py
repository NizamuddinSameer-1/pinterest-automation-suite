"""
Offline verification of bulk scheduling: the planner by execution, the publisher
by reading its source.

`schedule_planner` is pure stdlib, so it is imported and run for real — both
spacing modes, the refusals, and the notes. The publisher cannot be imported here
(no Playwright in this VM), so its guarantees are asserted against the source:

  1. the planner's arithmetic and every refusal it owes the operator;
  2. no "first available board" fallback survives, and the board comes from
     settings.default_board_name;
  3. every typed field is read back, and fields are blurred with Tab, never Enter;
  4. a schedule that cannot be set never falls through into publishing now;
  5. `pinterest_scheduled` is excluded from PRE's own due-pin sweep, so a pin
     Pinterest holds is never published a second time;
  6. the bulk endpoints exist, plan through `schedule_planner`, and record only
     what the publisher confirmed;
  7. the UI reaches both endpoints and shows the natively-scheduled state.
"""

import re
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# This VM has no PyPI packages, so the two things `pinterest_service` imports at
# module scope are stubbed. Nothing under test calls either: `httpx` is only used
# by the API-token path, and only `default_board_name` is read from settings.
if "httpx" not in sys.modules:
    sys.modules["httpx"] = types.ModuleType("httpx")
    sys.modules["httpx"].AsyncClient = object          # type: ignore[attr-defined]
    sys.modules["httpx"].HTTPStatusError = Exception   # type: ignore[attr-defined]

if "app.config" not in sys.modules:
    cfg = types.ModuleType("app.config")

    class _Settings:
        storage_path = str(Path(tempfile.gettempdir()) / "pre_verify_store")
        default_board_name = "Configured Board"
        pinterest_access_token = ""

    cfg.settings = _Settings()      # type: ignore[attr-defined]
    sys.modules["app.config"] = cfg

fails: list[str] = []
notes: list[str] = []


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def code_only(src: str) -> str:
    """Source with comments and docstrings stripped, for negative checks.

    Without this, a comment explaining that the "first available board" fallback
    was removed would itself trip the check that looks for it.
    """
    src = re.sub(r'"""(?:.|\n)*?"""', "", src)
    src = re.sub(r"'''(?:.|\n)*?'''", "", src)
    return "\n".join(re.sub(r"#.*$", "", line) for line in src.splitlines())


def want(condition: bool, message: str) -> None:
    if not condition:
        fails.append(message)


# ── 1. the planner, executed ────────────────────────────────────────────
from app.services.schedule_planner import (  # noqa: E402
    HORIZON_DAYS,
    MIN_LEAD_MINUTES,
    PlanError,
    parse_daily_slots,
    plan_publish_times,
)

NOW = datetime(2026, 8, 22, 6, 0, tzinfo=timezone.utc)
START = NOW + timedelta(hours=1)

# mode 1 — interval
plan = plan_publish_times(5, START, interval_minutes=90, now=NOW)
want(len(plan.times) == 5, f"interval mode produced {len(plan.times)} times, expected 5")
gaps = {(b - a).total_seconds() / 60 for a, b in zip(plan.times, plan.times[1:])}
want(gaps == {90.0}, f"interval spacing drifted: {sorted(gaps)}")
want(plan.times[0] == START, f"the first pin should be at the start time, got {plan.times[0]}")
want(all(t.tzinfo is not None for t in plan.times), "planned times must be timezone-aware")

# mode 1 with a per-day cap — the cap must roll the batch onto later days
capped = plan_publish_times(7, START, interval_minutes=60, per_day_cap=3, now=NOW)
want(len(capped.times) == 7, f"capped interval mode produced {len(capped.times)}, expected 7")
spans = {t.astimezone().strftime("%Y-%m-%d") for t in capped.times}
want(len(spans) >= 3, f"a cap of 3 over 7 pins must use at least 3 days, used {sorted(spans)}")
want(
    max(capped.per_day().values()) <= 3,
    f"per-day cap of 3 was exceeded: {capped.per_day()}",
)

# mode 2 — fixed daily slots
slotted = plan_publish_times(7, START, daily_slots=["09:00", "13:00", "20:00"], now=NOW)
want(len(slotted.times) == 7, f"slot mode produced {len(slotted.times)}, expected 7")
minutes_of_day = {t.astimezone().strftime("%H:%M") for t in slotted.times}
want(
    minutes_of_day <= {"09:00", "13:00", "20:00"},
    f"slot mode invented times of day: {sorted(minutes_of_day)}",
)
want(
    list(slotted.times) == sorted(slotted.times),
    "planned times came back out of order; the publisher types them in sequence",
)

# slots win over an interval, and say so
both = plan_publish_times(3, START, interval_minutes=45, daily_slots=["10:00", "18:00"], now=NOW)
want(
    any("slots are used" in n for n in both.notes),
    f"giving both a slot list and an interval must be reported, notes={both.notes}",
)

# parse_daily_slots reads the formats a human types, and refuses the rest
want(
    parse_daily_slots(["09:00", "0930", "8:30 PM"]) == parse_daily_slots(["09:00", "09:30", "20:30"]),
    "parse_daily_slots does not accept 0930 / 8:30 PM as the same times as 09:30 / 20:30",
)
for bad in (["not a time"], ["25:00"], ["9pm-ish"]):
    try:
        parse_daily_slots(bad)
        fails.append(f"parse_daily_slots({bad!r}) was accepted; an unreadable slot must raise")
    except PlanError:
        pass

# the refusals — each is a way the old code could have published at a wrong time
REFUSALS = {
    "count of zero": dict(count=0, start=START, interval_minutes=60),
    "naive start": dict(count=2, start=START.replace(tzinfo=None), interval_minutes=60),
    "no spacing at all": dict(count=2, start=START),
    "per-day cap of zero": dict(count=2, start=START, interval_minutes=60, per_day_cap=0),
    "a start in the past": dict(count=2, start=NOW - timedelta(hours=5), interval_minutes=60),
    "a start inside the lead time": dict(
        count=2, start=NOW + timedelta(minutes=MIN_LEAD_MINUTES - 5), interval_minutes=60
    ),
    "more pins than the horizon holds": dict(
        count=40, start=START, daily_slots=["09:00"], now=NOW, horizon_days=5
    ),
}
for label, kwargs in REFUSALS.items():
    kwargs.setdefault("now", NOW)
    count = kwargs.pop("count")
    start = kwargs.pop("start")
    try:
        plan_publish_times(count, start, **kwargs)
        fails.append(f"plan_publish_times accepted {label}; it must raise PlanError instead")
    except PlanError:
        pass
    except Exception as e:  # a TypeError here would still reach the operator as a 500
        fails.append(f"plan_publish_times({label}) raised {type(e).__name__}, expected PlanError: {e}")

# nothing may be planned beyond Pinterest's own ceiling
far = plan_publish_times(20, START, daily_slots=["09:00", "18:00"], now=NOW)
want(
    max(far.times) <= NOW + timedelta(days=HORIZON_DAYS),
    "a plan reached past the 30-day horizon Pinterest's date picker greys out",
)

# a heavy day is flagged rather than silently accepted
heavy = plan_publish_times(30, START, interval_minutes=20, now=NOW)
want(
    any("one day is heavy" in n for n in heavy.notes),
    f"30 pins in one day should carry a warning note, notes={heavy.notes}",
)


# ── 2. the publisher's guarantees, read from source ─────────────────────
pub = read("app/services/pinterest_publisher.py")
pub_code = code_only(pub)

want(
    "settings.default_board_name" in pub_code,
    "pinterest_publisher no longer reads settings.default_board_name",
)
for fallback in ("first_board", "boards[0]", "options.first", "first available board"):
    want(
        fallback not in pub_code,
        f"pinterest_publisher contains {fallback!r} — a board fallback publishes pins to the "
        "wrong board, which is what it did before",
    )
want(
    "_read_back" in pub_code and "_normalise_for_compare" in pub_code,
    "the read-back verification of typed fields is gone; a silently-empty description is "
    "exactly the failure that produced seven invisible drafts",
)
want(
    'keyboard.press("Tab")' in pub_code,
    "fields are no longer blurred with Tab",
)
want(
    'keyboard.press("Enter")' not in pub_code,
    "something presses Enter inside the builder — Enter submits the pin, so a half-filled "
    "pin would be published",
)
want("insert_text" in pub_code, "the publisher no longer types through browser_utils.insert_text")

for err in ("PinterestLoginRequired", "BuilderNotReady", "FieldNotAccepted",
            "BoardNotFound", "ScheduleNotAccepted", "NotConfirmed"):
    want(err in pub_code, f"typed error {err} is gone; failures would be indistinguishable")

# 2b. the board picker must be waited for, not sampled once.
#
# The Aug-23 01:04 run typed the board name ~2 s after opening the dropdown, read
# the rows once, found none because they had not arrived, and reported "Boards
# offered: (none readable)" — i.e. it blamed the account for a slow page. Both the
# waiting and the distinction between the two failures are ratcheted here.
board_fn = pub[pub.find("async def choose_board"):pub.find("# ── Pinterest's own scheduler")]
want(bool(board_fn), "choose_board is gone from the publisher")
want(
    "_wait_for_board_names" in board_fn,
    "choose_board does not wait for the board list; an empty dropdown that is merely "
    "still loading would again be reported as a missing board",
)
# Scoped to after the menu is opened: the earlier BoardNotFound ("no board dropdown
# at all") is a different, legitimate claim that needs no list.
opened = board_fn[board_fn.find("await button.click()"):]
want(
    0 <= opened.find("_wait_for_board_names") < opened.find("is not in this account's dropdown"),
    "choose_board can claim a board is missing before it has waited for the list",
)
want(
    "BoardListUnreadable" in pub_code
    and '(BoardListUnreadable, "board_list_unreadable")' in pub_code,
    "a board list that never renders is not distinguished from a board that does not "
    "exist (or its error_kind is not mapped), so the operator is told to fix Pinterest "
    "when the page was the problem",
)
want(
    "await self._board_names_unfiltered(" in opened,
    "the board search filter is not cleared before listing the available boards, so the "
    "failure message lists the boards that matched the name that just failed: none",
)
want(
    '.split("  ")' not in pub_code,
    'a board name is still split on a double space, which _squash has already collapsed — '
    'every reported name would carry its "12 pins" suffix',
)
want(
    "_board_row_name" in pub_code,
    "board row text is no longer reduced to a board name",
)

sch = read("app/services/scheduler.py")
want(
    '"board_not_found"' in sch and "hopeless" in sch,
    "the queue scheduler still retries a board_not_found on every 30-second tick; each "
    "retry opens Chromium and abandons another Pinterest draft",
)

# The central rule: if the time cannot be set, the pin must NOT be published now.
sched_fn = pub[pub.find("async def set_native_schedule"):pub.find("async def submit")]
want(bool(sched_fn), "set_native_schedule is gone from the publisher")
want(
    "ScheduleNotAccepted" in sched_fn,
    "set_native_schedule no longer raises ScheduleNotAccepted; a failed schedule that "
    "returns normally becomes an immediate publish",
)
want(
    "NOT published now" in sched_fn or "not published now" in sched_fn.lower(),
    "the schedule failure no longer tells the operator the pin was left as a draft rather "
    "than published",
)
process = pub[pub.find("async def _process_one"):pub.find("async def _launch_context")]
want(
    process.find("set_native_schedule") < process.find("await builder.submit()"),
    "_process_one submits before setting the schedule, so a scheduling failure would publish",
)
want(
    "try" not in code_only(process),
    "_process_one swallows an exception; a step that fails must propagate so the pin is "
    "reported failed instead of assumed scheduled",
)

# One browser for the batch, and progress persisted as it goes. The loop lives in
# `_run_pin_batch_impl`; `run_pin_batch` is the guard in front of it.
batch = pub[pub.find("async def _run_pin_batch_impl"):pub.find("async def run_pin_batch")]
want(bool(batch), "_run_pin_batch_impl is gone; bulk scheduling would open a browser per pin")
want(
    batch.count("_launch_context") == 1 and "for " in batch,
    "the batch loop no longer runs inside a single launched context",
)
want("on_result" in batch, "the batch loop no longer reports each pin as it finishes")
want(
    "login_required" in batch,
    "the batch loop no longer marks the remaining pins login_required after a login failure",
)

# The browser must never be launched inside the API's event loop again: uvicorn's
# reloader installs a SelectorEventLoop, which cannot spawn Playwright's driver,
# and the resulting NotImplementedError stringifies to '' — the empty
# "Direct browser publish failed:" the operator saw.
guard = pub[pub.find("def _refuse_unless_proactor"):pub.find("async def _run_pin_batch_impl")]
want(bool(guard), "_refuse_unless_proactor is gone; a browser launched on the wrong loop fails mutely")
want(
    "ProactorEventLoop" in guard and "WrongEventLoop" in guard,
    "_refuse_unless_proactor no longer checks for a ProactorEventLoop",
)
wrapper = pub[pub.find("async def run_pin_batch"):pub.find("async def publish_pin_via_browser")]
want(
    "_refuse_unless_proactor()" in wrapper,
    "run_pin_batch no longer refuses the wrong event loop before launching Chromium",
)
want(
    "_run_in_proactor" not in pub_code,
    "_run_in_proactor is back: running the batch in a worker thread did not fix the loop and "
    "silently dropped on_result, so a batch that failed halfway recorded nothing",
)
want(
    "on_result=None" not in pub_code,
    "something passes on_result=None into the batch; per-pin progress and recording would be lost",
)


# ── 3. Pinterest-held pins are never published again by PRE ────────────
svc = read("app/services/pinterest_service.py")
svc_code = code_only(svc)
want('STATUS_PINTEREST_SCHEDULED = "pinterest_scheduled"' in svc_code,
     "STATUS_PINTEREST_SCHEDULED is gone from pinterest_service")
want("record_pinterest_native_schedule" in svc_code,
     "record_pinterest_native_schedule is gone; natively-scheduled pins would be invisible")

due = svc[svc.find("def get_due_pins"):svc.find("def claim_pin_for_publishing")]
want(bool(due), "get_due_pins is gone from pinterest_service")
want(
    "STATUS_PINTEREST_SCHEDULED" not in code_only(due),
    "get_due_pins considers STATUS_PINTEREST_SCHEDULED — PRE would publish a pin Pinterest "
    "is already holding, and the operator gets two identical pins",
)

native = svc[svc.find("def record_pinterest_native_schedule"):svc.find("def get_scheduled_pins")]
want("confirmed_by" in native,
     "record_pinterest_native_schedule no longer records what confirmed the schedule")
want(
    "STATUS_CANCELLED" in native,
    "record_pinterest_native_schedule no longer cancels the earlier local queue entry, so "
    "PRE's own scheduler would publish a duplicate at its own queued time",
)

# Verify by execution that the sweep ignores the native status.
import app.services.pinterest_service as ps  # noqa: E402

sample = [
    {"id": "a", "status": ps.STATUS_SCHEDULED, "scheduled_time": (NOW - timedelta(hours=1)).isoformat()},
    {"id": "b", "status": ps.STATUS_PINTEREST_SCHEDULED, "scheduled_time": (NOW - timedelta(hours=1)).isoformat()},
    {"id": "c", "status": ps.STATUS_PUBLISHED, "scheduled_time": (NOW - timedelta(hours=1)).isoformat()},
]
original = ps._get_queue
ps._get_queue = lambda: sample  # type: ignore[assignment]
try:
    ids = [e["id"] for e in ps.get_due_pins(now=NOW)]
finally:
    ps._get_queue = original  # type: ignore[assignment]
want(ids == ["a"], f"get_due_pins returned {ids}; only the locally-queued entry 'a' is due")


# ── 4. the bulk endpoints ──────────────────────────────────────────────
pins_api = read("app/api/pins.py")
pins_code = code_only(pins_api)

for route in ('@router.post("/bulk-schedule/preview")', '@router.post("/bulk-schedule")'):
    want(route in pins_code, f"missing bulk route {route} in app/api/pins.py")
want("plan_publish_times" in pins_code,
     "the bulk endpoints no longer plan through schedule_planner")
want("record_pinterest_native_schedule" in pins_code,
     "the bulk endpoint no longer records Pinterest-held pins in the queue")
want('"scheduled_pinterest"' in pins_code,
     "the bulk endpoint no longer marks pins scheduled_pinterest, so they would look like drafts")
want("resolve_output_image" in pins_api.split("def ")[0] or
     re.search(r"^from app\.services\.media_paths import .*resolve_output_image", pins_api, re.M),
     "resolve_output_image is not imported at module scope in app/api/pins.py (it was used "
     "without an import, which raised NameError at request time)")

# No Playwright inside a request, ever. This is the whole fix for the empty
# "Direct browser publish failed:" 500: the API starts a child process and polls.
for browser_call in ("run_pin_batch", "publish_pin_via_browser", "async_playwright"):
    want(
        browser_call not in pins_code,
        f"app/api/pins.py references {browser_call} — the browser must not run in the API "
        "process, whose loop (uvicorn --reload) cannot spawn Playwright's driver",
    )
want("publish_runs.start_run" in pins_code,
     "app/api/pins.py no longer starts publish runs through app.services.publish_runs")
want('@router.get("/publish-runs/{run_id}")' in pins_code,
     "the run-polling route is gone; the UI would have no way to learn a run's outcome")

preview = pins_api[pins_api.find('@router.post("/bulk-schedule/preview")'):
                   pins_api.find('@router.post("/bulk-schedule")')]
want(
    "start_run" not in code_only(preview),
    "the preview endpoint starts a run; previewing must not send anything to Pinterest",
)
want("skipped" in preview and "notes" in preview,
     "the preview no longer reports skipped pins and planner notes")

bulk = pins_api[pins_api.find('@router.post("/bulk-schedule")'):
                pins_api.find('@router.post("/{pin_id}/dispatch-n8n")')]
want(bool(bulk), "the bulk-schedule endpoint body could not be located")
want(
    "KIND_BULK_SCHEDULE" in bulk and "run_id" in bulk,
    "the bulk endpoint no longer starts a background run and returns its id",
)
want(
    '"scheduled": 0' in bulk,
    "the bulk endpoint reports a scheduled count from the start of the run; only the run "
    "itself knows what Pinterest accepted",
)
want("PlanError" in pins_code, "a PlanError from the planner is no longer turned into a 409")

# The database is written from the run's results, and only where the publisher
# proved something. This is where "fabricated success" would come back.
apply_fn = pins_api[pins_api.find("async def _apply_run"):pins_api.find("def _record_native_schedule")]
want(bool(apply_fn), "_apply_run is gone; a finished run would never reach the database")
want(
    'result.get("confirmed_by")' in apply_fn,
    "_apply_run marks a pin published without a confirmation from the publisher",
)
want(
    'result.get("scheduled_for")' in apply_fn,
    "_apply_run marks a pin scheduled_pinterest without a confirmed time",
)
want("mark_applied" in apply_fn, "_apply_run does not mark the run applied; effects would repeat")
want(
    "_reconcile_runs" in pins_code and pins_code.count("await _reconcile_runs(db)") >= 1,
    "nothing reconciles finished runs, so a publish whose tab was closed would never be saved",
)

# ── 4b. the background-run contract ────────────────────────────────────
runs_src = code_only(read("app/services/publish_runs.py"))
want("scripts.publish_bg" in runs_src,
     "publish_runs no longer spawns scripts.publish_bg; the browser would have no process")
want("subprocess.Popen" in runs_src, "publish_runs no longer starts a child process")
want("os.replace" in runs_src,
     "status.json is no longer written atomically; a half-written file reads as a crashed run")
want("def is_stalled" in runs_src,
     "is_stalled is gone; a killed child would leave a run 'running' for ever")
want("def prune_old_runs" in runs_src,
     "run retention is gone; every list request reconciles by reading each status.json, so the "
     "run directory must not grow without bound")
want("def wait_for_run" in runs_src,
     "wait_for_run is gone; PRE's own queue scheduler has no way to await its own publish")

bg = read("scripts/publish_bg.py")
bg_code = code_only(bg)
want("WindowsProactorEventLoopPolicy" in bg_code,
     "scripts/publish_bg.py does not set the Proactor policy; Playwright cannot spawn its driver")
want(
    bg_code.find("WindowsProactorEventLoopPolicy") < bg_code.find("run_pin_batch"),
    "publish_bg imports the publisher before setting the event-loop policy; the policy must be "
    "set first or the loop is already wrong",
)
want("write_status" in bg_code and "on_result" in bg_code,
     "publish_bg no longer writes progress after each pin, so a long run is opaque")
want(
    "type(e).__name__" in bg_code,
    "publish_bg records only str(e); NotImplementedError stringifies to '' and the operator "
    "saw a failure with no reason at all",
)
for db_word in ("AsyncSession", "get_db", "PinDraft"):
    want(
        db_word not in bg_code,
        f"scripts/publish_bg.py touches the database ({db_word}); every SQLite write belongs to "
        "the API process, which applies a finished run exactly once",
    )


# PRE's own queue scheduler runs inside the API process, so it must go through a
# run too — in-process it hit the same SelectorEventLoop and every scheduled
# publish failed with an empty reason, on a 30-second tick.
sched_src = code_only(read("app/services/scheduler.py"))
want("publish_runs.start_run" in sched_src,
     "the queue scheduler still launches the browser in the API process; on Windows that raises "
     "a bare NotImplementedError and the queue entry is marked failed with no reason")
want("wait_for_run" in sched_src, "the queue scheduler does not wait for its run to finish")
want("publish_pin_via_browser" not in sched_src,
     "the queue scheduler calls publish_pin_via_browser directly again")
want('result.get("confirmed_by")' in sched_src or "confirmed_by = result.get" in sched_src,
     "the queue scheduler no longer requires a confirmation before marking an entry published")
want("mark_applied" in sched_src,
     "the queue scheduler does not mark its run applied, so the API would write the same pin twice")
want("retryable=False" in sched_src,
     "a stalled run is still retried by the 30-second tick; the browser may already have created "
     "the pin, so a retry posts a duplicate")

# ── 5. the UI reaches it, and shows the new state ──────────────────────
apits = read("frontend/src/api.ts")
want("previewBulkSchedule" in apits and "/pins/bulk-schedule/preview" in apits,
     "api.ts cannot reach the bulk preview endpoint")
want("bulkSchedulePins" in apits and "/pins/bulk-schedule" in apits,
     "api.ts cannot reach the bulk schedule endpoint")
for method in ("previewBulkSchedule", "bulkSchedulePins", "publishPin", "getPublishRun"):
    block = apits[apits.find(f"{method}: async"):]
    # Up to the method's own closing brace (two-space indent) — not the first
    # `},` in the body, which belongs to the headers object.
    block = block[:block.find("\n  },")]
    want("apiFetch(" in block or "if (!res.ok)" in block,
         f"api.{method} returns res.json() without checking res.ok, so a 409 would read as success")

# A network failure and a publisher failure are different things. Reported raw,
# the browser's "Failed to fetch" read as "the publisher broke" when the real
# answer was that nothing was listening on port 8000.
fetch_wrapper = apits[apits.find("async function apiFetch"):]
fetch_wrapper = fetch_wrapper[:fetch_wrapper.find("\n}\n")]
want(bool(fetch_wrapper), "api.ts has no apiFetch wrapper")
want(
    "run.py" in fetch_wrapper,
    "the network-error path no longer names the real cause (run.py not listening); the operator "
    "gets 'Failed to fetch' next to the word publish and blames the publisher",
)
want("getPublishRun" in apits and "/pins/publish-runs/" in apits,
     "api.ts cannot poll a publish run, so the outcome of a publish is unreachable")

composer = read("frontend/src/components/PinComposer.tsx")
want("api.previewBulkSchedule" in composer and "api.bulkSchedulePins" in composer,
     "PinComposer does not call the bulk methods; the feature would be unreachable")
want(
    "'scheduled_pinterest'" in composer,
    "PinComposer does not know the scheduled_pinterest status, so Pinterest-held pins would "
    "sit in Active Drafts and invite a duplicate publish",
)
want(
    re.search(r"SCHEDULED_STATES\s*=\s*\[[^\]]*scheduled_pinterest", composer) is not None,
    "scheduled_pinterest is missing from SCHEDULED_STATES",
)
want("error_kind" in composer,
     "PinComposer does not show error_kind, so a failed pin gives the operator no reason")
want(
    "toISOString().slice(0, 16)" not in composer,
    "a datetime-local input is still filled from toISOString() (UTC); in IST that offers a "
    "time 5.5 hours off what the operator picked",
)
if "bulkPreview" in composer and "handleBulkSchedule" in composer:
    gate = composer[composer.find("const handleBulkSchedule"):]
    gate = gate[:gate.find("\n  };")]
    want("if (!bulkPreview)" in gate,
         "the bulk run is no longer gated on a preview; the operator would start a browser "
         "session without having seen the times")

# The UI must poll the run rather than wait on the request: the browser outlives
# the request, and a dropped connection used to lose a pin Pinterest had accepted.
want("api.getPublishRun" in composer,
     "PinComposer never polls the run, so a publish's outcome is never learned")
want("followRun" in composer, "PinComposer has no run-following loop")
for handler in ("handlePublishDirectBrowser", "handleBulkSchedule"):
    block = composer[composer.find(f"const {handler}"):]
    block = block[:block.find("\n  };")]
    want("followRun(" in block, f"{handler} does not follow the run it started")
want("run.stalled" in composer,
     "PinComposer ignores a stalled run; the operator would retry a pin Pinterest may already hold")
want("run.completed" in composer,
     "PinComposer shows no per-pin progress, so a fifteen-pin batch looks like a hung spinner")


# ── report ─────────────────────────────────────────────────────────────
if fails:
    print("FAIL — bulk scheduling / publisher guarantees")
    for f in fails:
        print(f"  • {f}")
    sys.exit(1)

print("PASS — bulk scheduling planner + publisher guarantees")
print(f"  planner: interval and daily-slot modes, {len(REFUSALS)} refusals, "
      f"{HORIZON_DAYS}-day horizon, {MIN_LEAD_MINUTES}-minute lead")
print("  publisher: read-back on every field, Tab not Enter, no board fallback, "
      "schedule failure never publishes now")
print("  queue: pinterest_scheduled excluded from get_due_pins (checked by execution)")
print("  runs: no browser in an API request; publish_bg sets the Proactor policy first and "
      "owns no DB connection")
print("  api + UI: preview then commit, run polled for progress, per-pin reasons surfaced")
for n in notes:
    print(f"  · note: {n}")
