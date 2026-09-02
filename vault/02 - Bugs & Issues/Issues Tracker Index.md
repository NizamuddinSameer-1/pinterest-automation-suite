---
aliases:
  - Bug Index
  - Issue Index
tags:
  - moc
  - bugs
  - index
created: 2026-08-20
updated: 2026-08-29
---
# 🐛 Issues Tracker Index

**Hand-tracked bugs only.** Auto-captured exceptions are archived in
`02 - Bugs & Issues/_Archive - Auto Bugs/` — 111 notes
that would otherwise bury the 6 real ones.

---

## Active issues

| ID                                                                                | Title                                                      | Severity | Status | Subsystem |
| --------------------------------------------------------------------------------- | ---------------------------------------------------------- | -------- | ------ | --------- |
| [[BUG-001 - LLM Rate Limit & JSON Parsing Fallback\|BUG-001]]                     | LLM Rate Limit & JSON Parsing Fallback                     | high     | open   | llm       |
| [[BUG-002 - Gemini Vision Image Payload Base64 Overhead\|BUG-002]]                | Gemini Vision Image Payload Base64 Overhead                | medium   | open   | pipeline  |
| [[BUG-003 - SQLite Concurrent Writes & Async Session Locks\|BUG-003]]             | SQLite Concurrent Writes & Async Session Locks             | medium   | closed | database  |
| [[BUG-004 - Playwright Profile Lock & Subprocess Event Loop Resolution\|BUG-004]] | Playwright Profile Lock & Subprocess Event Loop Resolution | HIGH     | CLOSED | —         |
| [[BUG-005 - Pin Update MissingGreenlet & Destination Rollback\|BUG-005]]          | Pin Update MissingGreenlet & Destination Rollback          | high     | closed | api       |
| [[BUG-006 - SQLite Write Lock Held Across LLM Calls\|BUG-006]]                    | SQLite Write Lock Held Across LLM Calls                    | high     | closed | database  |

---

## Auto-captured exceptions

Written by `log_runtime_bug` whenever an unhandled exception escapes the API.
They land in `_Archive - Auto Bugs/` and are grouped by endpoint.

| Endpoint | Notes |
|---|---|
| `POST /api/jobs/*` | 87 |
| `POST /api/references/*` | 14 |

---

## Related

- [[🐛 Bug Tracker MOC]]
- [[🏠 Main Dashboard]]
