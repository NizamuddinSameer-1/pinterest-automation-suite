---
aliases:
  - Roadmap
  - Project Plan
  - Milestones
tags:
  - roadmap
  - milestones
  - planning
created: 2026-08-20
updated: 2026-08-20
---

# 🚀 Project Roadmap & Milestones

The strategic phased rollout plan for the **Pinterest Realism Engine (PRE)**.

```
       ┌────────────────────────────────────────────────────────┐
       │                   PHASED ROADMAP                       │
       └───────────────────────────┬────────────────────────────┘
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         ▼                         ▼                         ▼
┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│     PHASE 1      │      │     PHASE 2      │      │     PHASE 3      │
│  Vertical Slice  │ ───► │  Workflow Polish │ ───► │  Scale & Intel   │
│  & Core Pipeline │      │  & Batch Runner  │      │  & Auto-Publish  │
└──────────────────┘      └──────────────────┘      └──────────────────┘
```

---

## 🟢 Phase 1: The Working Vertical Slice (Current Phase)

**Primary Objective:** Deliver a working end-to-end flow from Pinterest Reference Screenshot to Exported Pin Package without modifying code.

### Deliverables Checklist:
- [x] PRD Deep Analysis & V2 Restructure
- [x] SQLite 9-Table Database & SQLAlchemy ORM
- [x] Dual LLM Provider Engine (OpenRouter + Gemini Vision)
- [x] Stage 1: Reference Analyst (Vision 9-Dimension Extractor)
- [x] Stage 2: Visual DNA Extractor (Stable vs Variable Decomposition)
- [x] Stage 3: Scene Director (Believable Scenarios + Motivation)
- [x] Stage 4: Prompt Compiler (13-Section Compiler + Job ZIP Packager)
- [x] Stage 6: Realism Critic (Categorical Quality Gates + Defect Severity)
- [x] Stage 7: Pinterest SEO Metadata Generator
- [x] Rework Engine (Preserve / Fix / Avoid Revisions)
- [x] State Machine & Export Services
- [ ] Pins API Endpoints & Compliance Checkers
- [ ] FastAPI Entry Point (`main.py`)
- [ ] Next.js Frontend Application:
  - [ ] Dashboard Page
  - [ ] Creative Lab (Interactive Pipeline)
  - [ ] Product Library & Product Truth Editor
  - [ ] Pin Composer & Exporter
- [ ] End-to-End Benchmark Validation (10 Sample Pins)

---

## 🟡 Phase 2: Workflow Polish & Batch Runner (Next)

**Primary Objective:** Make daily multi-product generation fast, seamless, and ergonomic for a single operator.

### Key Features:
- [ ] **Batch Generation:** Pair 1 Visual DNA with 20 affiliate products to generate 20 job packages simultaneously.
- [ ] **Visual DNA Comparison Tool:** Compare side-by-side extractions from different references.
- [ ] **Interactive Prompt Sandbox:** Live edit individual prompt chunks and preview assembled output in real-time.
- [ ] **Rejection Feedback Analytics:** Track operator rejection reasons (`#AI_LOOKING`, `#BAD_HANDS`, `#TOO_POLISHED`) to calibrate future prompts.
- [ ] **CSV Product Catalog Import:** Bulk upload 50+ affiliate products with auto-generated Product Truth templates.

---

## 🔵 Phase 3: Scale, Learning Loop & Official APIs (Future)

**Primary Objective:** Automate performance ingestion and allow the system to learn which visual patterns drive actual clicks.

### Key Features:
- [ ] **Official Pinterest API Integration:** Create pins and update boards via `POST /pins` using official OAuth2 tokens.
- [ ] **Automated Performance Tracking:** Pull daily impressions, saves, and outbound clicks.
- [ ] **Visual DNA Learning Loop:** Correlate specific lighting/environment DNA with high CTR to bias future scene generation.
- [ ] **Affiliate Network Auto-Feed Sync:** Direct sync with Amazon Associates, LTK, and ShareASale product feeds.
- [ ] **Automated Trend Scraper:** Periodic ingestion of Pinterest Trends and Google Trends data.

---

## 🔗 Related Notes
- [[🏠 Main Dashboard]]
- [[📋 Redesigned PRD v2]]
- [[Changelog]]
- [[2026-08-20 - Project Inception & Phase 1 Build]]
