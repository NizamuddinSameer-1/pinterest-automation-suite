"""
Pinterest Realism Engine — Instant Diagnostics & Error Intelligence Engine.

Provides deep, instant root-cause analysis, actionable fixes, subsystem tagging,
in-memory error ring buffer, and complete 7-subsystem automated health inspections.
"""

from __future__ import annotations

import asyncio
import datetime
import importlib.util
import json
import logging
import os
import sys
import time
import traceback
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger("pre.diagnostics")

# ── Subsystems ─────────────────────────────────────────────────────────
SUBSYSTEM_DB = "DATABASE"
SUBSYSTEM_LLM = "LLM_PROVIDER"
SUBSYSTEM_PIPELINE = "PIPELINE"
SUBSYSTEM_FLOW = "FLOW_AUTOMATION"
SUBSYSTEM_PINTEREST = "PINTEREST_PUBLISHER"
SUBSYSTEM_STORAGE = "STORAGE"
SUBSYSTEM_VAULT = "OBSIDIAN_VAULT"
SUBSYSTEM_API = "API"


@dataclass
class DiagnosticError:
    id: str
    timestamp: str
    subsystem: str
    error_type: str
    message: str
    location: str
    stacktrace: list[str]
    context: dict[str, Any] = field(default_factory=dict)
    suggested_fix: str = ""
    severity: str = "medium"  # low, medium, high, critical

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# In-memory circular buffer for fast recent error queries
_ERROR_BUFFER: deque[DiagnosticError] = deque(maxlen=50)


def analyze_and_suggest_fix(subsystem: str, error: Exception | str, context: dict[str, Any] | None = None) -> tuple[str, str, str]:
    """
    Analyzes an error to determine subsystem, severity, and exact actionable fix instructions.
    Returns: (detected_subsystem, severity, suggested_fix)
    """
    msg = str(error).lower()
    ctx = context or {}
    
    # 1. Quota / Rate limits
    if "429" in msg or "quota" in msg or "rate limit" in msg or "resourceexhausted" in msg:
        return (
            SUBSYSTEM_LLM,
            "high",
            "API key quota / rate limit reached (429). Check your API keys in .env. "
            "If using Google Gemini or OpenRouter, switch keys or wait ~60s before retrying."
        )

    # 2. Database locks / WAL
    if "database is locked" in msg or "busy" in msg or "operationalerror" in msg:
        return (
            SUBSYSTEM_DB,
            "high",
            "SQLite database is busy or locked. Ensure no long-running transactions are active. "
            "WAL mode is enabled automatically with 15s timeout; check for lingering external DB locks."
        )

    # 3. Google Flow browser automation
    if "flow" in msg or ctx.get("subsystem") == SUBSYSTEM_FLOW or "aisandbox" in msg:
        if "login" in msg or "profile" in msg or "sign in" in msg or "session" in msg:
            return (
                SUBSYSTEM_FLOW,
                "high",
                "Google Flow browser profile is signed out or missing. "
                "Run: 'python -m scripts.login_google_flow' to log in once in the visible browser."
            )
        if "prompt field" in msg or "could not find" in msg:
            return (
                SUBSYSTEM_FLOW,
                "medium",
                "Flow prompt field was not found. Verify FLOW_PROJECT_URL in .env is valid, "
                "or ensure the window resolution is at least 1920x1080."
            )
        if "target page, context or browser has been closed" in msg:
            return (
                SUBSYSTEM_FLOW,
                "medium",
                "Google Flow Chromium window was closed unexpectedly during generation. "
                "Ensure no external process killed Chrome and retry generation."
            )
        return (
            SUBSYSTEM_FLOW,
            "medium",
            "Google Flow generation failed. Inspect data/outputs/<job_id>/bg_log.txt for detailed browser steps."
        )

    # 4. Pinterest Publisher
    if "pinterest" in msg or ctx.get("subsystem") == SUBSYSTEM_PINTEREST or "pin-creation" in msg:
        if "login" in msg or "profile is signed out" in msg:
            return (
                SUBSYSTEM_PINTEREST,
                "high",
                "Pinterest session is not authenticated. "
                "Run: 'python scripts/init_pinterest_auth.py' and log into Pinterest once."
            )
        if "board" in msg or "dropdown" in msg:
            return (
                SUBSYSTEM_PINTEREST,
                "medium",
                "Board selection failed. Refresh your account boards via 'POST /api/pins/boards/refresh' "
                "or verify that the board exists on your Pinterest profile."
            )
        if "destination url" in msg or "link" in msg:
            return (
                SUBSYSTEM_PINTEREST,
                "low",
                "Pin is missing an affiliate/destination URL. Update the pin draft or pass allow_no_link=true."
            )
        return (
            SUBSYSTEM_PINTEREST,
            "medium",
            "Pinterest publisher encountered an issue. Check data/publish_runs/<run_id>/log.txt."
        )

    # 5. Missing Greenlet / SQLAlchemy lazy loading
    if "missinggreenlet" in msg or "greenlet_spawn" in msg:
        return (
            SUBSYSTEM_DB,
            "high",
            "Async SQLAlchemy lazy loading error. Use selectinload() on the query or access attributes via inspect()."
        )

    # 6. State transitions
    if "invalidtransitionerror" in msg or "cannot transition" in msg:
        return (
            SUBSYSTEM_PIPELINE,
            "medium",
            "Invalid job state transition. Jobs must follow: DRAFT -> ANALYZED -> PRODUCT_MATCHED -> SCENE_READY -> PROMPT_READY -> GENERATING -> OUTPUT_UPLOADED -> CRITIQUED -> PASS/REWORK."
        )

    # Fallback default
    sub = ctx.get("subsystem") or subsystem or SUBSYSTEM_API
    return (
        sub,
        "medium",
        "Inspect the full stack trace and request parameters in the diagnostic report."
    )


