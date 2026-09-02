"""
Pinterest Realism Engine — Generation Job Reaper.

Rescues jobs stuck in `GENERATING` state due to process termination,
system crash/reboot, machine sleep, or Playwright browser hangs.
Runs on startup and periodically in the scheduler loop.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.models import Job
from app.services.job_service import validate_transition

logger = logging.getLogger("pre.job_reaper")


def is_pid_alive(pid: int) -> bool:
    """
    Check if a process with the given PID is currently active and running.
    Cross-platform without external dependencies (ctypes on Windows, os.kill on POSIX).
    """
    if pid <= 0:
        return False

    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            SYNCHRONIZE = 0x00100000
            handle = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid
            )
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    STILL_ACTIVE = 259
                    return exit_code.value == STILL_ACTIVE
                return False
            finally:
                kernel32.CloseHandle(handle)
        except Exception as e:
            logger.debug("Error checking Windows PID %s: %s", pid, e)
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


async def reap_stalled_jobs(
    db: AsyncSession,
    stall_minutes: int | None = None,
) -> list[str]:
    """
    Find jobs in `GENERATING` state whose runner process has died or whose status
    has not been updated within `generation_stall_minutes`, and mark them `FAILED`.

    Uses `validate_transition("GENERATING", "FAILED")` and updates `status.json`
    so the UI can immediately display the error and allow one-click retry.

    Returns:
        List of reaped job IDs.
    """
    timeout_mins = (
        stall_minutes
        if stall_minutes is not None
        else getattr(settings, "generation_stall_minutes", 30)
    )

    query = select(Job).where(Job.current_state == "GENERATING")
    result = await db.execute(query)
    generating_jobs = result.scalars().all()

    if not generating_jobs:
        return []

    reaped_ids: list[str] = []
    now_ts = time.time()

    for job in generating_jobs:
        status_file = (settings.outputs_path / job.id / "status.json").resolve()
        is_stalled = False
        reason = ""
        status_data: dict[str, Any] = {}

        if not status_file.exists():
            # If status.json does not exist, check how old the job record is
            if job.created_at:
                created_utc = (
                    job.created_at
                    if job.created_at.tzinfo
                    else job.created_at.replace(tzinfo=timezone.utc)
                )
                age_mins = (datetime.now(timezone.utc) - created_utc).total_seconds() / 60.0
                if age_mins > timeout_mins:
                    is_stalled = True
                    reason = (
                        f"Generation process never created status file after {age_mins:.0f} minutes. "
                        "Job marked FAILED so it can be retried."
                    )
        else:
            try:
                status_data = json.loads(status_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                logger.warning("Unreadable status.json for job %s: %s", job.id, e)
                status_data = {}

            current_status = status_data.get("status", "generating")
            if current_status in ("generating", "saving"):
                mtime = status_file.stat().st_mtime
                age_mins = (now_ts - mtime) / 60.0

                pid_raw = status_data.get("pid")
                pid = int(pid_raw) if pid_raw and str(pid_raw).isdigit() else None

                if pid is not None:
                    if not is_pid_alive(pid):
                        is_stalled = True
                        reason = (
                            f"Background runner process (PID {pid}) died unexpectedly. "
                            f"No progress for {age_mins:.0f} minutes. Job marked FAILED for retry."
                        )
                    elif age_mins > timeout_mins:
                        is_stalled = True
                        reason = (
                            f"Background run stalled: process (PID {pid}) exceeded time limit of "
                            f"{timeout_mins} minutes (inactive for {age_mins:.0f}m). "
                            "Job marked FAILED for retry."
                        )
                elif age_mins > timeout_mins:
                    is_stalled = True
                    reason = (
                        f"Background run stalled: no status update for {age_mins:.0f} minutes "
                        f"(threshold: {timeout_mins}m). Job marked FAILED for retry."
                    )

        if is_stalled:
            try:
                validate_transition(job.current_state, "FAILED")
                job.current_state = "FAILED"
                job.failure_reason = reason
                reaped_ids.append(job.id)

                # Update status.json so polling endpoints reflect failure immediately
                status_data["status"] = "error"
                status_data["error"] = reason
                try:
                    status_file.parent.mkdir(parents=True, exist_ok=True)
                    status_file.write_text(
                        json.dumps(status_data, indent=2), encoding="utf-8"
                    )
                except OSError as write_err:
                    logger.warning("Could not write reaped status for job %s: %s", job.id, write_err)

                logger.info("Reaper marked job %s FAILED: %s", job.id, reason)
            except Exception as e:
                logger.error("Failed to transition stalled job %s to FAILED: %s", job.id, e)

    if reaped_ids:
        await db.commit()
        logger.warning(
            "Reaper swept and recovered %d stalled generation job(s): %s",
            len(reaped_ids),
            reaped_ids,
        )

    return reaped_ids
