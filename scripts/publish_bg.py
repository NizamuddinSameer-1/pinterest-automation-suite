"""
The child process that drives Chromium for a publish or bulk-schedule run.

    python -m scripts.publish_bg <run_id>

Started by `app/services/publish_runs.start_run`, never by hand in normal use.
It reads `data/publish_runs/<run_id>/spec.json`, puts every pin through one
browser session, and rewrites `status.json` after each one so the API can report
progress without holding a request open.

Two things make this a separate process rather than a task inside FastAPI:

  1. Playwright spawns the Chromium driver with `asyncio.create_subprocess_exec`,
     which raises NotImplementedError on Windows' SelectorEventLoop — and that is
     the loop uvicorn installs whenever it runs with `reload=True`. A fresh
     interpreter gets the Proactor loop, and the policy below makes that explicit.
  2. A browser run takes minutes. Out here it survives a dev-server reload, a
     refreshed tab and a dropped connection; the result is on disk either way.

It never touches the database. The API applies a finished run's effects once,
which keeps every SQLite write in one process.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Before anything imports playwright. On Windows this is the difference between
# a working browser and `NotImplementedError` with no message.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pre.publish_bg")


def _parse_when(value: str | None) -> datetime | None:
    """Read the spec's `scheduled_for` back as an aware UTC datetime."""
    if not value:
        return None
    when = datetime.fromisoformat(value)
    if when.tzinfo is None:
        raise ValueError(f"scheduled_for {value!r} has no timezone; the API must send aware UTC")
    return when.astimezone(timezone.utc)


async def main(run_id: str) -> int:
    from app.services import publish_runs as runs

    spec = runs.read_spec(run_id)
    if spec is None:
        logger.error("No spec.json for run %s", run_id)
        return 2

    status = runs.read_status(run_id) or {}
    results: list[dict] = []

    async def on_result(result) -> None:
        """Publish progress after every pin, so a long run is never opaque."""
        results.append(result.as_dict())
        runs.write_status(run_id, {
            **status,
            "status": runs.RUNNING,
            "completed": len(results),
            "results": list(results),
        })
        logger.info("run %s: %s/%s — %s %s", run_id, len(results), total,
                    result.pin_id, result.status)

    total = len(spec.get("pins") or [])
    try:
        # Imported inside the try on purpose: a missing Playwright, a broken
        # settings file or a malformed spec must end up in status.json like any
        # other failure. Raised out here it would leave a run that claims to be
        # running for the fifteen minutes it takes to look stalled.
        from app.services.pinterest_publisher import PinSpec, run_pin_batch

        specs = [
            PinSpec(
                pin_id=p["pin_id"],
                image_path=p["image_path"],
                title=p.get("title") or "",
                description=p.get("description") or "",
                link=p.get("link"),
                board_name=p.get("board_name"),
                scheduled_for=_parse_when(p.get("scheduled_for")),
                profile_id=p.get("profile_id") or spec.get("profile_id") or "default",
            )
            for p in spec["pins"]
        ]
        total = len(specs)
        logger.info("run %s: %s pin(s), kind=%s", run_id, total, spec.get("kind"))

        await run_pin_batch(specs, headless=bool(spec.get("headless")), on_result=on_result)
        finished = {"status": runs.DONE, "error": None}
    except Exception as e:
        # A crash here is a real outcome, not a lost run: record it, including the
        # exception type, because NotImplementedError and friends stringify empty.
        message = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
        logger.exception("run %s failed: %s", run_id, message)
        finished = {"status": runs.ERROR, "error": message}

    runs.write_status(run_id, {
        **status,
        **finished,
        "completed": len(results),
        "results": list(results),
        "finished_at": datetime.now(timezone.utc).isoformat(),
    })
    return 0 if finished["status"] == runs.DONE else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    try:
        raise SystemExit(asyncio.run(main(sys.argv[1])))
    except SystemExit:
        raise
    except BaseException as exc:
        # Last resort: even a failure to import the app must not leave a run
        # looking alive. If the store itself is unreachable there is nothing left
        # to write with, so the traceback in log.txt is all there is.
        logger.exception("run %s died before it could record anything", sys.argv[1])
        try:
            from app.services import publish_runs as runs

            previous = runs.read_status(sys.argv[1]) or {}
            runs.write_status(sys.argv[1], {
                **previous,
                "status": runs.ERROR,
                "error": f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            pass
        raise SystemExit(3)