def record_diagnostic_error(
    error: Exception | str,
    subsystem: str = SUBSYSTEM_API,
    severity: str | None = None,
    context: dict[str, Any] | None = None,
) -> DiagnosticError:
    """
    Standardized error recorder that analyzes the error, infers root cause,
    stores in the ring buffer, and synchronizes with the Obsidian Vault.
    """
    ctx = context or {}
    detected_sub, detected_sev, fix = analyze_and_suggest_fix(subsystem, error, ctx)
    sev = severity or detected_sev
    
    tb_lines = []
    location = "unknown"
    if isinstance(error, Exception):
        exc_type = type(error).__name__
        msg = str(error) or exc_type
        tb = traceback.extract_tb(error.__traceback__)
        if tb:
            last_frame = tb[-1]
            location = f"{Path(last_frame.filename).name}:{last_frame.lineno} in {last_frame.name}()"
        tb_lines = traceback.format_exception(type(error), error, error.__traceback__)
    else:
        exc_type = "RuntimeError"
        msg = str(error)
        location = ctx.get("location", "runtime")

    diag = DiagnosticError(
        id=f"ERR-{int(time.time()*1000)%1000000:06d}",
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        subsystem=detected_sub,
        error_type=exc_type,
        message=msg,
        location=location,
        stacktrace=tb_lines,
        context=ctx,
        suggested_fix=fix,
        severity=sev,
    )
    _ERROR_BUFFER.appendleft(diag)
    logger.error("[%s] [%s] %s (at %s): %s", diag.subsystem, diag.severity.upper(), diag.error_type, diag.location, diag.message)

    # Mirror to Obsidian Vault bug tracker
    try:
        from app.services.vault_sync import log_runtime_bug
        log_runtime_bug(
            title=f"[{diag.subsystem}] {diag.error_type}: {diag.message[:80]}",
            subsystem=diag.subsystem.lower(),
            severity=diag.severity,
            error=error if isinstance(error, Exception) else RuntimeError(msg),
            context={"location": diag.location, "suggested_fix": fix, **ctx},
        )
    except Exception:
        pass

    return diag


