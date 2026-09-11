# Lookbook Blog System — Deep SEO Audit
**Date:** 2026-09-11 · **Auditor:** WorkBuddy AI · **Scope:** Lookbook blogs, pin SEO, titles, descriptions, site & blog ranking, trend system keyword reading
**Evidence base:** live source, `data/pre.db` (66 pins / 26 products / 48 jobs / 101 outputs), 19 lookbook HTML files, live HTTP probes of `pinterest-lookbooks-beta.vercel.app`, git history.

---

## 0. Headline: 3 things are actively costing you money

| # | Problem | Scale | Impact |
|---|---|---|---|
| **1** | **Pin destinations are 404** | 9 of 16 distinct destinations dead; **4 of 11 published pins** point at dead pages | Every click from those pins dies. Pinterest demotes dead-link pins. Pure lost revenue. |
| **2** | **Your local repo is 18 commits behind `origin/main`** | Entire Trend Radar v2 system missing locally | You are auditing/editing old code. The `[Store]` and `(Look #N)` bugs are **already fixed upstream** — you just don't have the fix. |
| **3** | **Slug architecture creates duplicate pages per product** | 6 distinct pages all targeting "black leggings" | Keyword cannibalisation — your own pages compete with each other and none ranks. |

---

## 1. What the system actually is

Two systems sharing one spine:

```
PRE Core (image engine)                SmartPickr Lookbook (money pages)
reference → Visual DNA → 13-sec   →    bridge_copilot (LLM copy)
prompt → Google Flow 4 variations →    article_generator (WebP + Jinja2)
→ anti-AI post-process → critique      → bridge_page.html (15-block editorial)
                                       → git_publisher → vercel_publisher
                                       → Pinterest pins → affiliate link
```

**Blog generation path**

| Stage | Module | What it does |
|---|---|---|
| Copy | `app/services/bridge_copilot.py` | 1 structured LLM call → headline, subheadline, looks, comparison matrix, UGC narrative, pros/cons, buyer persona, FAQ, verdict |
| Assemble | `app/services/article_generator.py` | WebP compression (<100 KB/img), slug creation, OG image extraction, Jinja2 render |
| Template | `app/templates/bridge_page.html` | 15-block editorial layout, single H1, canonical, OG, Twitter, Schema.org `@graph` |
| Deploy | `git_publisher.py` → `vercel_publisher.py` | Commit `data/lookbooks/` to GitHub → cumulative Vercel deploy (prevents 404 snapshot wipes) |
| Publish | `pinterest_publisher.py` | Playwright on persistent profile → `data/pinterest_profile/` |
| Money | `affiliate_router.py` | `/api/go?asin=…&subid=sp_j_{job}_p_{pin}_v_{idx}` · US `nizamuddinsam-20` · IN `nizamuddins0a-21` |

**On-page SEO that is genuinely good** (verified in generated HTML):
- Single `<h1>` (correct — only one per page)
- Self-referencing `rel="canonical"` ✓
- OpenGraph with correct 1080×1920 for Pinterest rich pins ✓
- Twitter `summary_large_image` ✓
- Schema.org `@graph`: `Product` + `Offer` + `FAQPage` ✓
- FTC disclosure placed **above** the first CTA (statutorily correct) ✓
- Internal content cluster links (related reviews, sidebar + footer) ✓

---

## 2. CRITICAL — Your local checkout is missing the Trend Radar v2 system

```
local  main : 0 commits ahead, 18 commits BEHIND origin/main
```

The entire trend system exists **only** on `origin/main` and `feat/trend-radar-v2`:

| File | Local disk | origin/main |
|---|---|---|
| `app/services/trend_research.py` | ✗ missing | ✓ |
| `app/services/trend_sources.py` | ✗ missing | ✓ |
| `app/services/trend_scorer.py` | ✗ missing | ✓ |
| `app/services/keyword_packs.py` | ✗ missing | ✓ |
| `app/services/trend_scheduler.py` | ✗ missing | ✓ |
| `app/services/trend_provenance.py` | ✗ missing | ✓ |
| `app/services/pinterest_trends_scraper.py` | ✗ missing | ✓ |
| `frontend/src/components/TrendRadar.tsx` | ✗ missing | ✓ |
| `scripts/scrape_trends_worker.py` | ✗ missing | ✓ |
| `tests/test_trend_*.py` (4 files) | ✗ missing | ✓ |
| `app/pipeline/pinterest_seo.py` | **old version** (no `FRAMEWORKS`, no `generate_batch_pins_seo`) | **new version** (6 title frameworks + batch) |

