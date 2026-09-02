# Pinterest Realism Engine — Complete System Map
*Verified against live source and `data/pre.db` on 2026-08-29. Supersedes `CONTEXT_FOR_AI.md` for anything Amazon/Lookbook/Commerce related.*

---

## 1. The one-sentence version
Take a real product → generate photorealistic UGC-style pin images with AI → wrap them in a magazine-grade editorial review page → publish to Pinterest → route clicks through your own affiliate link.

## 2. Two systems, one spine

| # | System | Purpose | Entry point |
|---|---|---|---|
| A | **PRE Core** (Pinterest Realism Engine) | Reference photo → Visual DNA → 13-section prompt → Google Flow images → critique | `app/api/jobs.py`, `app/api/generation.py` |
| B | **SmartPickr Editorial Lookbook** | Amazon product → editorial blog page → Vercel → affiliate link | `app/api/amazon.py`, `app/api/lookbooks.py` |

They join at **`Job`** and **`Product`**. System A makes the images; System B turns them into money pages.

---

## 3. Full pipeline (stage by stage)

### Stage 1–4 · Brief building (System A)
| Stage | Module | Output |
|---|---|---|
| 1. Reference ingest | `pipeline/reference_analyst.py` | 10-dimension forensic photo analysis (lighting, camera, skin, texture, imperfection) |
| 2. Visual DNA | `pipeline/visual_dna.py` | Reusable photographic style fingerprint → `visual_dnas` |
| 3. Commerce DNA | `pipeline/commerce_strategist.py` | `hero_product`, `visual_hook`, `must_show`, `click_reason` → `jobs.commerce_dna_json` |
| 3b. Concepts | `pipeline/creative_concepts.py` | 4–7 distinct concepts (desire / detail / lifestyle / discovery) → `jobs.concepts_json` |
| 4. Scene + prompt | `pipeline/scene_director.py`, `prompt_compiler.py`, `prompt_modules.py` (1000 modules) | 13-section sensory prompt → `prompt_versions` |

### Stage 5 · Image generation (the fragile part)
`services/generation.py` is the **single** entry point. Backends:

