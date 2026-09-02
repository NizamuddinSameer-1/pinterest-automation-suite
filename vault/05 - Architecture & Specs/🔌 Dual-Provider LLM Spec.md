---
aliases:
  - LLM Provider Spec
  - OpenCode AI Spec
tags:
  - llm
  - providers
  - opencode
  - deepseek
  - mimo
created: 2026-08-20
updated: 2026-08-20
---

# 🔌 OpenCode AI Provider Specification

Technical architecture of the unified LLM routing engine powered by **OpenCode AI** (`https://opencode.ai/`).

---

## 🎯 Model Mapping

| Pipeline Operation | Required Capability | Provider | Model Identifier |
| :--- | :--- | :--- | :--- |
| **Stage 1: Reference Analysis** | High-fidelity vision understanding | **OpenCode AI** | `mimo-v2.5` |
| **Stage 2: Visual DNA Extractor** | Fast structured JSON extraction | **OpenCode AI** | `deepseek-v4-flash` |
| **Stage 3: Scene Director** | Contextual reasoning & motivation | **OpenCode AI** | `deepseek-v4-flash` |
| **Stage 4: Prompt Compiler** | Pure Python assembly & sanitizer | *Local Logic* | *(No LLM needed)* |
| **Stage 6: Realism Critic** | Multimodal flaw & defect inspection | **OpenCode AI** | `mimo-v2.5` |
| **Stage 7: Pinterest SEO** | Conversational copy & keyword tags | **OpenCode AI** | `deepseek-v4-flash` |
| **Rework Engine** | Targeted diff & revision directives | **OpenCode AI** | `deepseek-v4-flash` |

---

## ⚙️ Environment Configuration (`.env`)

```env
# ── OpenCode AI (Primary Provider) ───────────────
OPENCODE_API_KEY=sk-c7aqnlGsXYDeMhq63E7bdzILcN6HkJxXAAvDNoS35DuMhH2vvSIQDHeDJgmZCIDQ
OPENCODE_BASE_URL=https://api.opencode.ai/v1
OPENCODE_TEXT_MODEL=deepseek-v4-flash
OPENCODE_VISION_MODEL=mimo-v2.5
```

---

## 🛡️ Reliability & Multimodal Vision Handling
1. **OpenAI-Compatible Vision Payload:** Encodes image files as inline Base64 data URLs (`data:image/jpeg;base64,...`) and sends them to MiMo V2.5 via `/chat/completions`.
2. **Exponential Backoff:** Retries up to 3 times ($2^n$ seconds sleep).
3. **Commentary & Markdown Stripping:** Automatically strips code fences and locates JSON bounds if the model returns surrounding text.
4. **Fallback Safety:** If OpenCode credentials are unavailable, can fall back to Gemini or OpenRouter endpoints.

---

## 🔗 Related Notes
- [[🗺️ System Map & Architecture MOC]]
- [[📋 Redesigned PRD v2]]
- [[BUG-001 - LLM Rate Limit & JSON Parsing Fallback]]
