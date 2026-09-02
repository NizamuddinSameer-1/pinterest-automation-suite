---
aliases:
  - PRD v2
  - Product Requirements Document
  - Spec
tags:
  - prd
  - specification
  - architecture
created: 2026-08-20
updated: 2026-08-20
version: 2.0
---

# 📋 Pinterest Realism Engine — Redesigned PRD v2

**Version:** 2.0  
**Status:** Build-ready MVP specification  
**Operator:** Single creator  
**Market:** US  
**Initial niche:** Fashion + seasonal lifestyle (Halloween / Fall 2026)  
**Image generation:** Google Flow, human-in-the-loop  
**LLM/Vision:** Dual-Provider (OpenRouter Text + Gemini AI Studio Vision)  
**Local GPU:** None required

---

## 📌 Executive Summary & Core Loop

```
Reference Image ──► Visual DNA ──► Product + Scene ──► Prompt Compiler ──► Google Flow ──► Realism Critic ──► Pin Package
```

The system transforms casual Pinterest reference images into original, affiliate-ready UGC creatives by reverse-engineering photographic behavior and enforcing strict physical product fidelity.

---

## 🏛️ Key System Specs & Cross-Links

- **Database Architecture:** [[🏗️ Database & State Machine Architecture]] (9 tables, async SQLite)
- **Dual LLM Provider Layer:** [[🔌 Dual-Provider LLM Spec]] (OpenRouter + Gemini)
- **Visual DNA Standards:** [[🧬 Visual DNA Knowledge Base]]
- **Prompt Playbook:** [[🎨 Prompt Engineering Playbook]]
- **Quality Gates:** [[🔍 Realism Critic Defect Taxonomy]]
- **Compliance Rules:** [[🛡️ Compliance & Spam Guardrails]]
- **Roadmap & Phases:** [[Project Roadmap & Milestones]]

---

## 🎯 Core Operating Principles

| ID | Principle | Core Rule |
| :--- | :--- | :--- |
| **P1** | Realism before beauty | Must feel believable as a normal photo before looking aesthetic |
| **P2** | Behavior over keywords | No "8K masterpiece" — model camera, lighting, and sensor physics |
| **P3** | Context creates realism | Products must sit in logical environments (racks, carts, hands) |
| **P4** | Motivation is mandatory | Every scene requires a stated reason why someone photographed it |
| **P5** | Imperfection is intentional | Subtle real-world flaws without making the image look broken |
| **P6** | Product truth is sacred | Never invent colors, patterns, or features not on the real product |
| **P7** | Originality over copying | Extract photographic style, never replicate composition |
| **P8** | Human approval gate | AI prepares the creative, human conducts generation and final approval |
| **P9** | Provider independence | Core business logic never hardcodes generator-specific APIs |
