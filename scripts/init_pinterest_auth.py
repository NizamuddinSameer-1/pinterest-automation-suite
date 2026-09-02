"""
Pinterest Realism Engine — One-Time Pinterest Login & Session Saver.

Launches a visible Chromium window using a dedicated persistent profile folder.
Log into your Pinterest account once; cookies and authentication state will
remain saved permanently for automated publishing.

Supports multi-profile:
    python scripts/init_pinterest_auth.py [--profile <profile_id>] [--name <profile_name>]
"""

import argparse
import asyncio
import sys
from pathlib import Path
from playwright.async_api import async_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.pinterest_profiles import (
    DEFAULT_PROFILE_ID,
    create_profile,
    get_profile,
    get_profile_dir,
    list_profiles,
)


def clean_stale_locks(profile_dir: Path) -> None:
    """Remove Chrome lock files to avoid 'Opening in existing browser session'."""
    for lock in ["SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"]:
        lock_file = profile_dir / lock
        if lock_file.exists():
            try:
                lock_file.unlink()
                print(f"🧹 Cleaned stale lock: {lock}")
            except Exception:
                pass


async def init_auth(profile_id: str = DEFAULT_PROFILE_ID, name: str | None = None):
    # Ensure profile is registered
    prof = get_profile(profile_id)
    if not prof and name:
        prof = create_profile(name=name, profile_id=profile_id)
    elif not prof and profile_id != DEFAULT_PROFILE_ID:
        prof = create_profile(name=profile_id.replace("_", " ").title(), profile_id=profile_id)

    profile_name = prof["name"] if prof else (name or "Default Account")
    profile_dir = get_profile_dir(profile_id)

    print("=" * 60)
    print("🚀 PINTEREST AUTHENTICATION LAUNCHER")
    print("=" * 60)
    print(f"👤 Profile: {profile_name} (ID: {profile_id})")
    print(f"📁 Session Directory: {profile_dir}\n")

    profile_dir.mkdir(parents=True, exist_ok=True)
    clean_stale_locks(profile_dir)

    async with async_playwright() as p:
        print("🌐 Launching Chrome for Pinterest login...")
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            viewport={"width": 1280, "height": 850},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )

        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://www.pinterest.com/login/")

        print("\n" + "─" * 60)
        print(f"👉 STEP: Log into your Pinterest account ({profile_name}) in the Chrome window.")
        print("👉 STEP: Once you are logged in and see your Pinterest home feed,")
        print("👉 STEP: Come back to this terminal and press [ENTER]...")
        print("─" * 60 + "\n")

        # Wait for user input in terminal
        try:
            input("Press ENTER after you have logged in...")
        except EOFError:
            # Running non-interactively, wait 45 seconds
            await asyncio.sleep(45)

        print("💾 Saving session cookies & credentials...")
        try:
            await context.close()
        except Exception:
            pass  # User may have closed the browser window manually — that's fine

        print(f"\n🎉 SUCCESS! Pinterest session for '{profile_name}' saved permanently to {profile_dir}!")
        print("You can now publish pins to this account with 0 API keys.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pinterest Login Session Saver")
    parser.add_argument("--profile", default=DEFAULT_PROFILE_ID, help="Profile ID (default or slug)")
    parser.add_argument("--name", default=None, help="Profile display name")
    args = parser.parse_args()

    asyncio.run(init_auth(profile_id=args.profile, name=args.name))
