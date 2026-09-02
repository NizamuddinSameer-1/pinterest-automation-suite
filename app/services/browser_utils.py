"""
Shared browser-automation helpers.

Both Playwright services (Google Flow generation and Pinterest publishing) run a
persistent Chromium profile and occasionally need to clear a stale profile lock,
and both have to put long text into a field where Enter means "submit".
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("pre.browser_utils")

LOCK_FILES = ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile")


class TextEntryError(RuntimeError):
    """Text could not be delivered without risking a stray form submission."""


async def insert_text(page, text: str) -> str:
    """
    Put `text` into the focused field without generating a single key event.

    Returns a short label naming the mechanism used, for the caller's log.

    Why this exists: `keyboard.type()` replays every character as a real key
    press, so each newline is delivered as Enter — and Enter submits in both
    Google Flow's prompt bar and Pinterest's description editor. The safe
    primitive is one text insertion with no key events.

    The method is `keyboard.insert_text`, **snake_case**: Playwright's Python
    bindings rename every JavaScript method. `keyboard.insertText` raises
    `'Keyboard' object has no attribute 'insertText'` at run time — which is how
    this failed in production once — and `AttributeError` is not a
    `PlaywrightError`, so it slips straight past an `except PlaywrightError`
    fallback. Hence `getattr`, which cannot be wrong about the name that exists.
    """
    insert = getattr(page.keyboard, "insert_text", None)
    if callable(insert):
        await insert(text)
        return "keyboard.insert_text"

    # No binding for it: talk to the DevTools protocol directly (Chromium only,
    # which is what both services launch).
    try:
        session = await page.context.new_cdp_session(page)
        await session.send("Input.insertText", {"text": text})
        return "CDP Input.insertText"
    except Exception as e:
        logger.warning("Text insertion unavailable (%s); falling back to typing.", e)

    if "\n" in text or "\r" in text:
        # Refuse rather than submit something half-finished.
        raise TextEntryError(
            "Cannot type this text safely: it contains a newline, and typing "
            "delivers a newline as an Enter key press, which submits the form. "
            "Flatten the text first."
        )
    await page.keyboard.type(text, delay=1)
    return "keyboard.type"


def clean_stale_locks(profile_dir: Path) -> None:
    """Remove Chromium profile lock files left behind by a crashed run."""
    for lock in LOCK_FILES:
        lock_file = profile_dir / lock
        if lock_file.exists():
            try:
                lock_file.unlink()
                logger.info("Cleaned stale profile lock: %s", lock_file)
            except Exception:
                pass


def kill_chrome_for_profile(profile_dir: Path) -> None:
    """
    Kill only the Chromium processes launched against `profile_dir`.

    Deliberately narrow: `taskkill /F /IM chrome.exe` would also close every
    personal Chrome window the operator has open, mid-session.
    """
    if sys.platform != "win32":
        return

    marker = profile_dir.name  # e.g. "flow_profile" / "pinterest_profile"
    if not marker:
        return

    ps_command = (
        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{marker}*' }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_command],
            capture_output=True,
            timeout=20,
            check=False,
        )
        logger.info("Killed stale Chromium processes for profile %s", marker)
    except Exception as e:  # pragma: no cover — best-effort cleanup
        logger.warning("Scoped Chrome cleanup failed for %s: %s", marker, e)
