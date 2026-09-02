"""
Pinterest Realism Engine — Direct Publishing & Scheduling Queue.

Two responsibilities:

1. `publish_pin_to_pinterest` — the Pinterest API v5 path. Requires a configured
   access token; it raises instead of inventing a result. The browser path in
   `pinterest_publisher.py` is what actually runs today.
2. The scheduling queue in `data/scheduled_pins.json`, with a real status
   lifecycle. `app/services/scheduler.py` is what drains it.

Nothing in this module may return a "published" record it did not observe.
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from app.config import settings

logger = logging.getLogger("pre.pinterest_service")

SCHEDULE_QUEUE_FILE = Path("./data/scheduled_pins.json")

# Queue entry lifecycle
STATUS_SCHEDULED = "scheduled"
STATUS_PUBLISHING = "publishing"
STATUS_PUBLISHED = "published"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

# Pinterest itself is holding this pin and will publish it at the recorded time
# (its native "Publish at a later date"). This status is deliberately NOT one of
# the three `get_due_pins` considers: PRE must never publish a pin Pinterest has
# already accepted, or the operator gets two identical pins.
STATUS_PINTEREST_SCHEDULED = "pinterest_scheduled"

# An entry stuck in `publishing` for longer than this is assumed to have died
# with the process (e.g. the app was closed mid-publish) and becomes eligible
# for retry.
STALE_PUBLISHING_AFTER = timedelta(minutes=30)

# A failed entry is retried by the scheduler until it has burned this many
# attempts, then it stays `failed` until an operator reschedules it. Without a
# ceiling, a pin with a deleted image would retry forever.
MAX_PUBLISH_ATTEMPTS = 3


class PinterestPublishError(RuntimeError):
    """Publishing to Pinterest failed. No pin was created."""


# ─────────────────────────────────────────────────
# Queue persistence
# ─────────────────────────────────────────────────
def _get_queue() -> list[dict[str, Any]]:
    if not SCHEDULE_QUEUE_FILE.exists():
        return []
    try:
        data = json.loads(SCHEDULE_QUEUE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.error("Schedule queue is unreadable (%s): %s", SCHEDULE_QUEUE_FILE, e)
        return []


def _save_queue(queue: list[dict[str, Any]]) -> None:
    SCHEDULE_QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SCHEDULE_QUEUE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(queue, indent=2, default=str), encoding="utf-8")
    tmp.replace(SCHEDULE_QUEUE_FILE)


def parse_scheduled_time(value: str | datetime | None) -> datetime | None:
    """
    Parse a scheduled_time into an aware UTC datetime.

    Accepts full ISO strings and the shorter 'YYYY-MM-DDTHH:MM' the UI sends.
    Naive values are interpreted as the operator's local time, because that is
    what a datetime-local input means.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            else:
                logger.error("Unparseable scheduled_time: %r", value)
                return None
    if dt.tzinfo is None:
        dt = dt.astimezone()  # attach the local offset
    return dt.astimezone(timezone.utc)


