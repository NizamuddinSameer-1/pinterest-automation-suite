---
aliases:
  - Architecture MOC
  - System Map
tags:
  - moc
  - architecture
  - backend
created: 2026-08-20
updated: 2026-08-29
---

# 🗺️ System Map & Architecture MOC

How the Pinterest Realism Engine fits together: pipeline stages, the modules
that implement them, and where each one is documented.

Two systems share one spine. **PRE Core** turns a reference photo into
photorealistic pin images. **SmartPickr** turns those images into an editorial
affiliate page. They meet at the `Job` and `Product` records.

---

## 🏛️ Core architectural documents

1. **[[📋 Redesigned PRD v2]]** — product specification.
2. **[[🏗️ Database & State Machine Architecture]]** — SQLite schema, job and pin lifecycles.
3. **[[🔌 Dual-Provider LLM Spec]]** — multi-provider routing and fallback.
4. **[[🛡️ Compliance & Spam Guardrails]]** — Pinterest spam rules, FTC disclosure, AI labelling.
5. **[[📚 Vault Structure & Navigation]]** — what lives in which folder, and which service writes it.

---

## 🔄 Execution pipeline

### Stage 1–4 · Brief building

```
[Reference image]                    app/pipeline/reference_analyst.py
   │  vision: 10 forensic dimensions
   ▼
[Visual DNA]                         app/pipeline/visual_dna.py
   │  reusable photographic fingerprint
   ▼
[Commerce DNA]                       app/pipeline/commerce_strategist.py
   │  hero product, visual hook, click reason
   ▼
[Creative concepts]                  app/pipeline/creative_concepts.py
   │  4-7 distinct angles per job
   ▼
[Scene + 13-section prompt]          app/pipeline/scene_director.py
                                     app/pipeline/prompt_compiler.py
                                     app/pipeline/prompt_modules.py
```

### Stage 5 · Image generation

`app/services/generation.py` is the **only** entry point. It verifies every
returned file on disk and records which backend produced it.

| Backend | Mechanism | Notes |
|---|---|---|
| `flow_ui` | Playwright drives the Flow UI | **primary** — signs in from a persistent profile |
| `flow_api` | Replays a captured request | opportunistic — tokens expire in ~15 min |
| `pollinations` | HTTP image generation | test only, never an automatic fallback |

- **Load balancing** — `app/services/flow_router.py` round-robins 10 Flow workspaces.
- **Post-processing** — `app/services/anti_ai_processor.py` crops the watermark band and injects sensor grain.

### Stage 6 · Quality gates

```
[Realism critic]  app/pipeline/realism_critic.py
[Commerce critic] app/pipeline/commerce_critic.py
[Diversity score] app/pipeline/creative_diversity.py
        │
        ▼
[Final judge]     app/pipeline/final_judge.py   ← 4 gates
        │
   ┌────┴────┐
[PASS]     [REWORK] ──► app/pipeline/rework_engine.py
```

The four gates: **realism** passes, **product** clarity is not low,
**originality** is not a copy, **commerce** click-intent is not low.

### Stage 7–10 · The money path

```
[Editorial lookbook]   app/services/bridge_copilot.py + article_generator.py
        │              templates/bridge_page.html
        ▼
[Git + Vercel deploy]  app/services/git_publisher.py + vercel_publisher.py
        │              cumulative, so live pages never 404
        ▼
[Pin drafts]           app/pipeline/pinterest_seo.py
        ▼
[Pinterest publish]    app/services/pinterest_publisher.py (Playwright)
        │              app/services/schedule_planner.py + scheduler.py
        ▼
[Affiliate link]       app/services/affiliate_router.py  →  /api/go
```

Product data enters through **Amazon PA-API** (`app/services/amazon_paapi.py`,
`app/api/amazon.py`) and is deduplicated by ASIN.

---

## 📁 Codebase cross-reference

| Component | Path | Related note |
| :--- | :--- | :--- |
| Config & env | `app/config.py` | [[🔌 Dual-Provider LLM Spec]] |
| Database & models | `app/models/models.py` | [[🏗️ Database & State Machine Architecture]] |
| LLM routing | `app/providers/llm.py` | [[🔌 Dual-Provider LLM Spec]] |
| Reference analyst | `app/pipeline/reference_analyst.py` | [[🧬 Visual DNA Knowledge Base]] |
| Visual DNA | `app/pipeline/visual_dna.py` | [[🧬 Visual DNA Knowledge Base]] |
| Commerce strategist | `app/pipeline/commerce_strategist.py` | `05 - Architecture & Specs` |
| Scene director | `app/pipeline/scene_director.py` | [[🎨 Prompt Engineering Playbook]] |
| Prompt compiler | `app/pipeline/prompt_compiler.py` | [[🎨 Prompt Engineering Playbook]] |
| Realism critic | `app/pipeline/realism_critic.py` | [[🔍 Realism Critic Defect Taxonomy]] |
| Pinterest SEO | `app/pipeline/pinterest_seo.py` | [[🛡️ Compliance & Spam Guardrails]] |
| Product taxonomy | `app/pipeline/product_taxonomy.py` | [[📐 Product Truth Standards]] |
| Generation orchestrator | `app/services/generation.py` | `08 - Live Generation Nodes/Jobs` |
| Flow automator | `app/services/flow_automator.py` | `05 - Architecture & Specs` |
| Lookbook generator | `app/services/article_generator.py` | `04 - Campaigns & Products/Pins` |
| Amazon ingestion | `app/services/amazon_paapi.py` | `04 - Campaigns & Products/Products` |
| Affiliate router | `app/services/affiliate_router.py` | [[🛡️ Compliance & Spam Guardrails]] |
| Pinterest publisher | `app/services/pinterest_publisher.py` | `08 - Live Generation Nodes` |
| Vault sync | `app/services/vault_sync.py` | [[📚 Vault Structure & Navigation]] |

---

## 🔗 Related notes

- [[🏠 Main Dashboard]]
- [[🐛 Bug Tracker MOC]]
- [[🧪 Experiment & DNA MOC]]
- [[Project Roadmap & Milestones]]
