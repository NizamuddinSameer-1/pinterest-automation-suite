"""
Browser publish/schedule runs, owned by a **child process**.

Why a separate process at all: Playwright has to spawn the Chromium driver with
`asyncio.create_subprocess_exec`, and that only works on a ProactorEventLoop on
Windows. uvicorn started with `reload=True` runs the app on a *Selector* loop
(it sets WindowsSelectorEventLoopPolicy whenever it uses a subprocess), so every
in-request publish died with a bare `NotImplementedError` — the empty-message
500 the operator saw as "Direct browser publish failed:".

Running the browser in `python -m scripts.publish_bg` sidesteps the whole
question: a fresh interpreter gets Windows' default Proactor loop, and the run
also outlives a dev-server reload, a closed tab or a dropped connection. The
HTTP request only starts the run and returns a `run_id`.

Contract, all on disk under `data/publish_runs/<run_id>/`:

  spec.json    written once by the API — what to publish, and when
  status.json  rewritten by the child after every pin — the only progress source
  log.txt      the child's stdout and stderr

`status.json` carries `applied`, which is the API's flag, not the child's: the
child never touches the database, so the API applies a finished run's effects
(pin status, the local queue, the vault) exactly once. That keeps every SQLite
write in one process while still letting the browser run outside it.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger("pre.publish_runs")

RUNS_DIR = Path("./data/publish_runs").resolve()

KIND_PUBLISH = "publish"
KIND_BULK_SCHEDULE = "bulk_schedule"

# status values, in order
STARTING = "starting"
RUNNING = "running"
DONE = "done"
ERROR = "error"
FINISHED = (DONE, ERROR)


def run_dir(run_id: str) -> Path:
    """The directory for one run. `run_id` is checked, because it reaches a path."""
    if not run_id or not all(c.isalnum() or c in "-_" for c in run_id):
        raise ValueError(f"Not a run id: {run_id!r}")
    return RUNS_DIR / run_id


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write atomically — a half-written status.json would read as a crashed run."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def read_spec(run_id: str) -> dict[str, Any] | None:
    return _read_json(run_dir(run_id) / "spec.json")


def read_status(run_id: str) -> dict[str, Any] | None:
    return _read_json(run_dir(run_id) / "status.json")


def write_status(run_id: str, payload: dict[str, Any]) -> None:
    _write_json(run_dir(run_id) / "status.json", payload)


def start_run(
    kind: str,
    pins: list[dict[str, Any]],
    *,
    headless: bool = False,
    profile_id: str | None = None,
    skipped: list[str] | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    """
    Write the spec, launch the child, and return the initial status.

    `pins` entries are the publisher's `PinSpec` fields as JSON: pin_id,
    image_path, title, description, link, board_name, scheduled_for, and profile_id.

    Raises RuntimeError if the child could not be started — the caller must not
    report a run that is not running.
    """
    if kind not in (KIND_PUBLISH, KIND_BULK_SCHEDULE):
        raise ValueError(f"Unknown run kind {kind!r}")
    if not pins:
        raise ValueError("A run needs at least one pin")

    run_id = uuid.uuid4().hex[:12]
    directory = run_dir(run_id)
    directory.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).isoformat()
    _write_json(directory / "spec.json", {
        "run_id": run_id,
        "kind": kind,
        "headless": headless,
        "profile_id": profile_id or "default",
        "created_at": now,
        "pins": pins,
    })

    status: dict[str, Any] = {
        "run_id": run_id,
        "kind": kind,
        "status": STARTING,
        "started_at": now,
        "finished_at": None,
        "total": len(pins),
        "completed": 0,
        "results": [],
        "error": None,
        "applied": False,
        "skipped": list(skipped or []),
        "notes": list(notes or []),
        "pid": None,
    }
    write_status(run_id, status)
    prune_old_runs()
    return _spawn(run_id, status, directory)


RETENTION_DAYS = 14


def prune_old_runs(*, keep_days: int = RETENTION_DAYS) -> int:
    """
    Delete applied runs older than `keep_days`, and return how many went.

    Called when a run starts, not when pins are listed: every list request
    reconciles unapplied runs by reading each status.json, so the directory has to
    stay small, but it does not need pruning on the read path. Only *applied* runs
    are removed — an unapplied one still owes the database its outcome, however
    old it is.
    """
    if not RUNS_DIR.exists():
        return 0
    cutoff = datetime.now(timezone.utc).timestamp() - keep_days * 86400
    removed = 0
    for directory in RUNS_DIR.iterdir():
        if not directory.is_dir():
            continue
        status = _read_json(directory / "status.json")
        if not status or not status.get("applied"):
            continue
        try:
            if (directory / "status.json").stat().st_mtime > cutoff:
                continue
            shutil.rmtree(directory)
            removed += 1
        except OSError as e:
            logger.warning("Could not prune old publish run %s: %s", directory.name, e)
    if removed:
        logger.info("pruned %d publish run(s) older than %d days", removed, keep_days)
    return removed


def _spawn(run_id: str, status: dict[str, Any], directory: Path) -> dict[str, Any]:
    """Start `python -m scripts.publish_bg <run_id>` detached from this request."""
    log_path = directory / "log.txt"
    try:
        log = open(log_path, "w", encoding="utf-8", buffering=1)
    except OSError as e:
        raise RuntimeError(f"Could not open {log_path} for the publish run: {e}") from e

    # cwd is the project root: the publisher resolves ./data/pinterest_profile
    # and image paths relative to it, so a child started elsewhere would open a
    # brand-new, logged-out Chrome profile.
    root = Path(__file__).resolve().parents[2]
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "scripts.publish_bg", run_id],
            cwd=str(root),
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
    except OSError as e:
        log.close()
        status = {**status, "status": ERROR, "error": f"Could not start the publisher process: {e}",
                  "finished_at": datetime.now(timezone.utc).isoformat()}
        write_status(run_id, status)
        raise RuntimeError(status["error"]) from e

    status = {**status, "status": RUNNING, "pid": proc.pid}
    write_status(run_id, status)
    logger.info("publish run %s started as pid %s (%s pin(s))", run_id, proc.pid, status["total"])
    return status


async def wait_for_run(run_id: str, *, poll_seconds: float = 2.0, timeout_seconds: float = 30 * 60) -> dict[str, Any]:
    """
    Wait for a run to finish, and return its final status.

    For callers that already run outside a request — PRE's own queue scheduler —
    where waiting is the point. It reads status.json rather than the process
    handle, so it works after a reload and reports a stalled child instead of
    hanging on it. A timeout returns the last status seen; the caller must treat
    an unfinished run as unproven, not as a failure, because the browser may have
    created the pin.
    """
    import asyncio

    deadline = datetime.now(timezone.utc).timestamp() + timeout_seconds
    status = read_status(run_id) or {"run_id": run_id, "status": STARTING, "results": []}
    while True:
        status = read_status(run_id) or status
        if status.get("status") in FINISHED:
            return status
        if is_stalled(run_id, status):
            logger.error("publish run %s stopped reporting; giving up on it", run_id)
            return {**status, "stalled": True}
        if datetime.now(timezone.utc).timestamp() > deadline:
            logger.error("publish run %s is still running after %.0fs", run_id, timeout_seconds)
            return {**status, "timed_out": True}
        await asyncio.sleep(poll_seconds)


def unapplied_finished() -> Iterator[dict[str, Any]]:
    """Finished runs whose database effects have not been applied yet.

    Used to converge after a reload or a closed tab: the child keeps working and
    writes its results, so the effects must be applied whenever the API next
    looks, not only while someone is polling.
    """
    if not RUNS_DIR.exists():
        return
    for directory in sorted(RUNS_DIR.iterdir()):
        if not directory.is_dir():
            continue
        status = _read_json(directory / "status.json")
        if status and status.get("status") in FINISHED and not status.get("applied"):
            yield status


def mark_applied(run_id: str) -> None:
    status = read_status(run_id)
    if status is None:
        return
    write_status(run_id, {**status, "applied": True})


STALL_MINUTES = 15


def is_stalled(run_id: str, status: dict[str, Any], *, minutes: int = STALL_MINUTES) -> bool:
    """
    True when a run still claims to be running but has stopped writing.

    The child rewrites status.json after every pin, so silence for longer than a
    pin can take means the process is gone (killed, or crashed before it could
    record the failure). Reported rather than repaired: the browser may have got
    far enough to create a pin, and this cannot know.
    """
    if status.get("status") not in (STARTING, RUNNING):
        return False
    try:
        age = datetime.now(timezone.utc).timestamp() - (run_dir(run_id) / "status.json").stat().st_mtime
    except OSError:
        return True
    return age > minutes * 60