# ─────────────────────────────────────────────────
# Pinterest API v5 (only used when a token is configured)
# ─────────────────────────────────────────────────
async def publish_pin_to_pinterest(
    title: str,
    description: str,
    image_path: str,
    destination_url: str | None = None,
    board_id: str | None = None,
) -> dict[str, Any]:
    """
    Publish a pin through the Pinterest API v5.

    Raises:
        PinterestPublishError: if no token is configured, the image is missing,
            or Pinterest rejects the request.

    This function used to fabricate a `pin_live_<timestamp>` success record when
    the token was absent or the call failed, which made unpublished pins look
    published. It now fails loudly; use `pinterest_publisher.publish_pin_via_browser`
    for the browser-driven path that actually works today.
    """
    token = settings.pinterest_access_token
    if not token:
        raise PinterestPublishError(
            "PINTEREST_ACCESS_TOKEN is not configured, so the API path cannot publish. "
            "Use the browser publisher (POST /api/pins/{pin_id}/publish) instead."
        )

    img = Path(image_path)
    if not img.exists():
        raise PinterestPublishError(f"Image not found for publish: {image_path}")

    url = "https://api.pinterest.com/v5/pins"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {
        "title": title,
        "description": description,
        "link": destination_url or "",
        "media_source": {
            "source_type": "image_base64",
            "content_type": "image/jpeg",
            # Pinterest expects base64, not hex. The previous .hex() payload
            # would have been rejected even with a valid token.
            "data": base64.standard_b64encode(img.read_bytes()).decode("ascii"),
        },
    }
    if board_id:
        body["board_id"] = board_id

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        raise PinterestPublishError(
            f"Pinterest API rejected the pin: HTTP {e.response.status_code} — {e.response.text[:400]}"
        ) from e
    except Exception as e:
        raise PinterestPublishError(f"Pinterest API call failed: {e}") from e

    pin_id = data.get("id")
    if not pin_id:
        raise PinterestPublishError(f"Pinterest response contained no pin id: {str(data)[:400]}")

    return {
        "status": STATUS_PUBLISHED,
        "pin_id": pin_id,
        "url": f"https://www.pinterest.com/pin/{pin_id}/",
        "published_at": datetime.now(timezone.utc).isoformat(),
        "title": title,
        "raw": data,
    }


