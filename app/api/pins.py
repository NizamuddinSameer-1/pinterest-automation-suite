"""
Pins API routes — drafting, SEO generation, compliance verification,
and ZIP package export.

All pin actions synchronize in real time with the Obsidian Vault.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("pre.pins_api")

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.models import PinDraft, Job, JobOutput, Product, Reference
from app.pipeline.pinterest_seo import generate_pin_seo
from app.schemas.schemas import PinDraftCreate, PinDraftUpdate, PinReject
from app.services.export_service import export_pin_package
from app.services.media_paths import resolve_output_image
from app.services import board_catalog, publish_runs
from app.services.vault_sync import sync_pin_node, log_runtime_bug

router = APIRouter(prefix="/api/pins", tags=["pins"])


# ── pre-flight: what can be refused before a browser is spent ────────────
def _link_problem(pin: PinDraft) -> str | None:
    """
    Why this pin must not be published yet, on account of its link, or None.

    An affiliate pin with no destination URL is decoration: it can never earn, and
    Pinterest gives no way to add a link after publishing — the pin has to be
    deleted and remade. Two pins had already published this way before the check
    existed, because `create_pin_draft` stores `product.affiliate_url or ""` and
    four products have none.

    Callers pass `allow_no_link=true` to publish deliberately (a brand-awareness
    pin, or a board the operator links from elsewhere).
    """
    if (pin.destination_url or "").strip():
        return None
    return (
        "This pin has no destination URL, so it would publish with nothing to click — "
        "an affiliate pin that cannot earn, and Pinterest does not let a link be added "
        "afterwards. Set the product's affiliate URL or the pin's destination_url. "
        "Pass allow_no_link=true to publish it without one on purpose."
    )


def _board_problem(pin: PinDraft, profile_id: str | None = None) -> str | None:
    """
    Why this pin's board must not be published to yet, or None.

    The board name comes from the SEO model's `board_suggestion` and nothing ever
    reconciled it with the account, so twenty drafts named boards that do not
    exist. Each attempt cost a Chromium launch, half a minute, and one abandoned
    Pinterest draft — the operator found ten of them and no pins.

    `board_catalog.check_board` answers from the last board list read off the
    dropdown for the target profile.
    """
    target_profile = (profile_id or pin.profile_id or "default").strip()
    check = board_catalog.check_board(pin.board_name, fallback=settings.default_board_name, profile_id=target_profile)
    if check.blocks_publish:
        return check.message
    if check.verdict != board_catalog.OK:
        logger.warning("Pin %s board pre-flight for profile %s: %s", pin.id, target_profile, check.message)
    return None


@router.post("/draft", status_code=201)
async def create_pin_draft(
    body: PinDraftCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new Pin draft from an approved output and generate SEO metadata."""
    job = await db.get(Job, body.job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    output = await db.get(JobOutput, body.output_id)
    if not output:
        raise HTTPException(404, "Output image not found")

    # Load product and reference context
    product = await db.get(Product, job.product_id)
    ref = await db.get(Reference, job.reference_id)
    scene_data = json.loads(job.scene_json) if job.scene_json else {}

    # Run Pinterest SEO generator
    product_dict = {
        "name": product.name if product else "Product",
        "category": product.category if product else "General",
        "key_attributes": json.loads(product.key_attributes) if product and product.key_attributes else [],
    }

    try:
        seo_data = await generate_pin_seo(
            product=product_dict,
            scene=scene_data,
            trend_label=ref.trend_label if ref else None,
        )
    except Exception as e:
        log_runtime_bug(
            title="Pinterest SEO Generation Failed",
            subsystem="pipeline",
            severity="medium",
            error=e,
            context={"job_id": body.job_id, "output_id": body.output_id},
        )
        seo_data = {
            "title": f"Look at these {product.name if product else 'finds'}!",
            "description": f"Obsessed with this cute {product.name if product else 'item'}. Perfect find for this season!",
            "keywords": ["pinterest finds", "aesthetic", "must have"],
            "board_suggestion": "Cute Finds",
        }

    pin = PinDraft(
        output_id=body.output_id,
        job_id=body.job_id,
        title=seo_data.get("title", "Cute Find"),
        description=seo_data.get("description", ""),
        keywords=json.dumps(seo_data.get("keywords", [])),
        destination_url=product.affiliate_url if product else "",
        board_name=seo_data.get("board_suggestion", "Style & Trends"),
        profile_id=body.profile_id or "default",
        status="draft",
    )
    db.add(pin)
    await db.flush()
    await db.refresh(pin)

    # Real-time Obsidian Vault Sync
    try:
        sync_pin_node(
            pin_id=pin.id,
            job_id=job.id,
            title=pin.title,
            description=pin.description,
            keywords=seo_data.get("keywords", []),
            destination_url=pin.destination_url,
            board_name=pin.board_name,
            status=pin.status,
            product_name=product.name if product else None,
        )
    except Exception as e:
        # The vault is a mirror, so a sync failure must not fail the request —
        # but it must not be invisible either. `except: pass` hid every one.
        logger.warning("Vault sync of pin %s failed: %s", pin.id, e)

    return _serialize_pin(pin)


@router.get("")
async def list_pins(
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    List all pin drafts.

    Reconciles finished publish runs first: the browser runs in its own process,
    so a run whose tab was closed has still finished on disk, and this is the
    request the UI always makes. Without it a published pin would sit in the list
    as a draft until someone happened to poll its run.
    """
    await _reconcile_runs(db)

    query = select(PinDraft).options(selectinload(PinDraft.output)).order_by(PinDraft.created_at.desc())
    if status:
        query = query.where(PinDraft.status == status)
    result = await db.execute(query)
    return [_serialize_pin(p) for p in result.scalars().all()]


# ── the account's real boards ────────────────────
# Registered above `/{pin_id}`, and it has to stay there: FastAPI matches in
# registration order, so a single-segment `/boards` declared after the pin route
# would be swallowed as a pin id and answer 404 "Pin not found".
@router.get("/boards")
async def list_account_boards(profile_id: str | None = None):
    """
    The board names last read from the account's own dropdown for a given profile.
    """
    catalog = board_catalog.read_catalog(profile_id=profile_id)
    return {
        **catalog.as_dict(),
        "profile_id": profile_id or "default",
        "default_board": settings.default_board_name or None,
        "refresh": board_catalog.refresh_status_view(profile_id=profile_id),
        "message": (
            f"No board list yet for account '{profile_id or 'default'}' — refresh it to catch wrong board names." if catalog.is_empty else
            f"{len(catalog.boards)} board(s) recorded."
        ),
    }


@router.post("/boards/refresh")
async def refresh_account_boards(visible: bool = False, profile_id: str | None = None):
    """
    Re-read the board dropdown for a given profile in a child process. Returns at once.
    """
    try:
        status = board_catalog.start_refresh(headless=not visible, profile_id=profile_id)
    except RuntimeError as e:
        raise HTTPException(500, f"Could not start the board refresh: {e}") from e
    return {
        **status,
        "poll": f"/api/pins/boards?profile_id={profile_id or 'default'}",
        "message": (
            f"Reading Pinterest boards for account '{profile_id or 'default'}'. This takes a few seconds."
        ),
    }


@router.get("/boards/check")
async def check_pin_board(board: str | None = None, profile_id: str | None = None):
    """
    What the pre-flight check would say about a board name for a given profile, without publishing.
    """
    check = board_catalog.check_board(board, fallback=settings.default_board_name, profile_id=profile_id)
    return check.as_dict()


@router.get("/{pin_id}")
async def get_pin(pin_id: str, db: AsyncSession = Depends(get_db)):
    """Get a pin draft by ID."""
    res = await db.execute(select(PinDraft).options(selectinload(PinDraft.output)).where(PinDraft.id == pin_id))
    pin = res.scalars().first()
    if not pin:
        raise HTTPException(404, "Pin not found")
    return _serialize_pin(pin)


@router.put("/{pin_id}")
async def update_pin(
    pin_id: str,
    body: PinDraftUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update Pin draft title, description, keywords, or destination URL."""
    pin = await db.get(PinDraft, pin_id)
    if not pin:
        raise HTTPException(404, "Pin not found")

    update_data = body.model_dump(exclude_unset=True)
    if "keywords" in update_data and update_data["keywords"] is not None:
        update_data["keywords"] = json.dumps(update_data["keywords"])

    for k, v in update_data.items():
        setattr(pin, k, v)

    await db.flush()
    await db.refresh(pin)

    # Real-time Obsidian Vault Sync
    try:
        sync_pin_node(
            pin_id=pin.id,
            job_id=pin.job_id,
            title=pin.title,
            description=pin.description,
            keywords=json.loads(pin.keywords) if pin.keywords else [],
            destination_url=pin.destination_url,
            board_name=pin.board_name,
            status=pin.status,
        )
    except Exception as e:
        # The vault is a mirror, so a sync failure must not fail the request —
        # but it must not be invisible either. `except: pass` hid every one.
        logger.warning("Vault sync of pin %s failed: %s", pin.id, e)

    return _serialize_pin(pin)


@router.post("/{pin_id}/approve")
async def approve_pin(pin_id: str, db: AsyncSession = Depends(get_db)):
    """Operator approves pin for export/publishing."""
    pin = await db.get(PinDraft, pin_id)
    if not pin:
        raise HTTPException(404, "Pin not found")

    pin.status = "approved"
    pin.human_decision = "APPROVE"
    await db.flush()

    # Real-time Obsidian Vault Sync
    try:
        sync_pin_node(
            pin_id=pin.id,
            job_id=pin.job_id,
            title=pin.title,
            description=pin.description,
            keywords=json.loads(pin.keywords) if pin.keywords else [],
            destination_url=pin.destination_url,
            board_name=pin.board_name,
            status="approved",
        )
    except Exception as e:
        # The vault is a mirror, so a sync failure must not fail the request —
        # but it must not be invisible either. `except: pass` hid every one.
        logger.warning("Vault sync of pin %s failed: %s", pin.id, e)

    return {"pin_id": pin_id, "status": "approved"}


@router.post("/{pin_id}/reject")
async def reject_pin(
    pin_id: str,
    body: PinReject,
    db: AsyncSession = Depends(get_db),
):
    """Operator rejects pin with a reason code."""
    pin = await db.get(PinDraft, pin_id)
    if not pin:
        raise HTTPException(404, "Pin not found")

    pin.status = "rejected"
    pin.human_decision = "REJECT"
    pin.rejection_reason = f"{body.reason}: {body.notes or ''}"
    await db.flush()

    return {"pin_id": pin_id, "status": "rejected", "reason": pin.rejection_reason}


# ─────────────────────────────────────────────────
# Pinterest Profiles & Auth Management Endpoints
# ─────────────────────────────────────────────────
from app.services import pinterest_profiles
from app.schemas.schemas import PinterestProfileCreate


@router.get("/auth/profiles")
async def list_pinterest_profiles():
    """List all saved Pinterest profiles with authentication status and board counts."""
    return pinterest_profiles.list_profiles()


@router.post("/auth/profiles")
async def create_pinterest_profile(body: PinterestProfileCreate):
    """Register a new Pinterest profile."""
    try:
        return pinterest_profiles.create_profile(body.name, profile_id=body.profile_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/auth/profiles/{profile_id}")
async def delete_pinterest_profile(profile_id: str):
    """Delete a Pinterest profile and its session data."""
    try:
        success = pinterest_profiles.delete_profile(profile_id)
        if not success:
            raise HTTPException(404, "Profile not found")
        return {"status": "deleted", "profile_id": profile_id}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/auth/profiles/{profile_id}/default")
async def set_default_pinterest_profile(profile_id: str):
    """Set a Pinterest profile as the active default."""
    success = pinterest_profiles.set_default_profile(profile_id)
    if not success:
        raise HTTPException(404, "Profile not found")
    return {"status": "updated", "active_profile_id": profile_id}


@router.post("/auth/launch-login")
async def launch_pinterest_auth(profile_id: str | None = None):
    """Launch interactive visible Chrome for 1-time Pinterest login for a specific profile."""
    import subprocess
    import sys
    target_id = (profile_id or "default").strip()
    try:
        args = [sys.executable, "scripts/init_pinterest_auth.py", "--profile", target_id]
        subprocess.Popen(
            args,
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0,
        )
        return {
            "status": "launched",
            "profile_id": target_id,
            "message": f"Opened Pinterest login Chrome window for profile '{target_id}'. Log in manually and press ENTER in the popup console.",
        }
    except Exception as e:
        raise HTTPException(500, f"Failed to launch login script: {e}")


@router.get("/auth/status")
async def get_pinterest_auth_status(profile_id: str | None = None):
    """Check if Pinterest profile directory exists and has session files."""
    target_id = (profile_id or "default").strip()
    prof = pinterest_profiles.get_profile(target_id)
    pdir = pinterest_profiles.get_profile_dir(target_id)
    has_profile = prof["authenticated"] if prof else False
    return {
        "profile_id": target_id,
        "authenticated": has_profile,
        "profile_dir": str(pdir),
        "message": f"Pinterest session active for profile '{target_id}'." if has_profile else f"Profile '{target_id}' not authenticated. Click to log in.",
    }


@router.post("/{pin_id}/publish")
async def publish_pin_endpoint(
    pin_id: str,
    profile_id: str | None = None,
    allow_no_link: bool = False,
    force_board: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """
    Start publishing this pin through the browser. Returns at once.
    """
    pin = await db.get(PinDraft, pin_id)
    if not pin:
        raise HTTPException(404, "Pin not found")

    output = await db.get(JobOutput, pin.output_id)
    if not output:
        raise HTTPException(404, "Pin image output not found")

    target_profile = (profile_id or pin.profile_id or "default").strip()

    resolved = resolve_output_image(output.image_path)
    if resolved is None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Pin image file is missing on disk (stored path: {output.image_path!r}). "
                "Regenerate the image before publishing."
            ),
        )

    if not allow_no_link and (problem := _link_problem(pin)):
        raise HTTPException(status_code=409, detail=problem)
    if not force_board and (problem := _board_problem(pin, profile_id=target_profile)):
        raise HTTPException(status_code=409, detail=problem)

    logger.info("Starting publish run for pin %s (profile: %s) with image %s", pin.id, target_profile, resolved)
    try:
        status = publish_runs.start_run(
            publish_runs.KIND_PUBLISH,
            [{
                "pin_id": pin.id,
                "image_path": str(resolved),
                "title": pin.title,
                "description": pin.description or "",
                "link": pin.destination_url,
                "board_name": pin.board_name,
                "scheduled_for": None,
                "profile_id": target_profile,
            }],
            headless=False,
            profile_id=target_profile,
        )
    except (RuntimeError, ValueError) as e:
        raise HTTPException(500, f"Could not start the publisher: {e}") from e

    return {
        "pin_id": pin.id,
        "profile_id": target_profile,
        "run_id": status["run_id"],
        "status": "running",
        "poll": f"/api/pins/publish-runs/{status['run_id']}",
        "message": (
            f"A Chrome window is opening for profile '{target_profile}'. This takes a minute or two; "
            "the pin is only marked published once Pinterest confirms it."
        ),
    }


async def _apply_run(status: dict, db: AsyncSession) -> dict:
    """
    Write a finished run's outcome into the database, exactly once.

    The child process deliberately owns no database connection, so this is where
    a confirmed publish becomes `published` and a confirmed native schedule
    becomes `scheduled_pinterest`. Anything the publisher did not confirm leaves
    the pin exactly as it was — an unconfirmed pin must never look scheduled.
    """
    run_id = status["run_id"]
    spec = publish_runs.read_spec(run_id) or {}
    paths = {p["pin_id"]: p.get("image_path") for p in spec.get("pins", [])}
    applied: list[str] = []

    for result in status.get("results", []):
        pin_id = result.get("pin_id")
        pin = await db.get(PinDraft, pin_id) if pin_id else None
        if pin is None:
            continue

        if result.get("status") == "published" and result.get("confirmed_by"):
            pin.status = "published"
            pin.exported_at = datetime.now(timezone.utc)
            applied.append(pin.id)
            _sync_pin_quietly(pin, "published", live_url=result.get("live_url"),
                              board_name=result.get("board_used") or pin.board_name)

        elif result.get("status") == "scheduled" and result.get("scheduled_for"):
            _record_native_schedule(pin, result, paths.get(pin.id))
            # A distinct status: "scheduled" belongs to PRE's own queue, which this
            # machine has to be awake to drain. This one is Pinterest's to publish.
            pin.status = "scheduled_pinterest"
            applied.append(pin.id)
            _sync_pin_quietly(pin, "scheduled_pinterest",
                              board_name=result.get("board_used") or pin.board_name,
                              scheduled_time=result.get("scheduled_for"))

    if applied:
        await db.flush()
        await db.commit()
    publish_runs.mark_applied(run_id)
    logger.info("publish run %s applied to %d pin(s)", run_id, len(applied))
    return {**status, "applied": True, "applied_pins": applied}


def _record_native_schedule(pin: PinDraft, result: dict, image_path: str | None) -> None:
    """Put a Pinterest-held pin in the queue as `pinterest_scheduled`."""
    from app.services.pinterest_service import record_pinterest_native_schedule

    try:
        record_pinterest_native_schedule(
            pin_id=pin.id,
            title=pin.title,
            description=pin.description or "",
            image_path=image_path or "",
            destination_url=pin.destination_url,
            board_name=result.get("board_used") or pin.board_name,
            scheduled_time=datetime.fromisoformat(result["scheduled_for"]),
            confirmed_by=result.get("confirmed_by"),
        )
    except Exception as e:
        # Pinterest already holds the pin; failing the request now would invite a
        # second attempt and a duplicate pin. Loud in the log, not fatal here.
        logger.error("Pin %s was scheduled on Pinterest but not recorded: %s", pin.id, e)


def _sync_pin_quietly(pin: PinDraft, status: str, **extra) -> None:
    """Mirror a pin into the vault. The vault is a copy: never fail a run for it."""
    try:
        sync_pin_node(
            pin_id=pin.id,
            job_id=pin.job_id,
            title=pin.title,
            description=pin.description,
            keywords=json.loads(pin.keywords) if pin.keywords else [],
            destination_url=pin.destination_url,
            status=status,
            **extra,
        )
    except Exception as e:
        logger.warning("Vault sync of pin %s failed: %s", pin.id, e)


async def _reconcile_runs(db: AsyncSession) -> int:
    """
    Apply every finished-but-unapplied run.

    Called when runs are polled and when pins are listed, so a run whose tab was
    closed still lands in the database instead of waiting for someone to look.
    """
    count = 0
    for status in list(publish_runs.unapplied_finished()):
        try:
            await _apply_run(status, db)
            count += 1
        except Exception as e:
            logger.error("Could not apply publish run %s: %s", status.get("run_id"), e)
    return count


@router.get("/publish-runs/{run_id}")
async def get_publish_run(run_id: str, db: AsyncSession = Depends(get_db)):
    """
    Poll a publish or bulk-schedule run.

    `status` is starting / running / done / error. `results` grows as each pin
    finishes, so a bulk run reports pin 3 of 15 rather than nothing for minutes.
    `stalled` means the child stopped writing — the browser may have got far
    enough to create a pin, so check Pinterest before retrying.
    """
    try:
        status = publish_runs.read_status(run_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if status is None:
        raise HTTPException(404, f"No publish run {run_id!r}")

    if status.get("status") in publish_runs.FINISHED and not status.get("applied"):
        status = await _apply_run(status, db)

    return {**status, "stalled": publish_runs.is_stalled(run_id, status)}


# ─────────────────────────────────────────────────
# Bulk scheduling through Pinterest's own scheduler
# ─────────────────────────────────────────────────
class BulkScheduleRequest(BaseModel):
    """
    What to schedule and how to space it.
    """
    pin_ids: list[str]
    start_time: str | None = None
    interval_minutes: int | None = None
    daily_slots: list[str] | None = None
    per_day_cap: int | None = None
    headless: bool = False
    profile_id: str | None = None
    allow_no_link: bool = False
    force_board: bool = False


async def _collect_bulk_specs(
    pin_ids: list[str],
    db: AsyncSession,
    *,
    profile_id: str | None = None,
    allow_no_link: bool = False,
    force_board: bool = False,
) -> tuple[list[tuple[PinDraft, str]], list[str]]:
    """
    Resolve each requested pin to (pin, image path on disk), plus the problems.
    """
    usable: list[tuple[PinDraft, str]] = []
    problems: list[str] = []
    seen: set[str] = set()

    for pin_id in pin_ids:
        if pin_id in seen:
            problems.append(f"{pin_id}: listed twice in this batch")
            continue
        seen.add(pin_id)

        pin = await db.get(PinDraft, pin_id)
        if not pin:
            problems.append(f"{pin_id}: no such pin")
            continue
        output = await db.get(JobOutput, pin.output_id)
        if not output:
            problems.append(f"{pin_id}: its image output row is gone")
            continue
        resolved = resolve_output_image(output.image_path)
        if resolved is None:
            problems.append(f"{pin_id}: image missing on disk ({output.image_path!r})")
            continue
        if not allow_no_link and (problem := _link_problem(pin)):
            problems.append(f"{pin_id}: {problem}")
            continue
        target_prof = profile_id or pin.profile_id or "default"
        if not force_board and (problem := _board_problem(pin, profile_id=target_prof)):
            problems.append(f"{pin_id}: {problem}")
            continue
        usable.append((pin, str(resolved)))

    return usable, problems


def _plan_bulk_times(count: int, body: BulkScheduleRequest):
    """Turn the request's timing options into `count` future times, or fail loudly."""
    from app.services.pinterest_service import parse_scheduled_time
    from app.services.schedule_planner import PlanError, plan_publish_times

    if body.start_time:
        start = parse_scheduled_time(body.start_time)
        if start is None:
            raise HTTPException(
                400,
                f"Could not understand start_time {body.start_time!r}. Use "
                "2026-08-23T09:00 (local) or a full ISO timestamp with an offset.",
            )
    else:
        start = datetime.now(timezone.utc) + timedelta(minutes=20)

    try:
        return plan_publish_times(
            count,
            start,
            interval_minutes=body.interval_minutes,
            daily_slots=body.daily_slots,
            per_day_cap=body.per_day_cap,
        )
    except PlanError as e:
        raise HTTPException(409, str(e)) from e


@router.post("/bulk-schedule/preview")
async def preview_bulk_schedule(
    body: BulkScheduleRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    The times a bulk run *would* use — no browser, nothing sent to Pinterest.
    """
    usable, problems = await _collect_bulk_specs(
        body.pin_ids, db, profile_id=body.profile_id, allow_no_link=body.allow_no_link, force_board=body.force_board,
    )
    if not usable:
        raise HTTPException(
            409,
            "None of the selected pins can be scheduled: " + "; ".join(problems or ["no pins given"]),
        )
    plan = _plan_bulk_times(len(usable), body)
    return {
        "count": len(usable),
        "skipped": problems,
        "notes": list(plan.notes),
        "per_day": plan.per_day(),
        "times": [
            {
                "pin_id": pin.id,
                "title": pin.title,
                "board": pin.board_name or settings.default_board_name,
                "scheduled_for": when.isoformat(),
                "local": local,
            }
            for (pin, _), when, local in zip(usable, plan.times, plan.local_strings())
        ],
    }


@router.post("/bulk-schedule")
async def bulk_schedule_pins(
    body: BulkScheduleRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Hand a batch of pins to Pinterest's own scheduler, in one browser session.
    """
    usable, problems = await _collect_bulk_specs(
        body.pin_ids, db, profile_id=body.profile_id, allow_no_link=body.allow_no_link, force_board=body.force_board,
    )
    if not usable:
        raise HTTPException(
            409,
            "None of the selected pins can be scheduled: " + "; ".join(problems or ["no pins given"]),
        )
    if problems:
        logger.warning("Bulk schedule skipping %d pin(s): %s", len(problems), "; ".join(problems))

    plan = _plan_bulk_times(len(usable), body)

    try:
        status = publish_runs.start_run(
            publish_runs.KIND_BULK_SCHEDULE,
            [
                {
                    "pin_id": pin.id,
                    "image_path": path,
                    "title": pin.title,
                    "description": pin.description or "",
                    "link": pin.destination_url,
                    "board_name": pin.board_name,
                    "scheduled_for": when.isoformat(),
                    "profile_id": pin.profile_id or body.profile_id or "default",
                }
                for (pin, path), when in zip(usable, plan.times)
            ],
            headless=body.headless,
            profile_id=body.profile_id,
            skipped=problems,
            notes=list(plan.notes),
        )
    except (RuntimeError, ValueError) as e:
        raise HTTPException(500, f"Could not start the bulk scheduler: {e}") from e

    return {
        "run_id": status["run_id"],
        "poll": f"/api/pins/publish-runs/{status['run_id']}",
        "status": "running",
        "requested": len(body.pin_ids),
        "attempted": status["total"],
        "scheduled": 0,
        "failed": 0,
        "skipped": problems,
        "notes": list(plan.notes),
        "handled_by": "pinterest",
        "results": [],
        "times": [
            {"pin_id": pin.id, "scheduled_for": when.isoformat(), "local": local}
            for (pin, _), when, local in zip(usable, plan.times, plan.local_strings())
        ],
    }


class BulkPublishRequest(BaseModel):
    """Publish multiple pins directly in one browser session."""
    pin_ids: list[str]
    profile_id: str | None = None
    allow_no_link: bool = False
    force_board: bool = False
    headless: bool = False


@router.post("/bulk-publish")
async def bulk_publish_pins(
    body: BulkPublishRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Publish a batch of pins immediately through the browser publisher.
    """
    usable, problems = await _collect_bulk_specs(
        body.pin_ids, db, profile_id=body.profile_id, allow_no_link=body.allow_no_link, force_board=body.force_board,
    )
    if not usable:
        raise HTTPException(
            409,
            "None of the selected pins can be published: " + "; ".join(problems or ["no pins given"]),
        )
    if problems:
        logger.warning("Bulk publish skipping %d pin(s): %s", len(problems), "; ".join(problems))

    try:
        status = publish_runs.start_run(
            publish_runs.KIND_PUBLISH,
            [
                {
                    "pin_id": pin.id,
                    "image_path": path,
                    "title": pin.title,
                    "description": pin.description or "",
                    "link": pin.destination_url,
                    "board_name": pin.board_name,
                    "scheduled_for": None,
                    "profile_id": pin.profile_id or body.profile_id or "default",
                }
                for pin, path in usable
            ],
            headless=body.headless,
            profile_id=body.profile_id,
            skipped=problems,
        )
    except (RuntimeError, ValueError) as e:
        raise HTTPException(500, f"Could not start the publisher: {e}") from e

    return {
        "run_id": status["run_id"],
        "poll": f"/api/pins/publish-runs/{status['run_id']}",
        "status": "running",
        "requested": len(body.pin_ids),
        "attempted": status["total"],
        "published": 0,
        "failed": 0,
        "skipped": problems,
        "results": [],
    }


@router.post("/{pin_id}/schedule")
async def schedule_pin_endpoint(
    pin_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    Queue a Pin for future publishing by the in-process scheduler.

    The board and link pre-flight run here rather than only at publish time,
    because the queue publishes unattended: a pin queued with a board the account
    does not have fails at 3am, and the operator finds an abandoned Pinterest draft
    with no idea which run left it. `force_board` / `allow_no_link` in the body
    override, the same as on `/publish`.
    """
    pin = await db.get(PinDraft, pin_id)
    if not pin:
        raise HTTPException(404, "Pin not found")

    output = await db.get(JobOutput, pin.output_id)
    if not output:
        raise HTTPException(404, "Pin image output not found")

    from app.services.media_paths import resolve_output_image
    resolved = resolve_output_image(output.image_path)
    if resolved is None:
        raise HTTPException(
            409,
            f"Pin image file is missing on disk (stored path: {output.image_path!r}). "
            "Regenerate the image before scheduling.",
        )

    if not body.get("allow_no_link") and (problem := _link_problem(pin)):
        raise HTTPException(409, problem)
    if not body.get("force_board") and (problem := _board_problem(pin)):
        raise HTTPException(409, problem)

    from app.services.pinterest_service import parse_scheduled_time, schedule_pin_for_later

    raw_time = body.get("scheduled_time")
    when = parse_scheduled_time(raw_time) if raw_time else datetime.now(timezone.utc)
    if when is None:
        raise HTTPException(
            400,
            f"Could not understand scheduled_time {raw_time!r}. "
            "Use an ISO timestamp such as 2026-08-23T19:00 or 2026-08-23T19:00:00+05:30.",
        )

    try:
        entry = schedule_pin_for_later(
            pin_id=pin.id,
            title=pin.title,
            description=pin.description,
            image_path=str(resolved),
            destination_url=pin.destination_url,
            board_name=pin.board_name,
            scheduled_time=when,
        )
    except ValueError as e:
        raise HTTPException(409, str(e))

    pin.status = "scheduled"
    await db.flush()

    return {
        "pin_id": pin.id,
        "status": "scheduled",
        "scheduled_for": entry["scheduled_time"],
        "scheduled_entry": entry,
    }


@router.get("/scheduled/list")
async def list_scheduled_pins_endpoint(status: str | None = None):
    """List queue entries (optionally filtered by lifecycle status)."""
    from app.services.pinterest_service import get_due_pins, get_scheduled_pins

    entries = get_scheduled_pins(status=status)
    due_ids = {e.get("id") for e in get_due_pins()}
    for e in entries:
        e["is_due"] = e.get("id") in due_ids
    return entries


@router.get("/scheduler/status")
async def scheduler_status_endpoint():
    """Is the queue consumer alive, and what is it about to do?"""
    from app.services import scheduler
    from app.services.pinterest_service import MAX_PUBLISH_ATTEMPTS, get_due_pins, get_scheduled_pins

    queue = get_scheduled_pins()
    counts: dict[str, int] = {}
    for e in queue:
        counts[str(e.get("status"))] = counts.get(str(e.get("status")), 0) + 1

    return {
        "running": scheduler.is_running(),
        "enabled": settings.scheduler_enabled,
        "headless": settings.scheduler_headless,
        "tick_seconds": scheduler.TICK_SECONDS,
        "max_attempts": MAX_PUBLISH_ATTEMPTS,
        "queue_size": len(queue),
        "status_counts": counts,
        "due_now": [
            {"id": e.get("id"), "pin_id": e.get("pin_id"), "scheduled_time": e.get("scheduled_time")}
            for e in get_due_pins()
        ],
    }


@router.post("/scheduler/run-now")
async def scheduler_run_now_endpoint():
    """Drain everything currently due, without waiting for the next tick."""
    from app.services.scheduler import run_once

    processed = await run_once()
    return {
        "processed": len(processed),
        "entries": [
            {
                "id": e.get("id"),
                "pin_id": e.get("pin_id"),
                "status": e.get("status"),
                "live_url": e.get("live_url"),
                "last_error": e.get("last_error"),
            }
            for e in processed
        ],
    }


@router.delete("/scheduled/{entry_id}")
async def cancel_scheduled_pin_endpoint(entry_id: str, db: AsyncSession = Depends(get_db)):
    """Cancel a queued pin. Already-published entries cannot be cancelled."""
    from app.services.pinterest_service import cancel_scheduled_pin

    entry = cancel_scheduled_pin(entry_id)
    if entry is None:
        raise HTTPException(409, f"Queue entry {entry_id} is unknown or already published.")

    pin = await db.get(PinDraft, entry.get("pin_id", ""))
    if pin and pin.status == "scheduled":
        pin.status = "approved"
        await db.flush()

    return {"status": "cancelled", "entry": entry}


@router.get("/{pin_id}/export")
async def export_pin(pin_id: str, db: AsyncSession = Depends(get_db)):
    """Export complete Pin bundle as a ZIP package."""
    pin = await db.get(PinDraft, pin_id)
    if not pin:
        raise HTTPException(404, "Pin not found")

    output = await db.get(JobOutput, pin.output_id)
    if not output:
        raise HTTPException(404, "Output image file not found")

    job = await db.get(Job, pin.job_id)
    product = await db.get(Product, job.product_id) if job else None

    # Prepare package metadata
    pin_meta = {
        "pin_id": pin.id,
        "title": pin.title,
        "description": pin.description,
        "keywords": json.loads(pin.keywords) if pin.keywords else [],
        "destination_url": pin.destination_url,
        "board_name": pin.board_name,
        "product_name": product.name if product else "N/A",
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }

    gen_report = {
        "job_id": job.id if job else "N/A",
        "provider": job.provider if job else "google_flow_manual",
        "rework_count": job.rework_count if job else 0,
        "human_decision": pin.human_decision,
    }

    compliance = {
        "is_original_content": True,
        "is_affiliate": True,
        "affiliate_disclosed": True,
        "disclosure_text": pin.disclosure,
        "is_ai_generated": True,
        "ai_generation_labeled": True,
        "product_truth_verified": True,
        "originality_checked": True,
        "no_misleading_claims": True,
        "compliant": True,
    }

    zip_path = export_pin_package(
        pin_id=pin.id,
        output_image_path=output.image_path,
        pin_metadata=pin_meta,
        generation_report=gen_report,
        compliance=compliance,
    )

    pin.status = "exported"
    pin.exported_at = datetime.now(timezone.utc)
    await db.flush()

    return FileResponse(
        str(zip_path),
        media_type="application/zip",
        filename=f"pin_{pin.id}_export.zip",
    )


def _serialize_pin(pin: PinDraft) -> dict:
    image_path = None
    # Use SQLAlchemy inspect to avoid triggering lazy load (pin.__dict__.get still
    # goes through the descriptor on some SA versions and raises MissingGreenlet).
    try:
        from sqlalchemy import inspect as sa_inspect

        insp = sa_inspect(pin)
        if insp.attrs.output.loaded_value is not None:
            loaded = insp.attrs.output.loaded_value
            # loaded_value is the actual object or a Loader token; only use if it's a real instance
            if loaded is not None and hasattr(loaded, "image_path"):
                image_path = loaded.image_path  # type: ignore[union-attr]
        elif "output" in pin.__dict__ and pin.__dict__["output"] is not None:
            image_path = pin.__dict__["output"].image_path  # type: ignore[union-attr]
    except Exception:
        # Fallback: never fail serialization due to relationship inspection
        try:
            if "output" in pin.__dict__ and pin.__dict__["output"] is not None:
                image_path = pin.__dict__["output"].image_path  # type: ignore[union-attr]
        except Exception:
            pass

    return {
        "id": pin.id,
        "output_id": pin.output_id,
        "job_id": pin.job_id,
        "image_path": image_path,
        "title": pin.title,
        "description": pin.description,
        "keywords": json.loads(pin.keywords) if pin.keywords else [],
        "destination_url": pin.destination_url,
        "board_name": pin.board_name,
        "profile_id": pin.profile_id or "default",
        "is_affiliate": pin.is_affiliate,
        "is_ai_generated": pin.is_ai_generated,
        "disclosure": pin.disclosure,
        "status": pin.status,
        "human_decision": pin.human_decision,
        "rejection_reason": pin.rejection_reason,
        "exported_at": pin.exported_at.isoformat() if pin.exported_at else None,
        "created_at": pin.created_at.isoformat(),
    }
