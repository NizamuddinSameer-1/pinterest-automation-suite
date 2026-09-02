---
id: BUG-006
title: SQLite Write Lock Held Across LLM Calls Starves All Other Writers
severity: high
status: closed
subsystem: database
created: 2026-08-24
updated: 2026-08-24
resolved: 2026-08-24
assigned: Database Team
tags:
  - bug/resolved
  - severity/high
  - subsystem/database
---

# 🐛 BUG-006: SQLite Write Lock Held Across LLM Calls Starves All Other Writers

## 📋 Summary
Reference image uploads (and any other write) failed with `Upload failed: An internal error occurred…` whenever a prompt preview or a generation-recording step was running. WAL was already enabled (BUG-003 fix), but a single writer that flushes and then awaits an LLM call holds SQLite's one write lock for the whole call — minutes — so every other write timed out.

> **Status: ✅ CLOSED — Fixed 2026-08-24**

---

## 🔍 Root Cause Analysis
WAL allows one writer + many readers, but the write lock is held from the first flush until commit. Two hot paths flushed **first** and called LLMs **after**, still uncommitted:

1. **`POST /api/jobs/preview-prompt`** (`app/api/generation.py`) — `draft_product_from_reference` INSERTs the product (`flush` → lock acquired), then the same request runs `generate_commerce_dna` → `generate_concepts` → `generate_scene` (three LLM round-trips) before the request-end commit.
2. **Generation recording** (`app/services/output_service.py:record_generation_outputs`) — INSERTs JobOutput rows + job state (`flush` → lock acquired), then calls `generate_pin_seo` (LLM) before the caller commits.

Trigger confirmed by paired logs: `AUTO-BUG-20260824_172835` (upload INSERT INTO references) and `AUTO-BUG-20260824_172837` (preview-prompt INSERT INTO products) both waited out `busy_timeout=5000` and died ~5–6 s after their INSERT began, while a third writer sat in its LLM phase. The pattern repeats in bursts all day (17:20, 17:23, 17:26, 17:27, 17:28…).

Contributing factor: `busy_timeout=5000` was shorter than the connect timeout (`timeout=30`) and shorter than any LLM call.

---

## 💥 Impact
- Reference uploads 500 with "Upload failed" whenever a preview/generation ran — the operator's primary workflow.
- Pin updates, job writes and draft inserts failed in the same windows (see the 2026-08-23/24 auto-bug bursts).

---

## 🩹 Resolution (2026-08-24)

### Code Fix 1: `app/api/generation.py` — `preview_prompt_endpoint`
Commit the durable, independent draft-product INSERT **before** the LLM stages:
```python
draft_res = await draft_product_from_reference(req.reference_id, db=db)
product_id = draft_res["product"]["id"]
await db.commit()  # release the write lock before the LLM round-trips
```

### Code Fix 2: `app/services/output_service.py` — `record_generation_outputs`
Commit after outputs + job state are recorded, **before** `generate_pin_seo`:
```python
job.provider = produced_by
await db.flush()
await db.commit()  # outputs are durable; lock released before the SEO LLM call
```
`expire_on_commit=False` keeps all mapped objects usable; the final commit stays with the caller as before. If SEO fails, the outputs are already durable — which the `PinCopyUnavailable` path always intended.

### Code Fix 3: `app/database.py`
- `PRAGMA busy_timeout` 5000 → **15000** (aligned with the 30 s connect timeout; short legitimate locks are out-waited, real starvation still fails fast).
- **New:** `init_db` now runs `_add_missing_columns` — `PRAGMA table_info` per table + `ALTER TABLE ADD COLUMN` for model columns the file lacks. This closes the *other* outage class from 2026-08-24 (`GET /api/jobs` → `no such column: jobs.commerce_dna_json`, 20+ auto-logs) that happened because `create_all` never alters existing tables.

### What changed
- [x] No write transaction spans an LLM call on either hot path.
- [x] busy_timeout raised to 15 s.
- [x] Startup auto-migration for newly mapped nullable columns (idempotent; warns and skips FK/default/not-null columns).
- [x] Verified: migration unit-tested on a DB copy (adds missing columns, preserves data, idempotent); 13/13 tests pass; live `POST /api/references` returns 201.

### Follow-up
- [ ] The live DB sits inside the OneDrive-synced Desktop folder. OneDrive grabbing `pre.db`/`pre.db-wal` for sync can cause lock errors of its own (and WAL files + file sync is a known corruption risk). Consider moving `data/` (or the whole project) out of OneDrive, or excluding it from sync.

---

## 📎 Related Auto-Bugs
- [[AUTO-BUG-20260824_172835 - Unhandled Exception on POST apireferences]] — the upload failure
- [[AUTO-BUG-20260824_172837 - Unhandled Exception on POST apijobspreview-prom]] — the preview-prompt failure
- `AUTO-BUG-20260824_0842xx` / `_1424xx` (GET /api/jobs) — the schema-drift class, now covered by `_add_missing_columns`

---

## 🔗 Related Notes
- [[BUG-003 - SQLite Concurrent Writes & Async Session Locks]] — the earlier WAL fix this builds on
- [[🐛 Bug Tracker MOC]]
- [[Issues Tracker Index]]
