"""
Pinterest Realism Engine — the scheduler that actually publishes.

Before this module existed, `POST /api/pins/{pin_id}/schedule` appended a row to
`data/scheduled_pins.json` and nothing ever read it back; five entries sat there
past their due time forever. This is the missing consumer.

Design notes:

* Plain asyncio loop, not APScheduler. The queue needs minute granularity and
  one worker, so a dependency buys nothing.
* `_PUBLISH_LOCK` serialises publishes. Every publish drives a real Chromium
  profile (`data/pinterest_profile`); two concurrent runs fight over the profile
  lock and both fail.
* A due entry is claimed (`scheduled` -> `publishing`) before the browser opens,
  so a restart mid-publish cannot double-post within the staleness window.
* Only a `live_url` observed by the publisher marks an entry published. A failure
  is recorded with its reason and retried up to MAX_PUBLISH_ATTEMPTS.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.services import pinterest_service as queue_service

logger = logging.getLogger("pre.scheduler")

# How often to look for due entries. The queue stores minute-resolution times,
# so 30s keeps drift under a minute without busy-looping on disk.
TICK_SECONDS = 30
REAPER_INTERVAL_SECONDS = 300  # 5 minutes

_PUBLISH_LOCK = asyncio.Lock()
_task: asyncio.Task | None = None


async def publish_queue_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """
    Publish one claimed queue entry through the browser publisher.

    The browser runs in a child process (`publish_runs.start_run`) and this waits
    for it. That is not indirection for its own sake: Playwright spawns its driver
    with `create_subprocess_exec`, which the event loop uvicorn's reloader installs
    on Windows cannot do — in-process it raised a bare `NotImplementedError`, so
    every scheduled publish failed with an empty reason. The child also survives a
    dev-server reload, which a 30-second tick makes likely.

    Returns the updated queue entry. Never raises for an ordinary publish
    failure — the failure is recorded on the entry so the queue explains itself
    and the loop keeps running.
    """
    entry_id = entry["id"]
    from app.services import board_catalog, publish_runs
    from app.services.media_paths import resolve_output_image

    resolved = resolve_output_image(entry.get("image_path", ""))
    if resolved is None:
        msg = f"image missing on disk: {entry.get('image_path')!r}"
        logger.error("Queue entry %s cannot publish — %s", entry_id, msg)
        return queue_service.mark_queue_entry_failed(entry_id, msg) or entry

    # Refuse a board this account did not have when its dropdown was last read.
    # The queue publishes unattended, so the old behaviour was: at 3am Chromium
    # opens, types the whole pin in, fails, and leaves an abandoned Pinterest draft
    # nobody can trace back to a run. `board_not_found` was already non-retryable
    # below — this just stops paying for the browser to learn it.
    check = board_catalog.check_board(entry.get("board_name"), fallback=settings.default_board_name)
    if check.blocks_publish:
        logger.error("Queue entry %s cannot publish — %s", entry_id, check.message)
        return queue_service.mark_queue_entry_failed(entry_id, check.message, retryable=False) or entry
    if check.verdict != board_catalog.OK:
        logger.warning("Queue entry %s board pre-flight: %s", entry_id, check.message)

    async with _PUBLISH_LOCK:
        try:
            logger.info("Scheduler publishing queue entry %s (pin %s)", entry_id, entry.get("pin_id"))
            started = publish_runs.start_run(
                publish_runs.KIND_PUBLISH,
                [{
                    "pin_id": entry.get("pin_id") or entry_id,
                    "image_path": str(resolved),
                    "title": entry.get("title") or "",
                    "description": entry.get("description") or "",
                    "link": entry.get("destination_url"),
                    "board_name": entry.get("board_name"),
                    "scheduled_for": None,
                }],
                headless=settings.scheduler_headless,
            )
        except Exception as e:
            msg = f"could not start the publisher process: {e}"
            logger.error("Queue entry %s: %s", entry_id, msg)
            return queue_service.mark_queue_entry_failed(entry_id, msg) or entry

        run = await publish_runs.wait_for_run(started["run_id"])

    run_id = started["run_id"]
    results = run.get("results") or []
    result = results[0] if results else {}

    if run.get("stalled") or run.get("timed_out"):
        # Deliberately not retried: the browser may have created the pin, and a
        # retry would post a duplicate. The operator has to look.
        msg = (f"the publisher stopped reporting (run {run_id}); check Pinterest before retrying, "
               "a pin may already be there")
        logger.error("Queue entry %s: %s", entry_id, msg)
        return queue_service.mark_queue_entry_failed(entry_id, msg, retryable=False) or entry

    if run.get("status") == publish_runs.ERROR and not result:
        msg = f"{run.get('error') or 'the publisher failed without saying why'} (run {run_id})"
        logger.warning("Queue entry %s publish failed: %s", entry_id, msg)
        return queue_service.mark_queue_entry_failed(entry_id, msg) or entry

    live_url = result.get("live_url")
    confirmed_by = result.get("confirmed_by")
    if not confirmed_by:
        # Nothing was proven, so nothing is claimed. `error_kind` says which kind
        # of failure it was, and two of them cannot be fixed by trying again on the
        # next 30-second tick: a signed-out profile, and a board this account does
        # not have. Retrying those just opens Chromium again and leaves another
        # abandoned Pinterest draft behind each time.
        kind = result.get("error_kind")
        msg = result.get("error") or "publisher returned no publish confirmation; treating as not published"
        if kind == "login_required":
            msg = f"Pinterest session is not logged in ({msg}). Run scripts/init_pinterest_auth.py."
        hopeless = ("login_required", "board_not_found", "image_missing", "bad_request")
        logger.error("Queue entry %s: %s", entry_id, msg)
        publish_runs.mark_applied(run_id)
        return queue_service.mark_queue_entry_failed(
            entry_id, msg, retryable=kind not in hopeless
        ) or entry
    if not live_url:
        # Pinterest confirmed the save but did not expose a pin URL. Retrying would
        # post a duplicate, so the entry counts as published with no URL recorded.
        logger.warning(
            "Queue entry %s: publish confirmed by %s but Pinterest exposed no pin URL",
            entry_id, confirmed_by,
        )

    updated = queue_service.mark_queue_entry_published(entry_id, live_url) or entry
    logger.info("Queue entry %s published (%s): %s", entry_id, confirmed_by, live_url or "no URL")

    await _record_publication(entry, live_url)
    # This scheduler owns the database write for its own runs, so the API must not
    # apply them a second time when it next lists pins.
    publish_runs.mark_applied(run_id)
    return updated


async def _record_publication(entry: dict[str, Any], live_url: str | None) -> None:
    """Mirror an observed publish into the database and the Obsidian vault."""
    pin_id = entry.get("pin_id")
    if not pin_id:
        return
    try:
        from app.database import async_session
        from app.models.models import PinDraft

        async with async_session() as db:
            pin = await db.get(PinDraft, pin_id)
            if pin is None:
                logger.warning("Published queue entry %s references unknown pin %s", entry.get("id"), pin_id)
                return
            pin.status = "published"
            pin.exported_at = datetime.now(timezone.utc)
            await db.commit()

            try:
                import json as _json

                from app.services.vault_sync import sync_pin_node

                sync_pin_node(
                    pin_id=pin.id,
                    job_id=pin.job_id,
                    title=pin.title,
                    description=pin.description,
                    keywords=_json.loads(pin.keywords) if pin.keywords else [],
                    destination_url=pin.destination_url,
                    board_name=pin.board_name,
                    status="published",
                    live_url=live_url,
                )
            except Exception as e:  # vault sync is telemetry, not the publish
                logger.warning("Vault sync after scheduled publish failed: %s", e)
    except Exception as e:
        logger.error("Could not record scheduled publish for pin %s: %s", pin_id, e)


async def run_once(now: datetime | None = None) -> list[dict[str, Any]]:
    """
    Process every entry that is due right now. Returns the updated entries.
    Exposed separately so it can be triggered manually and tested.
    """
    due = queue_service.get_due_pins(now=now)
    if not due:
        return []

    logger.info("Scheduler found %d due queue entr%s", len(due), "y" if len(due) == 1 else "ies")
    processed: list[dict[str, Any]] = []
    for entry in due:
        claimed = queue_service.claim_pin_for_publishing(entry["id"])
        if claimed is None:
            continue  # someone else took it, or it is no longer eligible
        processed.append(await publish_queue_entry(claimed))
    return processed


async def _loop() -> None:
    # Legacy entries predate the lifecycle fields; fill them in once at startup
    # so `get_due_pins` can reason about them.
    try:
        queue_service.normalize_queue()
    except Exception as e:
        logger.error("Queue normalisation failed at startup: %s", e)

    logger.info("Pin scheduler started (tick %ss)", TICK_SECONDS)
    last_reap = time.time()
    while True:
        try:
            await run_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # A crashing tick must not kill the loop; the next tick retries.
            logger.error("Scheduler tick failed: %s", e, exc_info=True)

        # Periodically reap dead/hung generation jobs (every 5 minutes)
        now = time.time()
        if now - last_reap >= REAPER_INTERVAL_SECONDS:
            last_reap = now
            try:
                from app.database import async_session
                from app.services.job_reaper import reap_stalled_jobs

                async with async_session() as db:
                    await reap_stalled_jobs(db)
            except Exception as e:
                logger.error("Scheduled job reaper sweep failed: %s", e)

        await asyncio.sleep(TICK_SECONDS)


def start_scheduler() -> None:
    """Start the background loop. Safe to call once, from app startup."""
    global _task
    if not settings.scheduler_enabled:
        logger.warning("Pin scheduler disabled by settings (scheduler_enabled=false); "
                       "queued pins will not publish on their own.")
        return
    if _task and not _task.done():
        return
    _task = asyncio.create_task(_loop(), name="pin-scheduler")


async def stop_scheduler() -> None:
    """Cancel the background loop and wait for it to unwind."""
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except (asyncio.CancelledError, Exception):
        pass
    _task = None
    logger.info("Pin scheduler stopped")


def is_running() -> bool:
    return bool(_task and not _task.done())