| Backend | How | Status |
|---|---|---|
| `flow_ui` | Playwright drives Google Flow UI with persistent profile `data/flow_profile` | **Primary** (doesn't expire) |
| `flow_api` | Replays captured request `data/captured_flow_session.json` | Secondary — reCAPTCHA/OAuth tokens die in ~15 min |
| `pollinations` | HTTP image gen, condensed prompt | Test only; never auto-fallback |

Guards worth knowing: every returned file is verified on disk (`MIN_IMAGE_BYTES = 5000`), paths normalised to `data/outputs/<job>/`, empty prompts refused, explicit backend never silently substituted.

**Load balancing:** `services/flow_router.py` round-robins 10 Google Flow workspaces (`data/flow_projects.json`) so no single canvas bloats.

**Post-processing:** `services/anti_ai_processor.py` — FFmpeg chain (crop 120px watermark band → warm colour balance → contrast/saturation → unsharp → vignette → ISO grain) to break the AI signature. Falls back to PIL if FFmpeg missing.

### Stage 6 · Quality gates
`pipeline/realism_critic.py` + `commerce_critic.py` + `creative_diversity.py` → `pipeline/final_judge.py` applies a **4-gate rule**:
1. REALISM — realism critique PASS
2. PRODUCT — product clarity + prominence not low
3. ORIGINALITY — not a COPY of the reference
4. COMMERCE — click intent + desire not low

Fail → `pipeline/rework_engine.py` builds PRESERVE / FIX / AVOID instructions → new prompt version.

### Stage 7 · The money page (System B)
`services/bridge_copilot.py` (LLM copy) → `services/article_generator.py` (WebP base64 <100KB/img, Jinja2) → `templates/bridge_page.html`.

15-block editorial structure: masthead → headline → **top FTC disclosure (before any CTA)** → hero → verdict buy box → 3-tier comparison matrix → 5-stage "I tested" UGC narrative + 30-day log → sequential looks → fabric deep dive → honest pros/cons → buyer persona → FAQ accordion → related reviews cluster → final verdict → sticky mobile bar.

Ships with OpenGraph + Schema.org `@graph` (Product + Review + FAQPage).

### Stage 8 · Deploy
`services/git_publisher.py` commits `data/lookbooks/` to GitHub → `services/vercel_publisher.py` deploys **cumulatively** (all lookbooks at once, so live pages never 404). Local-first when `LOOKBOOK_GIT_AUTO_PUSH=False`; preview at `http://127.0.0.1:8000/lookbooks/{job_id}`.

### Stage 9 · Publish to Pinterest
`services/pinterest_publisher.py` — Playwright on persistent profile `data/pinterest_profile`. `services/publish_runs.py` spawns `scripts/publish_bg.py` as a **child process**, tracks progress via `spec.json` / `status.json` IPC. `services/schedule_planner.py` spaces bulk pins; `services/scheduler.py` drains due pins in-process (with catch-up sweep on boot).

### Stage 10 · Affiliate monetisation
`services/affiliate_router.py` builds first-party smart links:
```
https://pinterest-lookbooks-beta.vercel.app/api/go?asin={ASIN}&q={keywords}&subid=sp_j_{job}_p_{pin}_v_{idx}
```
Tags: US `nizamuddinsam-20`, IN `nizamuddins0a-21`. Missing ASIN → keyword search fallback with tag attached.

---

## 4. Automation inventory

| Automation | Mechanism | Trigger |
|---|---|---|
| Image generation | Playwright child process (`run_flow_bg.py`) | `POST /api/jobs/{id}/generate` |
| Pinterest publish | Playwright child process (`publish_bg.py`) | `POST /api/pins/bulk-publish` |
| Pinterest scheduling | In-process loop + native Pinterest scheduler | `POST /api/pins/bulk-schedule` |
| Board catalogue refresh | Playwright (`refresh_boards_bg.py`) | `POST /api/pins/boards/refresh` |
| Lookbook deploy | Git push + Vercel REST | `POST /api/jobs/{id}/lookbook` |
| Obsidian vault sync | `services/vault_sync.py` + `scripts/sync_all_to_vault.py` | `POST /api/vault/sync`, auto |
| Auto bug logging | `services/error_diagnostics.py` global handler | On any unhandled exception |
| Scheduler catch-up | Sweep on FastAPI lifespan startup | App boot |

---

## 5. Data model (10 tables)
`campaigns` → `references` → `reference_analyses` / `visual_dnas`
`products` (holds `product_truth_json` — immutable physical constraints)
`jobs` (`commerce_dna_json`, `concepts_json`, `current_state`) → `prompt_versions` → `job_outputs` → `critiques` → `pin_drafts`

Job states: `DRAFT → ANALYZED → SCENE_GENERATED → PROMPT_COMPILED → GENERATING → OUTPUT_UPLOADED → PASS / REWORK / FAILED`
Pin states: `draft → approved → scheduled → scheduled_pinterest → published`

---

## 6. Live production state (2026-08-29)

| Entity | Count |
|---|---|
| References | 95 |
| Products | 49 |
| Jobs | 82 (12 PASS, 19 OUTPUT_UPLOADED, 19 DRAFT, 12 ANALYZED, **11 FAILED, 9 stuck GENERATING**) |
| Job outputs | 115 |
| Critiques | **2** |
| Pin drafts | 114 (96 draft, 15 published, 3 scheduled) |
| Lookbooks on disk | 28 |
| Flow workspaces | 10 |

---

## 7. Open issues found during this pass

**Blocking revenue**
1. `frontend/src/components/AmazonSearchModal.tsx` is **orphaned** — never imported. The Amazon discovery/ingest UI is dead code in the running app.
2. Published pins point at **placeholder URLs** (`https://amzn.to/example-maid-costume`, `https://affiliate.example.com/pumpkin-pjs`, one empty string). Those pins earn nothing.

**Reliability**
3. All 11 FAILED jobs: "No generation backend produced images" — Google Flow automation failing.
4. 9 jobs stuck in `GENERATING` with no timeout/reaper.
5. `critiques` = 2 rows vs 115 outputs — the 4-gate quality loop is effectively unused.

**Data hygiene**
6. Product dedup is ASIN-only → ~20 non-Amazon duplicates ("Leather Jacket" ×11, "Reference Product" ×7).
7. 5 INR products, only 1 has `asin_in` → India geo-fallback degrades to keyword search for 4.

**Housekeeping**
8. `CONTEXT_FOR_AI.md` is stale (missing amazon/lookbook/affiliate/commerce modules).
9. `n8n/` workflow and `n8n_service.py` no longer exist in the main tree — only in `.claude/worktrees`.
10. 11 modified + new files uncommitted on `master`; 4 dangling `.claude` worktrees; `data/flow_profile` (Chrome profile) + debug screenshots in the repo.
11. No click/conversion tracking table — the `/api/go` redirect lives on Vercel, so there's no local feedback loop. (Listed in backlog as "Learning Engine & CTR Feedback Loop".)

**Checked and NOT a bug:** INR product prices (₹9,895 etc.) are correct — `currency` column matches, the parser reads symbol + whole/fraction from the same `.a-price` node.
