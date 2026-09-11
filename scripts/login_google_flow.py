"""
Pinterest Realism Engine — 1-Time Google Flow Browser Launcher (Windows Visible Window).

Opens a dedicated, completely visible browser window directly on your screen
so you can sign in to Google Flow once and save your session.
"""

import os
import subprocess
import sys
from pathlib import Path

PROFILE_DIR = Path("./data/flow_profile").resolve()
PROFILE_DIR.mkdir(parents=True, exist_ok=True)

FLOW_URL = "https://labs.google/fx/tools/image-fx"

# Candidates in order
BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


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


def launch_visible_browser():
    clean_stale_locks(PROFILE_DIR)
    browser_exe = None
    for path in BROWSERS:
        if Path(path).exists():
            browser_exe = path
            break

    if not browser_exe:
        print("[ERROR] No supported browser found.")
        return False

    print(f"Launching visible browser: {browser_exe}")
    
    # Use PowerShell Start-Process with --new-window to guarantee a brand new visible window opens on the desktop
    args = [
        "powershell",
        "-NoProfile",
        "-Command",
        f'Start-Process "{browser_exe}" -ArgumentList "--user-data-dir=`"{PROFILE_DIR}`"", "--new-window", "--no-first-run", "--no-default-browser-check", "`"{FLOW_URL}`""'
    ]
    subprocess.run(args, check=True)
    print("[SUCCESS] Browser window launched on your desktop screen!")
    return True


if __name__ == "__main__":
    launch_visible_browser()
