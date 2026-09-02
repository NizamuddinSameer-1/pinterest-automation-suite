---
id: BUG-003
title: SQLite Concurrent Writes & Async Session Locks on Batch Jobs
severity: medium
status: closed
subsystem: database
created: 2026-08-20
updated: 2026-08-22
resolved: 2026-08-22
assigned: Database Team
tags:
  - bug/resolved
  - severity/medium
  - subsystem/database
---

# 🐛 BUG-003: SQLite Concurrent Writes & Async Session Locks on Batch Jobs

## 📋 Summary
When multiple parallel jobs or background tasks attempt to write to SQLite simultaneously, `sqlite3.OperationalError: database is locked` can occur if transaction lifetimes overlap or WAL mode is not enabled.

> **Status: ✅ CLOSED — Fixed 2026-08-22**

---

## 🔍 Root Cause Analysis
- SQLite default journal mode (`DELETE`) locks the entire database file during writes.
- `aiosqlite` requires WAL (Write-Ahead Logging) mode and a reasonable `timeout` parameter to allow concurrent reads while a single write commits.
- **Trigger confirmed:** `AUTO-BUG-20260822_130901` — `POST /api/jobs/preview-prompt` raised:
  ```
  sqlite3.OperationalError: database is locked
  sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) database is locked
  [SQL: SELECT ... FROM jobs ...]
  ```
  Concurrent `preview-prompt` write + polling reads collided under `DELETE` mode with only `busy_timeout=5000ms` on one path but no WAL.

---

## 💥 Impact
- Batch processing 10-20 jobs concurrently can intermittently throw database lock exceptions.
- Live reproduction: `2026-08-22 13:09:01 UTC` blocked prompt preview for end user.

---

## 🩹 Resolution (2026-08-22)

### Code Fix: `app/database.py:12`
```python
from sqlalchemy import event

engine = create_async_engine(
    settings.database_url,
    echo=(settings.app_env == "development"),
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

### What changed
- [x] Set `check_same_thread=False` in SQLite engine initialization.
- [x] **NEW** — `PRAGMA journal_mode=WAL;` enabled via SQLAlchemy `connect` event (applies to every new `aiosqlite` connection, not just the first).
- [x] **NEW** — `PRAGMA busy_timeout=5000;` ensures 5s retry instead of immediate `database is locked`.
- [x] Added `PRAGMA synchronous=NORMAL;` (safe with WAL) and `PRAGMA foreign_keys=ON;`.
- [x] Raised `connect_args.timeout` from default `5s` → `30s` for multi-worker contention.

### Verification
- `PRAGMA journal_mode` now returns `wal` (verified via `app/database.py` event).
- Re-tested `POST /api/jobs/{id}/preview-prompt` under concurrent polling — no lock error.
- Existing WAL artefacts: `data/pre.db-wal` and `data/pre.db-shm` observed after first write, confirming WAL active.

### Follow-up
- [ ] Future migration path: PostgreSQL for multi-user/multi-worker deployments (tracked in [[🧪 Experiment & DNA MOC]]).

---

## 📎 Related Auto-Bug
- [[AUTO-BUG-20260822_130901 - Unhandled Exception on POST apijobspreview-prom]] — primary reproduction, now archived as resolved reference.

---

## 🔗 Related Notes
- [[🏗️ Database & State Machine Architecture]]
- [[🐛 Bug Tracker MOC]]
- [[2026-08-22 - SQLite WAL & Vault Repair]]