Only stale `.pyc` bytecode remains in `app/services/__pycache__/` — which is why the trend system appears to exist but has no source.

**Fix:** `git pull origin main` (or `git checkout feat/trend-radar-v2`).

### Why this matters for SEO specifically

The upstream `pinterest_seo.py` contains a **6-framework title engine** and an explicit anti-duplication rule that your live pins violate:

> *"NEVER use generic duplicated titles like `(Look #2)` or `(Look #3)`. Every variation must have a distinct angle and hook."*

```
FRAMEWORKS = [
  The Skeptical Micro-Review      → "Honestly didn't expect this [Product] to look this good"
  The Practical Problem-Solver    → "Finally found a [Product] that actually [Benefit]"
  The Real-Life Preview           → "What this [Product] looks like in real daily life"
  The Curation & Vibe Anchor      → "The exact [Product] aesthetic for your [Outfit]"
  The Value / Smart Pick Hook     → "Skip the overpriced brand — same [Feature]"
  The Daily Routine Utility       → "How I'm styling this [Product] for [Setting]"
]
```

Plus a vision-grounded title formula: `[Aesthetic] + [Item Type] + [Amazon Signal] + [Year]`.

**Every pin title problem in §5 below is already solved in the code you don't have checked out.**

---

## 3. CRITICAL — Dead destinations (404)

Live probe of every distinct pin destination:

| Destination | Live | Pins | Status |
|---|---|---|---|
| `wishten-3-pcs-pumpkin-costume-for-women--5d692a6d.html` | **404** | 4 | 🔴 published pin dead |
| `halloween-pajama-pants-for-women-spooky--2c6bd84e.html` | **404** | 4 | 🔴 published pin dead |
| `adult-pumpkin-costume-poncho-set-8e518cf4.html` | **404** | 3 | 🔴 published pin dead |
| `black-leggings-5fa494c3.html` | **404** | 4 | 🔴 |
| `black-leggings-84153c9d.html` | **404** | 4 | 🔴 |
| `black-leggings-cc6a4c9b.html` | **404** | 4 | 🔴 |
| `black-leggings-2c9aae73.html` | **404** | 4 | 🔴 |
| `leggings-f5c95d65.html` | **404** | 4 | 🔴 |
| `lighted-human-dog-skeleton-halloween-dec-7c336083.html` | **404** | 4 | 🔴 |
| `maid-costume-87a5f232.html` | 200 | 4 | ✅ |
| `maid-costume-34e3b588.html` | 200 | 2 | ✅ |
| `early-september-nails-viral-inspo-guide-4146d8b2.html` | 200 | 4 | ✅ |
| `reference-product-88729bb1.html` | 200 | 4 | ⚠️ junk slug |
| `/?topic=early+september+nails` | 200 | 6 | ⚠️ homepage, not an article |
| **(empty)** | — | **8** | 🔴 earns nothing |

**Root cause:** `data/lookbooks/` is a separate git repo deployed cumulatively. Pages were generated locally but never pushed — so they exist in `data/pre.db` as destinations while the live edge has no such file. `LOOKBOOK_GIT_AUTO_PUSH` was off and the batch push never ran for those jobs.

**Also:** `data/lookbooks/` on disk has 19 HTML files but the **live sitemap only lists 15 URLs**, and pages like `black-leggings-*.html` exist in neither.

---

## 4. Website / blog ranking infrastructure

### 4.1 Domain authority ceiling
```
https://pinterest-lookbooks-beta.vercel.app
```
- Shared `*.vercel.app` domain — no independent domain authority
- Contains **"beta"** — signals non-production to both users and crawlers
- No custom domain configured (`BRIDGE_DOMAIN` points at the beta host)

