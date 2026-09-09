"""
Trend Radar background scanner — daily fan-out over free sources.

Mirrors the pin scheduler's asyncio-loop pattern (app/services/scheduler.py):
one task, interval sleep, overlapping runs skipped via a module lock.
Disabled with TREND_SCAN_ENABLED=false (tests set this).
"""
from __future__ import annotations

import asyncio
import logging

from app.config import settings

logger = logging.getLogger("pre.trend_scheduler")

_task: asyncio.Task | None = None
_running = False


async def run_scan_once() -> int:
    """Run one full scan; returns dossier count. Never raises."""
    from app.services.trend_research import discover_trends_radar
    from app.services.pinterest_trends_scraper import get_official_pinterest_trends

    total = 0
    try:
        dossiers = await discover_trends_radar()
        logger.info("Commercial trend scan complete: %d dossiers", len(dossiers))
        total += len(dossiers)
    except Exception as e:
        logger.warning("Commercial trend scan failed: %s", e)

    # Automatically refresh official Pinterest Trends in the background
    for preset in ["breakout", "growing", "top"]:
        try:
            trends = await get_official_pinterest_trends(preset=preset, force_refresh=True)
            logger.info("Official Pinterest Trends background refresh [%s]: %d items", preset, len(trends))
            total += len(trends)
        except Exception as e:
            logger.warning("Official Pinterest Trends background refresh failed for %s: %s", preset, e)

    return total


async def _loop() -> None:
    global _running
    interval = max(1, settings.trend_scan_interval_hours) * 3600
    while True:
        if not _running:
            _running = True
            try:
                await run_scan_once()
            finally:
                _running = False
        await asyncio.sleep(interval)


def start_trend_scan() -> None:
    """Start the daily scan loop (idempotent)."""
    global _task
    if not settings.trend_scan_enabled:
        logger.info("Trend scan disabled (TREND_SCAN_ENABLED=false)")
        return
    if _task is None or _task.done():
        _task = asyncio.ensure_future(_loop())
        logger.info("Trend scan loop started")


async def stop_trend_scan() -> None:
    """Cancel the scan loop (awaited in lifespan shutdown)."""
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
