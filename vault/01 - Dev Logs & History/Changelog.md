---
aliases:
  - Changelog
  - Version History
tags:
  - changelog
  - history
  - release
created: 2026-08-20
updated: 2026-08-22
---

# 📜 System Changelog

All notable changes, architectural updates, refactorings, and milestone deliveries will be documented in this file.

## [v2.1.1] — 2026-08-22 — SQLite WAL & Vault Sync Repair

### 🩹 Fixed
- **SQLite `database is locked` (BUG-003 / AUTO-BUG-20260822_130901):**
  - Added `PRAGMA journal_mode=WAL` + `busy_timeout=5000` + `synchronous=NORMAL` via SQLAlchemy `connect` event in `app/database.py:12` — every new `aiosqlite` connection now gets WAL, not just the first.
  - Raised `connect_args.timeout` `5s` → `30s`.
  - Verified with concurrent `POST /api/jobs/preview-prompt` + polling — no lock.
- **Obsidian Vault Sync Drift:**
  - Archived 6 duplicate retry AUTO-BUGs to `02 - Bugs & Issues/_Archive - Retry Duplicates/` (25 active + 6 archived = 31 total preserved).
  - Removed stray `vault/Job - f671ff...md` duplicate at vault root.
  - Archived legacy `🎃 Campaign - Fall Halloween 2026.md` duplicate, repaired `[[🎃 Campaign` → `[[Campaign` in 104 nodes (Jobs, Refs, Pins, Products).
  - Closed `BUG-003` and `AUTO-BUG-20260822_130901`, opened detailed dev log `2026-08-22 - SQLite WAL & Vault Repair`.

### 📝 Docs
- New: `01 - Dev Logs & History/2026-08-22 - SQLite WAL & Vault Repair.md` — real-time error → fix trace.
- Updated: `BUG-003`, `AUTO-BUG-20260822_130901`, `🐛 Bug Tracker MOC`, `Issues Tracker Index`, `🏠 Main Dashboard`.

---

## [v2.1.0] — 2026-08-21

### ⚡ Added & Improved (Google Flow Direct API Engine)
- **100% Free Automated 4-Variation Generator:**
  - Integrated Playwright automation (`flow_automator.py`) supporting Google Flow (**Nano Banana 2 × x4**).
  - Built background worker (`scripts/run_flow_bg.py`) with `WindowsProactorEventLoopPolicy` to prevent event loop blocking.
  - Implemented 5-second polling status endpoint (`/api/jobs/{job_id}/generate-flow/status`).
  - Added self-healing Chromium profile lock recovery (`SingletonLock` removal + process cleanup).
  - Implemented DOM image diffing (`initial_srcs` set filtering) to isolate newly generated variations from canvas history.
- **Frontend Gallery Improvements:**
  - Auto-load latest completed `PASS` job on page load.
  - Live progress timer and status message feedback during background generation.
  - Dynamic cache-busting URL formatting for static `/data/outputs/` assets.

---

## [v2.0.0] — 2026-08-20

### 🚀 Added
- **Obsidian Vault Architecture:** Integrated `/vault` directory complete with MOCs, Bug Trackers, Visual DNA repositories, dev logs, and pre-built templates.
- **Dual LLM Provider Layer:** Built `app/providers/llm.py` providing seamless routing between OpenRouter (OpenAI-compatible text) and Google Gemini (Vision).
- **Core 6-Stage Pipeline:**
  - `reference_analyst.py`: 9-dimension multimodal photographic analyzer.
  - `visual_dna.py`: Stable vs Variable DNA extraction and versioning.
  - `scene_director.py`: Contextual scene generator with mandatory `capture_motivation`.
  - `prompt_compiler.py`: 13-section prompt compiler with compile-time sanitizer and job packager.
  - `realism_critic.py`: 3-question categorical evaluation with blocker defect detection.
  - `pinterest_seo.py`: Natural language Pin title, description, and keyword creator.
  - `rework_engine.py`: Targeted `PRESERVE` / `FIX` / `AVOID` revision generator.
- **Data & Storage Layer:**
  - 9-table async SQLite schema using SQLAlchemy (`Campaign`, `Reference`, `ReferenceAnalysis`, `VisualDNA`, `Product`, `Job`, `PromptVersion`, `JobOutput`, `Critique`, `PinDraft`).
  - Robust state machine transition service (`app/services/job_service.py`).
  - Automated ZIP export packaging for Google Flow and completed Pin bundles (`app/services/export_service.py`).
- **REST API Endpoints:**
  - `/api/campaigns`: Campaign creation, listing, and statistical aggregation.
  - `/api/references`: Image upload, vision analysis trigger, and Visual DNA version editing.
  - `/api/products`: Product CRUD, Product Truth constraint registry, and reference photo uploads.
  - `/api/jobs`: Job lifecycle management, scene generation, prompt compilation, output upload, critique, and rework.

### 🔄 Changed
- **PRD Restructuring (v1.0 ➔ v2.0):**
  - Reduced flat 100-section monolithic doc to 7 structured architectural parts.
  - Replaced artificial "7 agents" with an honest, maintainable stateful 6-stage pipeline.
  - Replaced subjective 0-100 decimal scores with deterministic categorical quality gates.
  - Scaled down database from 22 unneeded tables to 9 essential tables.

---

## [Initial Document] — 2026-08-20
- Original 3,141-line product requirements document received and analyzed.
