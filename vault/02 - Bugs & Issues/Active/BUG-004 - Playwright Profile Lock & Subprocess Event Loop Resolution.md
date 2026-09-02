---
aliases:
  - BUG-004
  - Profile Lock & Subprocess Bug Resolution
tags:
  - bug
  - resolved
  - playwright
  - flow
created: 2026-08-21
updated: 2026-08-21
status: CLOSED
severity: HIGH
---

# 🐛 BUG-004: Playwright Profile Lock & Subprocess Event Loop Resolution

## 📋 Problem Description
When executing Google Flow 4-variation automated generation from the web interface, the generation call hung or failed due to three concurrent runtime issues:
1. Playwright failing under Uvicorn with `NotImplementedError` on Windows.
2. Chromium profile locking (`data/flow_profile/SingletonLock`) causing `"Opening in existing browser session"`.
3. Selector slice capturing older canvas images instead of newly rendered ones.

---

## 🔍 Root Cause Analysis

| Component | Error | Root Cause |
|---|---|---|
| **Asyncio Loop** | `NotImplementedError` | Uvicorn's default `SelectorEventLoop` on Windows doesn't support subprocess transport required by Playwright. |
| **Chromium Profile** | `Opening in existing browser session` | Orphaned background `chrome.exe` processes or uncleaned `SingletonLock` files left `data/flow_profile` locked. |
| **DOM Selector** | Capturing old cards | Google Flow canvas stores all historical cards. `img[:4]` grabbed the top-left oldest images instead of newly created ones. |
| **FastAPI Route** | 404 Not Found on Polling | `/{job_id}/generate-flow/status` was shadowed by catch-all route ordering. |

---

## 🛠️ Resolution & Code Changes

### 1. `app/services/flow_automator.py`
- Added lock cleanup before launch:
  ```python
  for lock in ["SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"]:
      lock_file = PROFILE_DIR / lock
      if lock_file.exists():
          lock_file.unlink()
  ```
- Implemented a 3-attempt self-healing retry loop with `taskkill /F /IM chrome.exe` for orphaned processes.
- Switched to DOM image diffing (`src not in initial_srcs`) to guarantee capturing only new images.

### 2. `scripts/run_flow_bg.py`
- Set `asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())`.
- Detached execution into a background worker script.

### 3. `app/api/jobs.py`
- Reordered status endpoint and updated `generate_flow_batch_endpoint` to launch `run_flow_bg.py` with output redirection to `bg_log.txt`.

---

## ✅ Verification
Tested with job `e92ca1d0...` — generated and saved 4 high-res Pinterest vertical photos in `data/outputs/` and populated database records cleanly.

**Status:** CLOSED
