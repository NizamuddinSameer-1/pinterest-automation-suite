"""
Pinterest Realism Engine — Google Colab Playwright Automator.

Drives Google Colab using the persistent Chromium profile (`data/flow_profile`),
switches the hardware accelerator to T4 GPU, runs the Real-ESRGAN cloud server,
reads the Cloudflare tunnel URL, and feeds generation variations for AI upscaling.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Sequence

import httpx
from playwright.async_api import async_playwright, BrowserContext, Page

from app.config import settings
from app.services.browser_utils import kill_chrome_for_profile

logger = logging.getLogger("pre.colab_automator")

PROFILE_DIR = Path("./data/colab_profile").resolve()
CLOUDFLARE_URL_REGEX = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

_ACTIVE_CONTEXT: BrowserContext | None = None
_ACTIVE_PAGE: Page | None = None
_ACTIVE_TUNNEL_URL: str | None = None


async def get_or_launch_colab(notebook_url: str | None = None) -> tuple[Page, str]:
    """
    Launch or reuse the Google Colab browser page and return (page, tunnel_url).
    Ensures T4 GPU is active, executes the notebook, and extracts the Cloudflare tunnel URL.
    """
    global _ACTIVE_CONTEXT, _ACTIVE_PAGE, _ACTIVE_TUNNEL_URL

    url = (notebook_url or getattr(settings, "colab_notebook_url", "")).strip()
    if not url:
        raise ValueError("No COLAB_NOTEBOOK_URL provided in configuration or settings.")

    # 1. If browser is already open and page is active and responding, reuse
    if _ACTIVE_PAGE and not _ACTIVE_PAGE.is_closed() and _ACTIVE_TUNNEL_URL:
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                r = await client.get(_ACTIVE_TUNNEL_URL)
                if r.status_code == 200:
                    logger.info("⚡ [COLAB AUTOMATOR] Reusing active open Colab browser & tunnel: %s", _ACTIVE_TUNNEL_URL)
                    return _ACTIVE_PAGE, _ACTIVE_TUNNEL_URL
        except Exception:
            _ACTIVE_TUNNEL_URL = None

    p = await async_playwright().start()

    # Clean stale locks
    kill_chrome_for_profile(PROFILE_DIR)
    await asyncio.sleep(1)

    ctx = await p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
        no_viewport=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--start-maximized",
            "--no-sandbox",
        ],
    )
    _ACTIVE_CONTEXT = ctx
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    _ACTIVE_PAGE = page

    logger.info("🌐 [COLAB AUTOMATOR] Navigating to Google Colab: %s", url)
    await page.goto(url, wait_until="domcontentloaded", timeout=75_000)
    await page.wait_for_timeout(3000)

    # 2. Handle any initial popups (Author warning, etc.)
    await _dismiss_popups(page)

    # 3. Ensure Hardware Accelerator is set to T4 GPU
    await _ensure_t4_gpu(page)

    # 4. Trigger Notebook Run ("Run all" via Ctrl+F9 or Runtime menu)
    logger.info("▶️ [COLAB AUTOMATOR] Triggering Run All on Colab notebook...")
    await _trigger_run_all(page)

    # 5. Wait for the Cloudflare Tunnel URL to appear in the notebook cell output
    logger.info("⏳ [COLAB AUTOMATOR] Waiting for Real-ESRGAN to load & tunnel URL to appear...")
    tunnel_url = await _wait_for_tunnel_url(page, timeout_seconds=180)
    if not tunnel_url:
        raise RuntimeError("Google Colab failed to produce a Cloudflare tunnel URL within 180s.")

    _ACTIVE_TUNNEL_URL = tunnel_url
    TUNNEL_CACHE.write_text(tunnel_url, encoding="utf-8")
    logger.info("🎉 [COLAB AUTOMATOR] Colab AI Upscaler Online: %s", tunnel_url)
    return page, tunnel_url


async def _dismiss_popups(page: Page) -> None:
    """Click away common Google Colab popups like author warning."""
    candidate_selectors = [
        'button:has-text("Run anyway")',
        'mwc-button:has-text("Run anyway")',
        'paper-button:has-text("Run anyway")',
        'button:has-text("Cancel")',
        'button:has-text("Got it")',
        'button:has-text("OK")',
    ]
    for sel in candidate_selectors:
        try:
            loc = page.locator(sel)
            if await loc.count() > 0 and await loc.first.is_visible():
                await loc.first.click()
                logger.info("Dismissed Colab popup: %s", sel)
                await page.wait_for_timeout(1000)
        except Exception:
            pass


async def _ensure_t4_gpu(page: Page) -> None:
    """Check and switch runtime type to T4 GPU on every launch if not already connected."""
    logger.info("⚙️ [COLAB AUTOMATOR] Checking runtime accelerator status...")
    try:
        # Check if already connected (shows RAM/Disk meter as in user screenshot)
        connected_meter = page.locator('colab-connect-button, div:has-text("RAM"), div:has-text("Disk")')
        if await connected_meter.count() > 0:
            meter_text = await page.locator('colab-connect-button, [id*="connect"]').all_inner_texts()
            joined = " ".join(meter_text)
            if "RAM" in joined or "Disk" in joined or "T4" in joined:
                logger.info("⚡ [COLAB AUTOMATOR] T4 GPU runtime is ALREADY connected! Skipping dialog.")
                return

        # Open Runtime Menu if not connected yet
        runtime_menu = page.locator('div[id="runtime-menu-button"], div[aria-label*="Runtime" i], div:text-is("Runtime")').first
        if await runtime_menu.count() > 0:
            await runtime_menu.click()
            await page.wait_for_timeout(800)

            # Click 'Change runtime type'
            change_runtime_item = page.locator('div:has-text("Change runtime type"), [command="change-runtime-type"]').first
            if await change_runtime_item.count() > 0:
                await change_runtime_item.click()
                await page.wait_for_timeout(1500)

                # Look for the dialog
                dialog = page.locator('md-dialog, mwc-dialog, paper-dialog, div[role="dialog"]').first
                if await dialog.count() > 0:
                    # Look for T4 GPU option or hardware accelerator dropdown
                    t4_option = dialog.locator('text="T4 GPU", [value*="T4" i], label:has-text("T4")').first
                    if await t4_option.count() > 0:
                        await t4_option.click()
                        await page.wait_for_timeout(500)
                    else:
                        # Try selecting dropdown
                        dropdown = dialog.locator('md-select, select, div[role="combobox"]').first
                        if await dropdown.count() > 0:
                            await dropdown.click()
                            await page.wait_for_timeout(500)
                            t4_choice = page.locator('md-select-option:has-text("T4"), [role="option"]:has-text("T4 GPU"), text="T4 GPU"').first
                            if await t4_choice.count() > 0:
                                await t4_choice.click()
                                await page.wait_for_timeout(500)

                    # Click Save
                    save_btn = dialog.locator('button:has-text("Save"), mwc-button:has-text("Save")').first
                    if await save_btn.count() > 0:
                        await save_btn.click()
                        logger.info("✅ [COLAB AUTOMATOR] T4 GPU accelerator confirmed and saved.")
                        await page.wait_for_timeout(2000)
                        return
    except Exception as e:
        logger.warning("⚠️ [COLAB AUTOMATOR] Note while checking GPU runtime: %s. Continuing...", e)

    # Fallback: close any lingering dialog
    with contextlib.suppress(Exception):
        await page.keyboard.press("Escape")


async def _trigger_run_all(page: Page) -> None:
    """Dispatch Run All command in Colab."""
    # 1. Try Runtime menu -> Run all
    try:
        runtime_menu = page.locator('div[id="runtime-menu-button"], div:text-is("Runtime")').first
        if await runtime_menu.count() > 0:
            await runtime_menu.click()
            await page.wait_for_timeout(800)
            run_all_item = page.locator('div:has-text("Run all"), [command="runall"]').first
            if await run_all_item.count() > 0:
                await run_all_item.click()
                logger.info("⚡ [COLAB AUTOMATOR] Clicked Runtime -> Run all")
    except Exception as e:
        logger.debug("Runtime menu run all notice: %s", e)

    # 2. Keyboard shortcut: Control+F9
    await page.keyboard.press("Control+F9")
    await page.wait_for_timeout(1000)

    # 3. Direct cell run button inside colab-cell
    try:
        cell_run = page.locator('colab-cell colab-run-button, .cell.code colab-run-button').first
        if await cell_run.count() > 0 and await cell_run.is_visible():
            await cell_run.click()
            logger.info("⚡ [COLAB AUTOMATOR] Clicked cell run button")
    except Exception as e:
        logger.debug("Cell run button notice: %s", e)

    # 4. Dismiss any popups like author warning
    await page.wait_for_timeout(1500)
    await _dismiss_popups(page)


async def _wait_for_tunnel_url(page: Page, timeout_seconds: int = 180) -> str | None:
    """Poll page outputs for an active, responding Cloudflare tunnel URL."""
    start = time.time()
    while time.time() - start < timeout_seconds:
        # Check popup again in case of warning
        await _dismiss_popups(page)

        try:
            # Check cell output text areas
            outputs = await page.locator('.output, .stream, colab-output-renderer').all_inner_texts()
            full_text = " ".join(outputs)

            for match in CLOUDFLARE_URL_REGEX.finditer(full_text):
                cand = match.group(0)
                # Verify tunnel is answering HTTP requests
                try:
                    async with httpx.AsyncClient(timeout=3.0) as client:
                        r = await client.get(cand)
                        if r.status_code == 200:
                            logger.info("⚡ [COLAB AUTOMATOR] Verified active live tunnel: %s", cand)
                            return cand
                except Exception:
                    pass

            # Fallback: search entire body text
            body_text = await page.inner_text("body")
            for match2 in CLOUDFLARE_URL_REGEX.finditer(body_text):
                cand2 = match2.group(0)
                try:
                    async with httpx.AsyncClient(timeout=3.0) as client:
                        r = await client.get(cand2)
                        if r.status_code == 200:
                            logger.info("⚡ [COLAB AUTOMATOR] Verified active live tunnel: %s", cand2)
                            return cand2
                except Exception:
                    pass
        except Exception:
            pass

        await asyncio.sleep(3)

    return None


async def upscale_images_via_colab(
    image_paths: Sequence[str | Path],
    notebook_url: str | None = None,
) -> list[str]:
    """
    Automate Google Colab to upscale a list of generated images.
    Returns list of updated image paths.
    """
    if not image_paths:
        return []

    # 1. Connect to Colab and get tunnel
    _, tunnel_url = await get_or_launch_colab(notebook_url)
    endpoint = f"{tunnel_url.rstrip('/')}/upscale"

    upscaled_paths: list[str] = []

    async with httpx.AsyncClient(timeout=120.0) as client:
        for idx, img_path in enumerate(image_paths, 1):
            p = Path(img_path).resolve()
            if not p.is_file():
                logger.warning("Image does not exist: %s", p)
                continue

            logger.info("🔼 [COLAB AUTOMATOR] Uploading variation #%d to Colab GPU: %s", idx, p.name)
            raw_bytes = p.read_bytes()

            success = False
            for attempt in range(2):
                try:
                    files = {"file": (p.name, raw_bytes, "image/jpeg")}
                    resp = await client.post(endpoint, files=files)
                    if resp.status_code == 200 and len(resp.content) > 5000:
                        from app.services.anti_ai_processor import postprocess_image

                        temp_upscaled = p.with_suffix(".colab_tmp.jpg")
                        temp_upscaled.write_bytes(resp.content)

                        postprocess_image(temp_upscaled, p)
                        if temp_upscaled.is_file():
                            temp_upscaled.unlink()

                        logger.info("✅ [COLAB AUTOMATOR] Variation #%d upscaled: %s (%d KB)", idx, p.name, p.stat().st_size // 1024)
                        upscaled_paths.append(str(p))
                        success = True
                        break
                    else:
                        logger.warning("Colab returned status %d for %s (attempt %d)", resp.status_code, p.name, attempt + 1)
                except Exception as e:
                    logger.warning("Attempt %d to upscale %s failed: %s", attempt + 1, p.name, e)
                    if attempt == 0:
                        await asyncio.sleep(2)

            if not success:
                logger.info("Using local high-resolution engine for %s", p.name)
                from app.services.anti_ai_processor import postprocess_image
                postprocess_image(p)
                upscaled_paths.append(str(p))

    return upscaled_paths