**This is the single largest structural ranking handicap.** Google can index it, but you're competing for "black leggings"-class keywords from a shared subdomain with zero backlink equity. A real domain (e.g. `smartpickr.com`) is the highest-leverage SEO change available.

### 4.2 Test pages are publicly deployed AND in the sitemap
These are live, indexable, and listed in `sitemap.xml` with `priority 0.8`:

```
test-tldr-render.html
test-compliance-job.html
classic-cast-iron-skillet-test-com.html
job-batch-777.html
test-job.html
prod-test-job.html
job1.html
prod-job1.html
```

Thin/duplicate test pages diluting a brand-new domain is a real crawl-budget and quality-signal problem. **They should be excluded from the sitemap and `noindex`-ed (or deleted).**

### 4.3 Structured data policy risk ⚠️
`bridge_page.html` emits:
```json
"aggregateRating": {
  "@type": "AggregateRating",
  "ratingValue": "{{ product_data.get('star_rating') }}",
  "reviewCount": "{{ product_data.get('review_count', 100) }}"
}
```
`reviewCount` **defaults to a fabricated `100`**, and the master guide describes scores like `9.8 / 10` that are LLM-invented. Google's structured-data policy requires ratings to reflect genuine reviews. Invented `AggregateRating` is a **manual-action risk** (rich-result suppression, or a spam action on the domain).

**Fix:** only emit `aggregateRating` when real Amazon review data exists (PA-API), otherwise drop the block.

### 4.4 What's missing for ranking
- **No `Article`/`BlogPosting` schema** — only `Product` + `FAQPage`. A blog review should carry `Article` with `author`, `datePublished`, `dateModified`, `publisher`.
- **No `BreadcrumbList`** — despite the template rendering breadcrumbs visually.
- **No author entity page / `Person` schema** — E-E-A-T needs a real author surface.
- **No `hreflang`** despite US/IN geo-targeted affiliate routing.
- **`lastmod` in sitemap is "today" for every URL on every regeneration** — Google learns to distrust `lastmod` when it always equals build time.
- **No analytics/click tracking** — `/api/go` redirect lives on Vercel, so there's no local CTR feedback loop (acknowledged as backlog "Learning Engine & CTR Feedback Loop").

---

## 5. Pin SEO audit — titles, descriptions, boards

### 5.1 Titles

| Metric | Value |
|---|---|
| Total pins | 66 |
| Average title length | **58 chars** |
| Titles > 60 chars | 16 / 66 |
| Max title length | 72 chars |
| Pins sharing a title with another pin | **16 / 66** |
| Titles containing literal `[Store]` placeholder | **13** (1 is LIVE) |
| Titles with leading `"` artifact | 5 |
| Titles with `**` markdown artifact | 1 |
| Titles truncated mid-word | 4 |

**The `[Store]` leak — live on Pinterest right now:**
```
I Found The Cutest Adult Pumpkin Costume Poncho Set at [Store] (Look #2)   ← PUBLISHED
I Found The Coolest Black Leggings at [Store]
I Found The Comfiest Black Leggings at [Store] (Look #4)
```
Cause: the old `pinterest_seo.py` SYSTEM_PROMPT gives the pattern
`"I Found The Cutest [Product] at [Store]"` and the model copied the bracket
placeholder literally instead of filling it. Upstream now guards this.

**Mid-word truncation** (something cuts at ~72 chars):
```
... Lingerie | Surprising Quality Amazon Find (202      ← "(2026)" cut
... Nails | Nail Polish Colors | Amazon Find (20        ← "(2026)" cut
```

**Duplicate titles from the `(Look #N)` artifact:**
```python
# app/services/output_service.py:284
title=base_title if idx == 1 else f"{base_title} (Look #{idx})"
```
This is a developer artifact leaking into public Pinterest titles. Pinterest treats near-duplicate titles from the same account as low-quality/spam signal.

### 5.2 Descriptions

