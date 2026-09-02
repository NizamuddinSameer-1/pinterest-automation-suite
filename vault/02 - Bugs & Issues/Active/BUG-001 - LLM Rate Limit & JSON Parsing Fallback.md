---
id: BUG-001
title: OpenRouter Rate Limit & Robust JSON Parsing Fallback
severity: high
status: open
subsystem: llm
created: 2026-08-20
updated: 2026-08-20
assigned: Backend Team
tags:
  - bug/open
  - severity/high
  - subsystem/llm
---

# 🐛 BUG-001: OpenRouter Rate Limit & Robust JSON Parsing Fallback

## 📋 Summary
When utilizing free-tier models on OpenRouter (e.g. DeepSeek v4 Flash) or high-concurrency requests, response payloads may occasionally return HTTP 429 (Rate Limit) or enclose JSON structures within markdown commentary / code fences that can cause naive `json.loads()` calls to fail.

---

## 🔍 Root Cause Analysis
1. **Free-tier Rate Limits:** Free models enforce strict queries-per-minute (QPM) ceilings.
2. **LLM Output Formatting Drift:** Models occasionally precede JSON with pleasantries ("Sure, here is the JSON...") or wrap responses in ```` ```json \n ... \n ``` ```` despite `response_format={"type": "json_object"}`.

---

## 💥 Impact
- Pipeline halts during Stage 2 (Visual DNA) or Stage 3 (Scene Director).
- Unhandled JSON errors lead to 500 Internal Server Errors in FastAPI route handlers.

---

## 🛠️ Reproduction Steps
1. Send 10 rapid scene generation requests to `/api/jobs/{id}/scene`.
2. Observe provider returning a raw markdown fence or throttling status code.

---

## 🩹 Implemented / Proposed Solution
- [x] **Exponential Backoff:** Implemented 3-attempt retry loop with $2^n$ second backoff in `app/providers/llm.py`.
- [x] **Markdown Stripper:** Added `_parse_json()` helper that strips leading/trailing markdown fences (` ``` `).
- [ ] **Dual Fallback Route:** If OpenRouter repeatedly fails with 429, automatically fallback structured calls to the Gemini API endpoint.

---

## 🔗 Related Notes
- [[🔌 Dual-Provider LLM Spec]]
- [[🐛 Bug Tracker MOC]]
- [[Issues Tracker Index]]
