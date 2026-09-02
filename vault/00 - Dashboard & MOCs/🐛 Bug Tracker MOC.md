---
aliases:
  - Bug Tracker
  - Issues MOC
tags:
  - moc
  - bugs
  - issues
created: 2026-08-20
updated: 2026-08-20
---

# 🐛 Bug Tracker & Issue MOC

Central tracking hub for all bugs, edge cases, provider timeouts, schema validations, and runtime exceptions encountered during development and operation.

---

## 🚦 Issue Status Overview

```
                      ┌────────────────────────┐
                      │   TOTAL ISSUES LOGGED  │
                      └───────────┬────────────┘
                                   │
                  ┌────────────────┴────────────────┐
                  ▼                                 ▼
         ┌─────────────────┐               ┌─────────────────┐
         │  🔴 OPEN (2)    │               │  🟢 RESOLVED(2) │
         └─────────────────┘               └─────────────────┘
```

*Last updated: 2026-08-29 — vault reorganised; 111 auto-captured reports moved to
`02 - Bugs & Issues/_Archive - Auto Bugs/` so they stop burying the hand-tracked issues.*

---

## 📋 Active Issues Registry

| Issue ID | Severity | Title | Area | Status | Target Fix |
| :--- | :---: | :--- | :--- | :---: | :---: |
| **[[BUG-001 - LLM Rate Limit & JSON Parsing Fallback]]** | `High` | OpenRouter Rate Limit & Robust JSON Sanitization | LLM Provider | 🔴 Open | Phase 1 |
| **[[BUG-002 - Gemini Vision Image Payload Base64 Overhead]]** | `Medium` | Large Image Payloads Causing Gemini Payload Latency | Pipeline / Vision | 🔴 Open | Phase 1 |

## ✅ Resolved Issues Archive

| Issue ID | Severity | Title | Area | Status | Resolved |
| :--- | :---: | :--- | :--- | :---: | :---: |
| **[[BUG-003 - SQLite Concurrent Writes & Async Session Locks]]** | `Medium` | SQLite `database is locked` on Parallel Job Processing | DB / Storage | 🟢 Resolved | 2026-08-22 |
| **[[BUG-004 - Playwright Profile Lock & Subprocess Event Loop Resolution]]** | `High` | Playwright Profile Lock & Subprocess NotImplementedError | Flow / Playwright | 🟢 Resolved | 2026-08-21 |

---

## 🤖 Auto-captured exceptions

`log_runtime_bug` writes one note per unhandled API exception. Those are
**not** issues to triage — they are telemetry. They live in
`02 - Bugs & Issues/_Archive - Auto Bugs/` (111 notes), grouped by endpoint.

Promote one to `Active/` only when it has a reproduction and an owner; otherwise
it is noise from a single bad run.

---

## 🏷️ Issue Categorization Guide

When creating a new bug using `[[📝 Template - Bug Issue]]`, assign appropriate tags:

### By Severity:
- `#severity/blocker` — Halts execution pipeline entirely
- `#severity/high` — Core stage error, prompt generation failure
- `#severity/medium` — Degraded performance, retry delays
- `#severity/low` — Cosmetic, minor UI/UX glitch

### By Subsystem:
- `#subsystem/llm` — OpenRouter / Gemini API issues
- `#subsystem/pipeline` — Analysis, DNA, Scene, Compiler, Critic
- `#subsystem/database` — SQLite, SQLAlchemy, ORM mappings
- `#subsystem/storage` — Filesystem paths, ZIP exports, permissions
- `#subsystem/frontend` — Next.js UI, state sync, preview rendering

---

## 📈 Known Root Causes & Resolution Playbooks

### 1. Markdown Code Fences in JSON LLM Responses
- **Symptom:** `json.decoder.JSONDecodeError` when LLMs wrap outputs in ```` ```json ... ``` ````.
- **Fix:** Use regex and strip line markers before invoking `json.loads()` (see `app/providers/llm.py` `_parse_json`).

### 2. Missing Product Truth Attributes
- **Symptom:** Prompt compiler raises compilation error due to empty `must_preserve`.
- **Fix:** Default `must_preserve` to product's `key_attributes` or fallback to general category tags.

### 3. File Path Traversal & Windows Slashes
- **Symptom:** Cross-platform path errors when creating job packages or serving exports.
- **Fix:** Always wrap filesystem paths in `pathlib.Path` objects.

---

## 🔗 Related Notes
- [[🏠 Main Dashboard]]
- [[Issues Tracker Index]]
- [[📝 Template - Bug Issue]]