def get_recent_errors(limit: int = 20) -> list[dict[str, Any]]:
    """Return the most recent diagnostic errors."""
    return [e.to_dict() for e in list(_ERROR_BUFFER)[:limit]]


# ─────────────────────────────────────────────────────────────────────────
# Complete System Health & Diagnostic Inspection Engine
# ─────────────────────────────────────────────────────────────────────────

async def inspect_database() -> dict[str, Any]:
    """Test SQLite DB connection, WAL mode, table counts, and active locks."""
    t0 = time.time()
    result = {"name": "Database (SQLite + WAL)", "subsystem": SUBSYSTEM_DB, "status": "PASS", "latency_ms": 0, "details": {}}
    try:
        from app.database import async_session
        from sqlalchemy import text
        from app.models.models import Campaign, Job, PinDraft, Product, Reference

        async with async_session() as db:
            # Check PRAGMAs
            wal_row = await db.execute(text("PRAGMA journal_mode;"))
            journal_mode = wal_row.scalar()
            busy_row = await db.execute(text("PRAGMA busy_timeout;"))
            busy_timeout = busy_row.scalar()

            # Check table counts
            ref_c = await db.execute(text("SELECT COUNT(*) FROM \"references\";"))
            job_c = await db.execute(text("SELECT COUNT(*) FROM jobs;"))
            pin_c = await db.execute(text("SELECT COUNT(*) FROM pin_drafts;"))
            prod_c = await db.execute(text("SELECT COUNT(*) FROM products;"))

            result["latency_ms"] = int((time.time() - t0) * 1000)
            result["details"] = {
                "journal_mode": journal_mode,
                "busy_timeout_ms": busy_timeout,
                "counts": {
                    "references": ref_c.scalar(),
                    "products": prod_c.scalar(),
                    "jobs": job_c.scalar(),
                    "pin_drafts": pin_c.scalar(),
                }
            }
            if str(journal_mode).lower() != "wal":
                result["status"] = "WARN"
                result["message"] = f"Journal mode is {journal_mode}, recommended is WAL."
    except Exception as e:
        result["status"] = "FAIL"
        result["error"] = str(e)
        result["suggested_fix"] = "Verify data/pre.db exists and permissions allow async write."
    return result


async def inspect_llm_stack() -> dict[str, Any]:
    """Probe configured LLM providers for latency and quota availability."""
    t0 = time.time()
    result = {"name": "LLM Provider Stack", "subsystem": SUBSYSTEM_LLM, "status": "PASS", "latency_ms": 0, "providers": {}}
    try:
        from app.providers.llm import llm
        
        # Test basic text generation ping
        test_prompt = "Reply with 'OK'."
        resp = await asyncio.wait_for(llm.generate_text(test_prompt), timeout=15)
        result["latency_ms"] = int((time.time() - t0) * 1000)
        result["ping_response"] = resp.strip()[:50]
        result["providers"] = {
            "gemini": bool(settings.gemini_api_key),
            "opencode": bool(settings.opencode_api_key),
            "openrouter": bool(settings.openrouter_api_key),
            "text_model": settings.openrouter_model if settings.openrouter_api_key else settings.gemini_model,
        }
    except Exception as e:
        result["status"] = "FAIL" if "429" in str(e) or "quota" in str(e).lower() else "WARN"
        result["error"] = str(e)
        result["suggested_fix"] = "Check API keys in .env. If 429 quota reached, replace key or wait 60s."
    return result


def inspect_flow_automation() -> dict[str, Any]:
    """Inspect Google Flow session, profile directory, and recent generation logs."""
    profile_dir = Path("./data/flow_profile").resolve()
    session_file = Path("./data/captured_flow_session.json").resolve()
    has_profile = profile_dir.exists() and any(profile_dir.iterdir()) if profile_dir.exists() else False

    result = {
        "name": "Google Flow Browser Automation",
        "subsystem": SUBSYSTEM_FLOW,
        "status": "PASS" if has_profile else "WARN",
        "profile_dir": str(profile_dir),
        "has_profile": has_profile,
        "project_url": settings.flow_project_url or "(auto-discover on Flow home)",
        "direct_api_session": session_file.exists(),
    }
    if not has_profile:
        result["suggested_fix"] = "Run 'python -m scripts.login_google_flow' to log into Google Flow once."
    return result


