"""
Watch publish/schedule runs happen, live, from a terminal.

    python -m scripts.watch_runs            follow whatever runs next
    python -m scripts.watch_runs --list     recent runs and how they ended
    python -m scripts.watch_runs --run 3f9a follow one run by id (prefix is enough)
    python -m scripts.watch_runs --last     re-read the most recent run and exit

Why this exists: since the browser moved out of the API process
(`app/services/publish_runs.start_run` -> `python -m scripts.publish_bg`), the
only record of a run is on disk under `data/publish_runs/<run_id>/`. The UI polls
`status.json` and shows a progress bar, but it deliberately hides the noisy part
-- Chromium's own stdout, the selector the publisher settled on, the traceback of
a failure. That is exactly what you want when a publish misbehaves, so this
prints both: every change to `status.json` and every new line of `log.txt`,
interleaved, as they are written.

Read-only. It never starts, stops or repairs a run, and it holds no lock, so it
is safe to leave open while publishing. Ctrl-C to stop watching; the run itself
keeps going, because it is a separate process.

ASCII output only -- the Windows console default code page mangles anything else.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "data" / "publish_runs"

POLL_SECONDS = 1.0


def _read_json(path: Path) -> dict | None:
    """Tolerate a torn read: the child rewrites status.json while we poll it."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _runs() -> list[Path]:
    """Run directories, oldest first by the mtime of their spec.json."""
    if not RUNS_DIR.exists():
        return []
    dirs = [d for d in RUNS_DIR.iterdir() if d.is_dir() and (d / "spec.json").exists()]
    return sorted(dirs, key=lambda d: (d / "spec.json").stat().st_mtime)


def _clock(value: str | None) -> str:
    """An ISO timestamp as local wall-clock time, which is what you compare against."""
    if not value:
        return "-"
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        return value
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone().strftime("%H:%M:%S")


def _say(text: str = "") -> None:
    print(text, flush=True)


def _summarise(status: dict, spec: dict | None) -> str:
    kind = status.get("kind") or (spec or {}).get("kind") or "?"
    return (f"run {status.get('run_id')}  kind={kind}  pins={status.get('total')}  "
            f"started {_clock(status.get('started_at'))}  pid={status.get('pid')}")


def _result_line(result: dict) -> str:
    """One pin's outcome. `confirmed_by` is the only field that proves anything."""
    bits = [f"  - {result.get('pin_id')}: {result.get('status')}"]
    if result.get("confirmed_by"):
        bits.append(f"confirmed by {result['confirmed_by']}")
    if result.get("live_url"):
        bits.append(str(result["live_url"]))
    if result.get("scheduled_for"):
        bits.append(f"scheduled for {_clock(result['scheduled_for'])}")
    if result.get("error_kind"):
        bits.append(f"[{result['error_kind']}]")
    if result.get("error"):
        bits.append(str(result["error"])[:300])
    return "  ".join(bits)


def show(run: Path, *, tail_log_lines: int = 40) -> None:
    """Print a finished (or abandoned) run once, without following it."""
    status = _read_json(run / "status.json") or {}
    spec = _read_json(run / "spec.json")
    _say("=" * 78)
    _say(_summarise(status, spec))
    _say(f"status={status.get('status')}  completed={status.get('completed')}/{status.get('total')}"
         f"  applied={status.get('applied')}  finished {_clock(status.get('finished_at'))}")
    if status.get("error"):
        _say(f"error: {status['error']}")
    for result in status.get("results") or []:
        _say(_result_line(result))
    for note in status.get("notes") or []:
        _say(f"  note: {note}")
    for skip in status.get("skipped") or []:
        _say(f"  skipped: {skip}")
    log = run / "log.txt"
    if log.exists():
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        _say(f"--- log.txt (last {min(tail_log_lines, len(lines))} of {len(lines)} lines) ---")
        for line in lines[-tail_log_lines:]:
            _say(line)
    _say(f"full log: {log}")


