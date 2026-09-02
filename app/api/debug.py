"""
Debug & Diagnostics API routes — Instant system-wide health and error intelligence.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from app.services.error_diagnostics import (
    get_recent_errors,
    inspect_flow_automation,
    inspect_llm_stack,
    inspect_pinterest_publisher,
    record_diagnostic_error,
    run_full_system_diagnostic,
)

router = APIRouter(prefix="/api/debug", tags=["diagnostics"])
logger = logging.getLogger("pre.api.debug")


@router.get("/system-status")
async def get_system_status():
    """
    Execute full automated inspection of all 7 subsystems:
    Database, LLM Providers, Flow Automation, Pinterest Publisher, Storage, and Obsidian Vault.
    """
    try:
        return await run_full_system_diagnostic()
    except Exception as e:
        logger.exception("Failed to run system diagnostics: %s", e)
        diag = record_diagnostic_error(e, subsystem="API", context={"endpoint": "/api/debug/system-status"})
        return {
            "overall_status": "FAIL",
            "error": str(e),
            "diagnostic": diag.to_dict(),
        }


@router.get("/recent-errors")
async def list_recent_errors(limit: int = 20):
    """
    Return recent runtime diagnostic errors with subsystem tags, locations, and suggested fixes.
    """
    return {
        "count": len(get_recent_errors(limit=limit)),
        "errors": get_recent_errors(limit=limit),
    }


@router.post("/test-llm")
async def test_llm_endpoint():
    """Probe configured LLM provider and measure latency/quota availability."""
    return await inspect_llm_stack()


@router.post("/test-flow-session")
async def test_flow_session_endpoint():
    """Probe Google Flow browser profile state."""
    return inspect_flow_automation()


@router.post("/test-pinterest-session")
async def test_pinterest_session_endpoint():
    """Probe Pinterest session profile state."""
    return inspect_pinterest_publisher()
