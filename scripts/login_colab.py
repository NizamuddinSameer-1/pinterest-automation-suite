"""
Pinterest Realism Engine — 1-Time Google Colab Browser Launcher (Windows Visible Window).

Opens a dedicated, completely visible browser window directly on your screen
so you can view your Colab notebook, sign in, or verify your T4 GPU runtime.
"""

import os
import subprocess
import sys
from pathlib import Path

PROFILE_DIR = Path("./data/colab_profile").resolve()
PROFILE_DIR.mkdir(parents=True, exist_ok=True)

COLAB_URL = "https://colab.research.google.com/drive/1TgdpXgPBQ7pKlYO50PsuSX8RcRyu7y9U#scrollTo=HLsprCUNt-MT"

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def launch_colab_browser():
    browser_exe = None
    for path in BROWSERS:
        if Path(path).exists():
            browser_exe = path
            break

    if not browser_exe:
        print("[ERROR] No supported browser found.")
        return False

    print(f"Launching visible Colab browser with profile: {PROFILE_DIR}")
    
    args = [
        "powershell",
        "-NoProfile",
        "-Command",
        f'Start-Process "{browser_exe}" -ArgumentList "--user-data-dir=`"{PROFILE_DIR}`"", "--new-window", "--no-first-run", "--no-default-browser-check", "`"{COLAB_URL}`""'
    ]
    subprocess.run(args, check=True)
    print("[SUCCESS] Google Colab window opened on your desktop!")
    return True


if __name__ == "__main__":
    launch_colab_browser()
