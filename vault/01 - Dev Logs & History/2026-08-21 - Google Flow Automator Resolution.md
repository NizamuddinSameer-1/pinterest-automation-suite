---
aliases:
  - 2026-08-21 Dev Log
  - Google Flow Automator Fix
tags:
  - devlog
  - flow
  - fixes
  - playwright
created: 2026-08-21
updated: 2026-08-21
---

# 📅 Dev Log: 2026-08-21 — Google Flow Automator Resolution & Polling Integration

## 📌 Summary
Resolved all major issues preventing automated Google Flow 4-variation batch image generation, image extraction, and real-time gallery rendering in the Pinterest Realism Engine.

---

## 🛠️ Issues Addressed & Solutions Applied

### 1. HTTP Request Timeout on Generation
- **Symptom:** Clicking "Generate 4 Variations Now" timed out after 30–60 seconds, leaving jobs stuck in `DRAFT` or `GENERATING`.
- **Root Cause:** Playwright browser automation was being `await`-ed directly inside the FastAPI request handler, blocking the HTTP thread.
- **Fix:** Converted `generate_flow_batch_endpoint` into an instant background process trigger. It writes `prompt.txt` and `status.json`, launches `scripts.run_flow_bg` in a detached process, and returns HTTP 200 immediately (`<0.1s`). The frontend polls `/api/jobs/{job_id}/generate-flow/status` every 5 seconds.

### 2. Windows Asyncio Subprocess `NotImplementedError`
- **Symptom:** Backend threw `NotImplementedError` when attempting to spawn Playwright Chromium on Windows.
- **Root Cause:** Uvicorn on Windows uses SelectorEventLoop by default, which does not support Playwright subprocesses.
- **Fix:** Added `asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())` to `scripts/run_flow_bg.py` and decoupled execution into a standalone process.

### 3. Chromium Profile Lock Contention (`Opening in existing browser session`)
- **Symptom:** Background Playwright tasks failed with *"Opening in existing browser session"*.
- **Root Cause:** Lingering background `chrome.exe` processes or stale `SingletonLock` files locked `data/flow_profile`.
- **Fix:** Added automatic stale lock cleanup (`SingletonLock`, `lockfile`) and a 3-attempt self-healing launch loop in `app/services/flow_automator.py` that kills lingering orphaned Chrome processes on Windows before retrying.

### 4. Wrong Images Captured (Template / Old Cards Captured Instead of New Batch)
- **Symptom:** Gallery rendered hiking signs or old test images instead of the newly requested product images.
- **Root Cause:** Google Flow projects preserve all previous generations on an infinite canvas. Selector `img[:count]` grabbed the oldest 4 images on the page.
- **Fix:** Implemented DOM image diffing: recorded `initial_srcs` set before submitting the prompt, and filtered for `src not in initial_srcs` after generation completed.

### 5. Instant Prompt Construction
- **Symptom:** Generation call hung retrying external LLM providers when API keys were missing/unauthorized.
- **Fix:** Added deterministic instant prompt construction for Google Flow, removing external LLM blocking delays from the critical path.

---

## ✅ Results & Verification
- Tested with **French Maid Halloween Costume Set** (`prod_maid_costume_001`).
- Successfully generated and captured **4 photorealistic 9:16 Pinterest vertical mirror selfies** (`flow_var_1.jpg` – `flow_var_4.jpg`).
- All 4 variations are saved, indexed in SQLite, rendered in the Creative Lab gallery, and synced with the Obsidian Vault graph.
