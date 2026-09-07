# Trend Radar v2 — Design Spec (2026-09-07)

Status: user-approved (all 4 sections). Next: implementation plan via writing-plans.

## 1. Goal

Upgrade the Trend Radar from a thin demo (Google Shopping autocomplete +
hardcoded seeds + demo fallbacks) into a full pipeline:
free trend signals → blended score → stored keyword packs → launch →
pins + blog reading the same pack → click feedback improving scores.

Scope decisions (locked in brainstorming):
- Sources: all free sources; no paid APIs.
- Keywords feed blog + pins together from one pack.
- Ranking: blended score (demand + money + winnability).
- Build order: A (scheduled radar + packs) → C (learn loop) with B
  (on-demand deep scan) extended from the existing custom-query box.

## 2. Architecture

Five bounded units, each independently understandable and testable:

| # | Unit | Does | Interface | Depends on |
|---|------|------|-----------|------------|
| 1 | Source clients | Fetch one signal each, fail-soft, 6–10s timeout | `fetch_*() -> {items, status: fresh/stale}` | httpx/BS4 only |
| 2 | Scheduler | Daily fan-out scan, writes snapshot | `run_scan() -> snapshot_id` | Unit 1 |
| 3 | Scorer | Pure blended-score function | `score(signals, weights) -> {score, tier, breakdown}` | Nothing (pure) |
| 4 | Keyword packs | Build/store/version one pack per dossier | `pack` schema on dossier; `packs_version` | Units 2–3, content lane (drafts only) |
| 5 | Learn loop | Click logging + CTR factor | `POST /api/analytics/click`, `clicks` table | Edge fn, scorer |

Existing pieces reused unchanged: `TREND_SEEDS` (as bootstrap queries only —
scores no longer hardcoded), PA-API matcher, demo-guard + `DEMO_ASINS`,
launch-campaign gating, dual LLM lanes (content lane drafts packs).

## 3. Data flow

Scheduled: scheduler → source clients (parallel) → dossiers with per-source
status → scorer → keyword pack draft (content lane, cached) →
`data/trend_radar/<date>.json` snapshot + per-dossier record.
On-demand: custom query → live clients → same scorer/pack path →
24h per-query cache + click debounce.
Launch: dossier (+pack version pinned) → gated launch-campaign →
`generate_batch_pins_seo(pack)` + `generate_bridge_copy(pack)` →
pins + lookbook sections share vocabulary.
Learn: `/api/go` click ping → `clicks` table → trailing-30d CTR per niche →
4th scoring factor at weight 0 until 100 clicks.

## 4. Scoring

`score = 0.40*demand + 0.35*money + 0.25*winnability`, each 0–100 normalized
per scan. Demand: autocomplete breadth + Trends slope. Money: price ×
commission band. Winnability: inverse big-brand token dominance in
suggestions. Weights in settings; dossier stores `score_breakdown` +
`weights_version`. Tiers: S ≥ 85, A ≥ 70, else B (same bands as today).

## 5. Keyword pack schema

`{primary: str, long_tails: str[3-8], hooks: {variation_index, framework}[],
board_angle: str, negative_terms: str[], pack_version: int}`.
Consumers accept an optional pack and fall back to current behavior when
absent (backward compatible). New pack versions apply to new generations
only — live campaigns are never silently rewritten.

## 6. Error handling

Per-source fail-soft with fresh/stale status surfaced in UI; scheduler never
fails a whole scan on one source. LLM pack drafting is cached and optional —
dossier without a pack still launches (consumers fall back). Click endpoint
fire-and-forget (never blocks redirects). `demo_only` rule extends to all
trend products: invented ASINs can never reach launch.

## 7. Testing

Scorer fixtures (pure function, incl. weight-version cases); per-client
offline fixtures (recorded responses); pack-schema contract tests for both
consumers; launch-guard tests extended (demo + orphan rules already exist);
vault-sync mocked in all generation tests (stops real-vault pollution).

## 8. Out of scope

Paid trend APIs; Pinterest login-walled scraping; automatic board creation
changes; SEO-instruction tuning (separate future pack); backfilling packs
for historic dossiers.