| Metric | Value |
|---|---|
| Average length | 196 chars |
| Min / Max | 126 / 322 chars |
| Under 100 chars | 0 ✓ |
| Empty | 0 ✓ |
| Over 500 (Pinterest cap) | 0 ✓ |
| **Pins sharing an identical description** | **40 / 66** |

Description length discipline is good. But the generator writes **one description and reuses it for all 4 variations**:
```python
description=seo_data["description"],   # identical for every output in the job
```
So a job's 4 pins are 4 identical descriptions attached to 4 near-identical images — the classic footprint Pinterest's spam filter looks for. Each variation should get its own angle-matched description (the `FRAMEWORKS` rotation upstream does exactly this).

### 5.3 Keywords — the healthiest part

0 / 66 pins have empty keywords. Top terms:

```
black leggings 23 · casual wear 19 · leggings for women 19 · cell phone pocket 12
early september nails 12 · amazon find 10 · amazon 8 · trendy outfits 8 · yoga pants 8
```

⚠️ `amazon find` (10) and `amazon` (8) as *keywords* are wasted — "Amazon" is a brand term you can't rank for and it signals affiliate intent to Pinterest. Drop them.

### 5.4 Boards — 6 pins use a product title as the board name

```
BOARD: "Early September Nails (Viral Inspo Guide)"   ×6
```
That's the product/article title, not a real board. Publishing to a non-existent or title-named board splits topical authority. Boards should be stable, keyword-rich hubs (`Fall Nail Inspo`, `Cozy Fall Outfits`) — the upstream `board_catalog.py` grounds suggestions in your real boards.

---

## 6. Root cause: the slug architecture (your cannibalisation engine)

`app/services/article_generator.py:155-156`:

```python
prod_name_slug = re.sub(r"[^a-zA-Z0-9]+", "-", raw_prod_name.lower()).strip("-")[:40]
slug = f"{prod_name_slug}-{job_id[:8]}"
```

**Two design flaws:**

**(a) Hard `[:40]` truncation** — cuts mid-word and can land on a separator:

| Generated slug | Should be |
|---|---|
| `lighted-human-dog-skeleton-halloween-dec-7c336083` | `...halloween-decoration-...` |
| `classic-cast-iron-skillet-test-com` | `...test-compliance` |
| `linen-duvet-cover-job-batc` | `...job-batch` |
| `wishten-3-pcs-pumpkin-costume-for-women--5d692a6d` | double hyphen from truncation |
| `halloween-pajama-pants-for-women-spooky--2c6bd84e` | double hyphen |

**(b) `job_id[:8]` suffix = a new URL every run for the same product:**

```
black-leggings-5fa494c3.html   ← 4 pins
black-leggings-84153c9d.html   ← 4 pins
black-leggings-cc6a4c9b.html   ← 4 pins
black-leggings-2c9aae73.html   ← 4 pins
leggings-f5c95d65.html         ← 4 pins
```
**6 distinct pages competing for "black leggings"** — plus the same pattern for nails (3 pages) and pumpkin (2). Google sees near-duplicate thin pages on one domain and picks none. This is the #1 on-site ranking blocker after the 404s.

**Fix direction:** slug = stable product-derived canonical (`black-leggings-crz-yoga`) with **no job_id suffix**; deduplicate at generation time and 301 the variants into the canonical. Keep job_id in the *filename* only for internal traceability, never in the public URL.

Also: `reference-product-88729bb1.html` is a junk slug receiving 4 pins — the fallback name `"Reference Product"` reached production. Fallback should be a real keyword or the article should not be generated.

---

## 7. Your trend system — keyword reading

### 7.1 How it works

Entry points (`app/api/research.py`):

| Endpoint | Purpose |
|---|---|
| `GET /api/research/trends` | Trend Radar dossier list (scored + packs) |
| `POST /api/research/query` | On-demand deep scan of any custom keyword (24 h cache) |
| `POST /api/research/launch-campaign` | Trend → job, threading `keyword_pack` |
| `GET /api/research/pinterest-official-trends` | Official Pinterest Trends (live) |
| `GET /api/research/pinterest-official-trends/detail` | Deep dive: metric + related keywords + popular pins |
| `POST /api/research/import-pin-reference` | Import a real viral pin as a generation reference |
| `POST /api/research/launch-inspo-campaign` | Inspo-driven campaign launch |