def follow(run: Path) -> dict:
    """
    Stream one run until it finishes, and return its last status.

    Two sources, polled together: `status.json` (rewritten wholesale after every
    pin, so we diff it rather than trusting an event) and `log.txt` (append-only,
    so we remember a byte offset). Printing both is the point -- status.json says
    *what* happened, the log says why.
    """
    status_path, log_path = run / "status.json", run / "log.txt"
    printed_results = 0
    last_line = ""
    offset = 0
    status: dict = {}

    _say("=" * 78)
    while True:
        fresh = _read_json(status_path)
        if fresh:
            if not status:
                _say(_summarise(fresh, _read_json(run / "spec.json")))
                _say(f"watching {status_path}")
                _say("-" * 78)
            status = fresh

        if log_path.exists():
            try:
                with log_path.open("r", encoding="utf-8", errors="replace") as fh:
                    fh.seek(offset)
                    chunk = fh.read()
                    offset = fh.tell()
                for line in chunk.splitlines():
                    if line.strip():
                        _say(f"    | {line}")
            except OSError:
                pass  # the child has it open for writing; try again next tick

        results = status.get("results") or []
        for result in results[printed_results:]:
            _say(_result_line(result))
        printed_results = len(results)

        line = (f"[{status.get('status')}] {status.get('completed')}/{status.get('total')} pins")
        if line != last_line:
            _say(line)
            last_line = line

        if status.get("status") in ("done", "error"):
            _say("-" * 78)
            _say(f"finished {_clock(status.get('finished_at'))} as {status.get('status')}")
            if status.get("error"):
                _say(f"error: {status['error']}")
            _say("The API applies the database effects on the next poll or pin list "
                 "(applied=true in status.json when it has).")
            return status

        # A child that stops rewriting status.json is gone. Say so rather than
        # waiting forever: the browser may still have created the pin, so this is
        # reported, never repaired.
        try:
            silence = time.time() - status_path.stat().st_mtime
        except OSError:
            silence = 0.0
        if status.get("status") in ("starting", "running") and silence > 15 * 60:
            _say(f"!! no progress for {silence / 60:.0f} minutes -- the publisher process looks gone.")
            _say("   Check Pinterest before retrying: a pin may already be there.")
            return {**status, "stalled": True}

        time.sleep(POLL_SECONDS)


def wait_for_new_run(known: set[str]) -> Path:
    """Block until a run directory appears that we have not seen."""
    _say(f"Waiting for a publish run in {RUNS_DIR}")
    _say("Trigger one from the UI (Publish, or Bulk schedule), or let the queue tick pick a pin up.")
    _say("Ctrl-C to stop watching.")
    while True:
        for run in _runs():
            if run.name not in known:
                return run
        time.sleep(POLL_SECONDS)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Watch PRE publish runs as they happen.")
    parser.add_argument("--run", help="run id (a unique prefix is enough)")
    parser.add_argument("--list", action="store_true", help="list recent runs and exit")
    parser.add_argument("--last", action="store_true", help="show the most recent run and exit")
    parser.add_argument("--follow-last", action="store_true",
                        help="attach to the most recent run even if it has finished")
    args = parser.parse_args(argv)

    runs = _runs()

    if args.list:
        if not runs:
            _say(f"No runs yet under {RUNS_DIR}")
            return 0
        _say(f"{'run id':14} {'kind':15} {'status':9} {'pins':>5}  started   applied")
        for run in runs[-25:]:
            s = _read_json(run / "status.json") or {}
            _say(f"{run.name:14} {str(s.get('kind')):15} {str(s.get('status')):9} "
                 f"{s.get('completed')}/{s.get('total'):<3} {_clock(s.get('started_at')):9} "
                 f"{s.get('applied')}")
        _say(f"\n{len(runs)} run(s). Detail: python -m scripts.watch_runs --run <id>")
        return 0

    if args.run:
        matches = [r for r in runs if r.name.startswith(args.run)]
        if not matches:
            _say(f"No run id starts with {args.run!r}. Try --list.")
            return 2
        if len(matches) > 1:
            _say(f"{args.run!r} matches {[r.name for r in matches]} -- be more specific.")
            return 2
        target = matches[0]
        status = _read_json(target / "status.json") or {}
        if status.get("status") in ("done", "error"):
            show(target)
            return 0
        follow(target)
        return 0

    if args.last or args.follow_last:
        if not runs:
            _say(f"No runs yet under {RUNS_DIR}")
            return 0
        if args.follow_last and (_read_json(runs[-1] / "status.json") or {}).get("status") in ("starting", "running"):
            follow(runs[-1])
        else:
            show(runs[-1])
        return 0

    # Default: sit and wait, then follow every run that starts. This is the mode
    # to leave open in a second terminal while using the UI.
    known = {r.name for r in runs}
    # ...but if a run is already in flight, attach to it rather than ignoring it:
    # starting the watcher *after* clicking Publish is the normal way to reach for
    # it, and waiting quietly while a browser is working would look like a hang.
    if runs and (_read_json(runs[-1] / "status.json") or {}).get("status") in ("starting", "running"):
        _say(f"run {runs[-1].name} is already in flight -- attaching to it")
        follow(runs[-1])
        _say()
    while True:
        run = wait_for_new_run(known)
        known.add(run.name)
        follow(run)
        _say()


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        _say("\nStopped watching. Any run in flight is a separate process and keeps going.")
        raise SystemExit(130)
    except BrokenPipeError:
        # `... | head` closes the pipe under us. Not an error worth a traceback.
        raise SystemExit(0)