# ─────────────────────────────────────────────────
# Scheduling queue
# ─────────────────────────────────────────────────
def schedule_pin_for_later(
    pin_id: str,
    title: str,
    description: str,
    image_path: str,
    destination_url: str | None = None,
    board_name: str | None = None,
    scheduled_time: str | datetime | None = None,
) -> dict[str, Any]:
    """
    Add a pin to the queue in `data/scheduled_pins.json`.

    Raises:
        ValueError: if `scheduled_time` cannot be parsed, or the image is gone.
            Queueing an entry whose image does not exist guarantees a failure
            30 minutes later with no useful context, so it is rejected here.
    """
    when = parse_scheduled_time(scheduled_time) or datetime.now(timezone.utc)

    if not Path(image_path).exists():
        raise ValueError(f"Cannot schedule pin {pin_id}: image not found at {image_path}")

    now = datetime.now(timezone.utc)
    entry = {
        # uuid suffix: two pins queued in the same second used to collide on
        # `sched_<timestamp>`, and every id-based lookup then hit the wrong row.
        "id": f"sched_{int(now.timestamp())}_{uuid4().hex[:6]}",
        "pin_id": pin_id,
        "title": title,
        "description": description,
        "image_path": str(image_path),
        "destination_url": destination_url,
        "board_name": board_name,
        # Always stored as an aware UTC ISO string, so the scheduler never has
        # to guess a timezone. Older entries written as naive local time are
        # normalised on read by `parse_scheduled_time`.
        "scheduled_time": when.isoformat(),
        "status": STATUS_SCHEDULED,
        "attempts": 0,
        "last_error": None,
        "live_url": None,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

    queue = _get_queue()
    # Replace any earlier open entry for the same pin rather than queueing the
    # same image twice.
    queue = [
        e for e in queue
        if not (e.get("pin_id") == pin_id and e.get("status") in (STATUS_SCHEDULED, STATUS_FAILED))
    ]
    queue.append(entry)
    _save_queue(queue)

    logger.info("Queued pin %s for %s (entry %s)", pin_id, entry["scheduled_time"], entry["id"])
    return entry


def record_pinterest_native_schedule(
    pin_id: str,
    title: str,
    description: str,
    image_path: str,
    destination_url: str | None = None,
    board_name: str | None = None,
    scheduled_time: str | datetime | None = None,
    confirmed_by: str | None = None,
    live_url: str | None = None,
) -> dict[str, Any]:
    """
    Record a pin that *Pinterest* has accepted for later publication.

    This is the bulk path: the browser flipped "Publish at a later date", typed a
    time and Pinterest confirmed. From then on Pinterest publishes it with this
    machine switched off, so the entry exists only so the operator can see what
    is queued — it is written with `STATUS_PINTEREST_SCHEDULED`, which
    `get_due_pins` ignores, and it carries `confirmed_by` so a row nobody
    observed can be told from one Pinterest acknowledged.

    Any earlier *open* local entry for the same pin is cancelled, otherwise PRE's
    own scheduler would publish a duplicate at its own queued time.
    """
    when = parse_scheduled_time(scheduled_time)
    now = datetime.now(timezone.utc)
    entry = {
        "id": f"pins_{int(now.timestamp())}_{uuid4().hex[:6]}",
        "pin_id": pin_id,
        "title": title,
        "description": description,
        "image_path": str(image_path),
        "destination_url": destination_url,
        "board_name": board_name,
        "scheduled_time": (when or now).isoformat(),
        "status": STATUS_PINTEREST_SCHEDULED,
        "handled_by": "pinterest",
        "confirmed_by": confirmed_by,
        "attempts": 0,
        "last_error": None,
        "live_url": live_url,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

    queue = _get_queue()
    for e in queue:
        if e.get("pin_id") == pin_id and e.get("status") in (STATUS_SCHEDULED, STATUS_FAILED):
            e["status"] = STATUS_CANCELLED
            e["last_error"] = "Superseded — Pinterest is now holding this pin natively."
            e["updated_at"] = now.isoformat()
    queue.append(entry)
    _save_queue(queue)

    logger.info(
        "Pinterest accepted pin %s for %s (entry %s, confirmed by %s)",
        pin_id, entry["scheduled_time"], entry["id"], confirmed_by or "nothing",
    )
    return entry


def get_scheduled_pins(status: str | None = None) -> list[dict[str, Any]]:
    """Return queue entries, newest scheduled_time last. Optionally filtered by status."""
    queue = _get_queue()
    if status:
        queue = [e for e in queue if e.get("status") == status]
    return sorted(queue, key=lambda e: str(e.get("scheduled_time") or ""))


def update_queue_entry(entry_id: str, **fields: Any) -> dict[str, Any] | None:
    """
    Patch one queue entry in place and persist. Returns the updated entry, or
    None if `entry_id` is not in the queue.
    """
    queue = _get_queue()
    updated: dict[str, Any] | None = None
    for e in queue:
        if e.get("id") == entry_id:
            e.update(fields)
            e["updated_at"] = datetime.now(timezone.utc).isoformat()
            updated = e
            break
    if updated is None:
        logger.warning("update_queue_entry: no entry with id %r", entry_id)
        return None
    _save_queue(queue)
    return updated


def get_due_pins(now: datetime | None = None) -> list[dict[str, Any]]:
    """
    Entries whose scheduled_time has passed and that are eligible to publish.

    Eligible means:
      - status `scheduled`;
      - status `failed` with fewer than MAX_PUBLISH_ATTEMPTS attempts spent;
      - status `publishing` stuck longer than STALE_PUBLISHING_AFTER (the
        process died mid-publish, e.g. the app was closed).

    Entries with an unparseable scheduled_time are skipped and logged rather
    than treated as due — publishing at an unknown time is worse than not
    publishing.
    """
    now = now or datetime.now(timezone.utc)
    due: list[dict[str, Any]] = []

    for e in _get_queue():
        status = e.get("status")
        if status not in (STATUS_SCHEDULED, STATUS_PUBLISHING, STATUS_FAILED):
            continue

        when = parse_scheduled_time(e.get("scheduled_time"))
        if when is None:
            logger.error("Queue entry %s has unusable scheduled_time %r; skipping",
                         e.get("id"), e.get("scheduled_time"))
            continue
        if when > now:
            continue

        if status == STATUS_FAILED:
            if int(e.get("attempts") or 0) >= MAX_PUBLISH_ATTEMPTS:
                continue  # exhausted; needs an operator, not another retry

        if status == STATUS_PUBLISHING:
            started = parse_scheduled_time(e.get("updated_at")) or when
            if now - started < STALE_PUBLISHING_AFTER:
                continue  # a publish is genuinely in flight
            logger.warning("Entry %s stuck in %s since %s; reclaiming for retry",
                           e.get("id"), STATUS_PUBLISHING, started.isoformat())

        due.append(e)

    return sorted(due, key=lambda e: str(e.get("scheduled_time") or ""))


def claim_pin_for_publishing(entry_id: str) -> dict[str, Any] | None:
    """
    Flip an entry to `publishing` so a second worker will not pick it up.
    Returns the claimed entry, or None if it vanished or was already claimed
    by someone else within the staleness window.
    """
    queue = _get_queue()
    now = datetime.now(timezone.utc)

    for e in queue:
        if e.get("id") != entry_id:
            continue
        if e.get("status") == STATUS_PUBLISHING:
            started = parse_scheduled_time(e.get("updated_at"))
            if started and now - started < STALE_PUBLISHING_AFTER:
                return None
        elif e.get("status") == STATUS_FAILED:
            if int(e.get("attempts") or 0) >= MAX_PUBLISH_ATTEMPTS:
                return None
        elif e.get("status") != STATUS_SCHEDULED:
            return None

        e["status"] = STATUS_PUBLISHING
        e["attempts"] = int(e.get("attempts") or 0) + 1
        e["updated_at"] = now.isoformat()
        _save_queue(queue)
        return e

    return None


def mark_queue_entry_published(entry_id: str, live_url: str | None) -> dict[str, Any] | None:
    """Record an observed publish.

    `live_url` must come from the publisher, never be synthesised. It may be None:
    Pinterest sometimes confirms the save without exposing a pin URL, and an empty
    URL is more honest than a fabricated one.
    """
    return update_queue_entry(
        entry_id,
        status=STATUS_PUBLISHED,
        live_url=live_url,
        published_at=datetime.now(timezone.utc).isoformat(),
        last_error=None,
    )


def mark_queue_entry_failed(entry_id: str, error: str, *, retryable: bool = True) -> dict[str, Any] | None:
    """
    Record a publish failure with its reason, so the queue explains itself.

    `retryable=False` also spends the attempt budget, which stops the 30-second
    tick picking the entry up again. Used where a retry would be worse than the
    failure: a browser that stopped reporting may already have created the pin,
    and a login wall will not clear by reopening Chromium every half minute.
    """
    fields: dict[str, Any] = {"status": STATUS_FAILED, "last_error": str(error)[:600]}
    if not retryable:
        fields["attempts"] = MAX_PUBLISH_ATTEMPTS
    return update_queue_entry(entry_id, **fields)


def cancel_scheduled_pin(entry_id: str) -> dict[str, Any] | None:
    """Cancel a queued pin. Already-published entries are left untouched."""
    queue = _get_queue()
    for e in queue:
        if e.get("id") == entry_id:
            if e.get("status") == STATUS_PUBLISHED:
                return None
            break
    return update_queue_entry(entry_id, status=STATUS_CANCELLED)


def normalize_queue() -> int:
    """
    One-off migration for entries written before the lifecycle existed: fill in
    the missing bookkeeping fields, rewrite naive `scheduled_time` values as
    aware UTC, and give duplicate ids fresh unique ones.

    Duplicate ids are not hypothetical: the old `sched_<timestamp>` scheme gave
    four entries queued in the same second the id `sched_1787256120`, so every
    id-based update hit whichever one came first. Returns the number of entries
    changed.
    """
    queue = _get_queue()
    changed = 0
    seen_ids: set[str] = set()

    for e in queue:
        before = dict(e)

        entry_id = str(e.get("id") or "")
        if not entry_id or entry_id in seen_ids:
            e["id"] = f"sched_{int(datetime.now(timezone.utc).timestamp())}_{uuid4().hex[:6]}"
            logger.warning("Queue entry id %r was missing or duplicated; reassigned to %s",
                           entry_id, e["id"])
        seen_ids.add(str(e["id"]))

        e.setdefault("status", STATUS_SCHEDULED)
        e.setdefault("attempts", 0)
        e.setdefault("last_error", None)
        e.setdefault("live_url", None)
        when = parse_scheduled_time(e.get("scheduled_time"))
        if when is not None:
            e["scheduled_time"] = when.isoformat()
        e.setdefault("updated_at", e.get("created_at") or datetime.now(timezone.utc).isoformat())
        if e != before:
            changed += 1

    if changed:
        _save_queue(queue)
        logger.info("Normalized %d legacy queue entries", changed)
    return changed