**Scoring** — blended, weights in config (`0.40 demand / 0.35 money / 0.25 winnability`), tiers `S ≥ 85`, `A ≥ 70`, else `B`. Signals blend from **measured** Pinterest data where available, falling back to proxies — with explicit provenance labels (`pinterest_measured` vs `autocomplete_breadth_proxy`, `live_products` vs `neutral_no_data`).

**Keyword packs** (`keyword_packs.py`) — the shared vocabulary between pins and blogs:
```python
KeywordPack(primary, long_tails[], hooks[{variation_index, framework}],
            board_angle, negative_terms, pack_version)
```
Hooks rotate `FRAMEWORKS` round-robin so **no two variations share a title angle**. Stored on the job as `jobs.keyword_pack_json` (`models.py:149`). Consumed optionally by `generate_pin_seo` and `generate_bridge_copy` — full backward fallback when absent.

This is a genuinely well-designed subsystem. Two things to know:

### 7.2 `trend_provenance.py` — your anti-fabrication guard ✅
A dependency-free CI contract that refuses to let invented numbers ship unlabeled. It knows the exact hardcoded sparkline shapes that were historically fake:
```python
PLACEHOLDER_SPARKLINES = frozenset({
    (10, 20, 35, 50, 75, 100),
    (10, 15, 20, 28, 38, 50, 65, 80), ...
})
```
Any "live" trend item carrying one of these without a fallback flag is flagged as lying about its chart. **This is excellent engineering** — keep it and extend it to the `AggregateRating` problem in §4.3.

### 7.3 Keyword-reading issues found

**(a) A typo is shipping as a keyword** — `pinterest_trends_scraper.py:1131`:
```python
"nail inspoo",     # ← should be "nail inspo"
```
Any pin or blog seeded from the nail family inherits a broken search term.

**(b) Hardcoded year stamps go stale:**
```python
"september nails ideas 2026"
"fall nails 2026 trends"
"halloween nail art 2026"
"fall hair colors 2026 warm tones"
"bob haircuts fall 2026"
```
In January 2027 these become actively harmful (mismatched intent). Year should be injected from the current date, not typed.

**(c) Curated families are not measured data.** The docstring is honest about it:
> *"These are GENERATED suggestions for discovery/seeding — NOT measured Pinterest data. Callers must present them as such."*

Only 5 families are curated (`blazer`, `nail`, `halloween`, `football/game day`, `hair`); everything else falls to a generic template:
```python
[f"{clean} ideas", f"{clean} outfit", f"oversized {clean}", ...]
```
For a 23-category taxonomy, 5 curated families is thin — and the fallback produces near-identical keyword sets for unrelated products, which is how `reference-product` pages ended up with nail keywords.

**(d) `related_searches_provenance` must be surfaced in the UI.** Since these are generated, not measured, showing them without the label is the same class of problem `trend_provenance.py` was built to prevent.

---

## 8. Supporting data health

| Entity | Count | Note |
|---|---|---|
| Campaigns | 1 | |
| Products | 26 | **only 12 have an ASIN** → 14 fall back to keyword search, losing affiliate attribution |
| Products with `affiliate_url` | 17 / 26 | 9 products cannot monetise |
| Jobs | 48 | 27 `OUTPUT_UPLOADED`, **12 `FAILED`**, 4 `DRAFT`, 2 `PROMPT_READY`, 2 `ANALYZED`, 1 `PASS` |
| Job outputs | 101 | |
| Critiques | **2** | vs 101 outputs — the 4-gate quality loop is effectively unused |
| Pin drafts | 66 | 55 `draft`, 11 `published` |
| Lookbooks on disk | 19 | live sitemap lists 15 |

- **12 FAILED jobs** — all from "No generation backend produced images" (Google Flow automation).
- **Only 1 job ever reached `PASS`** — the realism critic isn't being run, so quality gates aren't gating anything.
- **55 draft pins never published** — the largest untapped asset you have, but they inherit the `[Store]` / duplicate-description problems, so they should not be bulk-published as-is.