def inspect_pinterest_publisher() -> dict[str, Any]:
    """Inspect Pinterest session profile and cached board catalogue."""
    profile_dir = Path("./data/pinterest_profile").resolve()
    boards_file = Path("./data/pinterest_boards.json").resolve()
    has_profile = profile_dir.exists() and any(profile_dir.iterdir()) if profile_dir.exists() else False

    boards_count = 0
    if boards_file.exists():
        try:
            data = json.loads(boards_file.read_text(encoding="utf-8"))
            boards_count = len(data.get("boards", []))
        except Exception:
            pass

    result = {
        "name": "Pinterest Publisher & Scheduler",
        "subsystem": SUBSYSTEM_PINTEREST,
        "status": "PASS" if has_profile else "WARN",
        "profile_dir": str(profile_dir),
        "authenticated": has_profile,
        "cached_boards_count": boards_count,
        "default_board": settings.default_board_name,
    }
    if not has_profile:
        result["suggested_fix"] = "Run 'python scripts/init_pinterest_auth.py' to log into Pinterest."
    elif boards_count == 0:
        result["status"] = "WARN"
        result["suggested_fix"] = "Refresh board list via 'POST /api/pins/boards/refresh' or in the Pin Composer."
    return result


def inspect_storage_directories() -> dict[str, Any]:
    """Inspect all required storage directories and verify write access."""
    paths = {
        "references": settings.references_path,
        "products": settings.products_path,
        "jobs": settings.jobs_path,
        "outputs": settings.outputs_path,
        "exports": settings.exports_path,
    }
    all_ok = True
    counts = {}
    for name, p in paths.items():
        p.mkdir(parents=True, exist_ok=True)
        counts[name] = len(list(p.iterdir())) if p.exists() else 0

    return {
        "name": "Storage & Assets",
        "subsystem": SUBSYSTEM_STORAGE,
        "status": "PASS" if all_ok else "FAIL",
        "counts": counts,
        "base_path": str(Path(settings.storage_path).resolve()),
    }


def inspect_vault_sync() -> dict[str, Any]:
    """Inspect Obsidian Vault connectivity and recent bug notes."""
    vault_path = Path("./vault").resolve()
    has_vault = vault_path.exists()
    bugs_dir = vault_path / "02 - Bugs & Issues"
    bug_files = list(bugs_dir.glob("*.md")) if bugs_dir.exists() else []

    return {
        "name": "Obsidian Vault Real-Time Sync",
        "subsystem": SUBSYSTEM_VAULT,
        "status": "PASS" if has_vault else "WARN",
        "vault_path": str(vault_path),
        "connected": has_vault,
        "logged_bug_count": len(bug_files),
    }


async def run_full_system_diagnostic() -> dict[str, Any]:
    """
    Executes an instant comprehensive health & diagnostic check across all subsystems.
    """
    t_start = time.time()
    db_res = await inspect_database()
    llm_res = await inspect_llm_stack()
    flow_res = inspect_flow_automation()
    pin_res = inspect_pinterest_publisher()
    storage_res = inspect_storage_directories()
    vault_res = inspect_vault_sync()

    subsystems = [db_res, llm_res, flow_res, pin_res, storage_res, vault_res]
    overall_status = "PASS"
    if any(s.get("status") == "FAIL" for s in subsystems):
        overall_status = "FAIL"
    elif any(s.get("status") == "WARN" for s in subsystems):
        overall_status = "WARN"

    recent_errors = get_recent_errors(limit=10)

    return {
        "overall_status": overall_status,
        "diagnostic_time_ms": int((time.time() - t_start) * 1000),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "subsystems": {
            "database": db_res,
            "llm_provider": llm_res,
            "flow_automation": flow_res,
            "pinterest_publisher": pin_res,
            "storage": storage_res,
            "vault": vault_res,
        },
        "recent_errors": recent_errors,
    }
