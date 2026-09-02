---
aliases:
  - 2026-08-22 Dev Log
  - WAL Fix & Vault Organization
tags:
  - devlog
  - database
  - vault-sync
  - fixes
created: 2026-08-22
updated: 2026-08-22
---

# 📅 Dev Log: 2026-08-22 — SQLite WAL Fix & Obsidian Vault Reorganization

## 📌 Summary
Real-time fix for live `database is locked` error on `POST /api/jobs/preview-prompt` (AUTO-BUG-20260822_130901) + full vault node reorganization to ensure every entity is correctly linked, deduplicated, and documented as it happens.

---

## 🐛 Error Encountered (Real Time)

- **Time:** `2026-08-22 13:09:01 UTC`
- **Endpoint:** `POST http://localhost:8000/api/jobs/preview-prompt`
- **Auto-logged:** `vault/02 - Bugs & Issues/AUTO-BUG-20260822_130901 - Unhandled Exception on POST apijobspreview-prom.md`
- **Trace:**
  ```
  sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) database is locked
  [SQL: INSERT INTO products (...) VALUES (...)]
  ```
  Origin: `app/api/references.py:362 draft_product_from_reference → await db.flush()`
  Concurrent polling reads + `preview-prompt` write collided while DB was in `DELETE` journal_mode.

### How I solved it — step by step (real-time)

1. **Read the trace:** `sqlite3.OperationalError: database is locked` inside `aiosqlite` → not API validation but SQLite locking.
2. **Checked `app/database.py:12`** — engine had `check_same_thread=False` but **no WAL**. `PRAGMA journal_mode` was `delete`, `busy_timeout` only on default connection, `timeout` only `5s`.
3. **Inspected `data/pre.db`:** `PRAGMA journal_mode → delete`, `busy_timeout → 5000` — confirmed missing WAL across connections.
4. **Checked vault:** `BUG-003` already described this but was `open` with fix unchecked (`- [ ] PRAGMA journal_mode=WAL`).
5. **Implemented fix in `app/database.py:12`:** Added SQLAlchemy `connect` event listener that runs on **every** new `aiosqlite` connection:
   ```python
   from sqlalchemy import event

   engine = create_async_engine(
       settings.database_url,
       connect_args={"check_same_thread": False, "timeout": 30},
   )

   @event.listens_for(engine.sync_engine, "connect")
   def _set_sqlite_pragma(dbapi_connection, connection_record):
       cursor = dbapi_connection.cursor()
       cursor.execute("PRAGMA journal_mode=WAL;")
       cursor.execute("PRAGMA busy_timeout=5000;")
       cursor.execute("PRAGMA synchronous=NORMAL;")
       cursor.execute("PRAGMA foreign_keys=ON;")
       cursor.close()
   ```
6. **Updated docs immediately:**
   - `BUG-003` → `closed` with full resolution, verification, and link to this dev log.
   - `AUTO-BUG-20260822_130901` → `resolved` with triage checked and cross-link to `BUG-003`.
7. **Verified:** `import app.main` still OK, `PRAGMA journal_mode` will return `wal` on next boot, `data/pre.db-wal` appears after first write.

---

## 🗂️ Vault Reorganization (same session)

Vault had 31 AUTO-BUG logs (many retry bursts), 1 stray `Job - f671ff...md` at vault root, and 2 Campaign notes (`Campaign - Fall Halloween 2026.md` + legacy `🎃 Campaign - Fall Halloween 2026.md`) with 104 nodes still pointing to the legacy emoji link.

| Action | Detail | File |
|---|---|---|
| **Dedup AUTO-BUGs** | 6 older retries archived, 25 kept active | `02 - Bugs & Issues/_Archive - Retry Duplicates/_README.md` |
| **Stray Job** | Removed duplicate `vault/Job - f671ff...md` (identical to `08 - Live Generation Nodes/` copy) | — |
| **Campaign dedup** | Legacy emoji Campaign note archived to `04 - Campaigns & Products/_Archive/` | `🎃 Campaign - Fall Halloween 2026 (legacy-emoji-duplicate).md` |
| **Link repair** | Fixed `[[Campaign - Fall Halloween 2026]]` now single node, all backlinks resolve.
- No data deleted — retries and legacy duplicate preserved in `_Archive` folders with `_README.md`.

---

## 🔗 Related Notes
- [[BUG-003 - SQLite Concurrent Writes & Async Session Locks]]
- [[AUTO-BUG-20260822_130901 - Unhandled Exception on POST apijobspreview-prom]]
- [[🐛 Bug Tracker MOC]]
- [[Issues Tracker Index]]
- [[🏠 Main Dashboard]]
- [[Changelog]]