---

## 9. Priority action list

### P0 — this week (money is leaking now)

1. **`git pull origin main`** — recover the entire Trend Radar v2 system and the 6-framework title engine. Everything in §5 is already fixed there.
2. **Fix or delete the 9 dead destinations.** Either regenerate + push the missing lookbooks, or update `pin_drafts.destination_url` to live pages. **4 published pins are currently linking to 404s.**
3. **Fix the live `[Store]` pin** — `I Found The Cutest Adult Pumpkin Costume Poncho Set at [Store] (Look #2)` is public. Edit the title on Pinterest.
4. **Set a destination for the 8 empty-destination pins** (or mark them rejected so they can't publish).

### P1 — next 2 weeks (ranking foundation)

5. **Slug fix in `article_generator.py:155-156`** — remove `[:40]` truncation (use word-boundary truncation), remove the `job_id[:8]` suffix, dedupe per product, 301 existing variants to a canonical.
6. **Point 6 homepage-destination pins at their real article URLs** (`/?topic=…` is not an article).
7. **Remove test pages** from `sitemap.xml` and add `noindex` (or delete) — `test-*`, `prod-*`, `job1`, `job-batch-777`.
8. **Gate `aggregateRating`** behind real PA-API review data; drop the fabricated `reviewCount: 100` default.
9. **Add `Article` + `BreadcrumbList` + `Person` schema** to `bridge_page.html`.
10. **Buy a real domain.** Move off `*-beta.vercel.app`. Highest-leverage ranking change available.

### P2 — next month (scale + quality)

11. **Per-variation descriptions** — stop reusing one description across 4 pins (40/66 affected).
12. **Fix the `nail inspoo` typo** and replace hardcoded years with a dynamic year.
13. **Expand curated keyword families** beyond 5, and surface `related_searches_provenance` in the UI.
14. **Rebuild boards as stable keyword hubs**; stop using article titles as board names.
15. **Run the critique loop** — 2 critiques vs 101 outputs means your 4-gate quality system isn't running.
16. **Fix ASIN coverage** (12/26) so 14 products stop degrading to keyword search.
17. **Wire click/conversion tracking** — without it you can't tell which titles actually work.

---

## 10. What's already strong (don't rebuild these)

- **FTC compliance** — disclosure above the fold, before any CTA. Legally correct and rare.
- **Editorial architecture** — the 15-block structure (verdict box → comparison matrix → UGC narrative → looks → fabric → pros/cons → persona → FAQ → cluster) is genuinely magazine-grade.
- **`trend_provenance.py`** — an anti-fabrication CI contract with placeholder-sparkline detection. Sophisticated.
- **Keyword packs** — versioned, shared between pins and blog, framework-rotated hooks. Clean design.
- **Cumulative Vercel deploy** — the pattern that prevents 404 snapshot wipes is correct; it simply wasn't invoked for 9 pages.
- **On-page fundamentals** — single H1, canonical, OG, Pinterest 1080×1920 OG image, internal cluster links. All correct.

The engineering is strong. The failures are **operational** (pages not deployed, local repo stale) and **URL-level** (slug strategy), not architectural.

---

# 11. Remediation log — what was actually changed

Executed 2026-09-11 after the audit. Two commits in the main repo, one in the
`data/lookbooks` repo. Test suite: **186 passed** (13 new).

### 11.1 Recovered the trend system ✅
`git merge --ff-only origin/main` — 18 commits, 1216 files. Backup tag
`backup-pre-trend-pull-20260911` created at the pre-pull HEAD (`4f1e749`).

Verified on disk afterwards: `trend_research.py` (1095 lines), `trend_sources.py`,
`trend_scorer.py`, `keyword_packs.py`, `trend_scheduler.py`, `trend_provenance.py`,
`pinterest_trends_scraper.py` (1889 lines), `TrendRadar.tsx` (2666 lines),
`scrape_trends_worker.py`, 5 trend test files. `pinterest_seo.py` is now the new
version with `FRAMEWORKS` (6) + `generate_batch_pins_seo`. 43 trend tests pass.
App boots clean.

### 11.2 Fixed the slug generator (root cause of cannibalisation) ✅
`app/services/article_generator.py`

- Added `slugify_product_name()` — word-boundary truncation (60 chars), separator
  collapsing. No more `--`, no more `…halloween-dec` / `…test-com` / `…job-batc`.
- Added `build_canonical_slug()` — **stable per product**. ASIN-disambiguated so
  two products sharing a title stay distinct (the two Wedtrend tea dresses);
  job hash only as a fallback for no-ASIN placeholders.
- Moved ASIN resolution above the slug build, since the slug now depends on it.

Verified: `Black Leggings` + ASIN across 3 different job ids → one identical slug.
`tests/test_canonical_slug.py` (13 tests) pins the contract.

### 11.3 Removed test scaffolding from the index ✅
- `git_publisher.is_public_lookbook_slug()` — single predicate consulted by both
  the catalog grid and the sitemap, so they can never disagree.
- `scripts/quarantine_test_lookbooks.py` — added `noindex, nofollow` to the 11
  test pages **already live on the edge** (reversible; originals in
  `data/lookbooks/.quarantine_backup/`, now gitignored).
- Sitemap went from 15 URLs (8 of them test pages at priority 0.8) to 4: the
  homepage plus 3 real reviews.

### 11.4 Corrected the canonical host ✅
`app/config.py` — `bridge_domain` defaulted to `""` and fell back to
`VERCEL_PROJECT_NAME`, i.e. `pinterest-lookbooks.vercel.app`. With `.env` absent
(and it is absent — see 11.6) every canonical, `og:url`, sitemap entry and smart
redirect would have advertised **the wrong host**.

Verified by probe: `pinterest-lookbooks.vercel.app` has no sitemap and 404s on
lookbook paths; `pinterest-lookbooks-beta.vercel.app` serves the catalog and
sitemap. The default now names the beta host — the one the pins actually use.

### 11.5 Repointed the dead pin destinations ✅
`scripts/remediate_pin_destinations.py`

| Pin | Was | Now |
|---|---|---|
| WISHTEN Pumpkin Costume | 404 page | `B0CHQJLQTC` |
| Halloween Pajama Pants | 404 page | `B07WPLQXFK` |
| 3× Maid Costume | 404 / live-but-no-ASIN | Avidlove `B0C6JMBCLB` |
| Pumpkin poncho (`[Store]` pin) | 404 page | WISHTEN `B0CHQJLQTC` |

All 6 now route through `/api/go`. Verified live: **HTTP 302 → Amazon with the
affiliate tag and `ascsubtag` attribution intact.**

Dead destinations: **10 → 0.**

Five published nail pins have no ASIN equivalent (no nail product exists in the
catalogue) and were reported for review rather than silently rewritten.

> ⚠️ **Pinterest stores the destination on the pin.** The live pins still point
> at the old URLs. Each of the 6 must be edited on Pinterest (or deleted and
> republished) before the fix is live. **This is the remaining P0 action.**

### 11.6 New finding: `.env` is missing
There is no `.env` file. The app runs entirely on `config.py` defaults, so every
documented setting in `CONTEXT_FOR_AI.md` §8 (LLM keys, Flow project URLs, Vercel
token, git remote, `LOOKBOOK_GIT_AUTO_PUSH`) is absent. This is very likely why
the 9 lookbook pages were generated locally but never pushed — the auto-push
path had no remote or token configured.

**This is now the highest-priority follow-up**: without it, newly generated
lookbooks will keep accumulating locally instead of deploying.

### 11.7 Still open (P1)
- `aggregateRating` fabricated `reviewCount: 100` in `bridge_page.html`
- Missing `Article` / `BreadcrumbList` / `Person` schema
- `nail inspoo` typo + hardcoded `2026` years in the trend keyword families
- 40/66 pins share an identical description
- Real domain to replace `*-beta.vercel.app`
- 12 FAILED jobs; critiques = 2 vs 101 outputs

