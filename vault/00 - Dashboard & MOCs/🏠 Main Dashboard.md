---
aliases:
  - Main Dashboard
  - Pinterest Realism Engine Cockpit
tags:
  - dashboard
  - moc
  - index
created: 2026-08-20
updated: 2026-08-29
---
# 🚀 Pinterest Realism Engine — Knowledge & Telemetry Vault

Live knowledge graph for the Pinterest Realism Engine (PRE), synced with the
production database, the pipeline state machine, and the Google Flow batch
generator.

---

## 📊 Live system metrics

| Metric          | Count | Notes                                                                                        |
| --------------- | ----- | -------------------------------------------------------------------------------------------- |
| Campaigns       | `1`   |                                                                                              |
| Products        | `49`  | includes Amazon PA-API ingestions                                                            |
| References      | `95`  |                                                                                              |
| Generation jobs | `82`  | `19` draft · `19` output_uploaded · `12` analyzed · `12` pass · `11` failed · `9` generating |
| Job outputs     | `115` | generated variation images                                                                   |
| Pin drafts      | `114` | `96` draft · `15` published · `3` scheduled                                                  |
| Critiques       | `2`   | quality gate is under-used                                                                   |
| Vault notes     | `393` | across 19 folders                                                                            |

> Snapshot taken 2026-08-29. Re-run `python scripts/vault_regenerate_mocs.py` to refresh.

---

## 🗺️ Maps of content

- [[🗺️ System Map & Architecture MOC]] — pipeline stages, data model, module map.
- [[📚 Vault Structure & Navigation]] — what lives in which folder and why.
- [[🧪 Experiment & DNA MOC]] — Visual DNA library and extraction parameters.
- [[🛍️ Product Catalog & Truth Registry]] — anti-hallucination truth constraints.
- [[🐛 Bug Tracker MOC]] — real bugs, with auto-generated reports archived.

---

## 📁 Folder map

| Folder | Notes |
|---|---|
| `00 - Dashboard & MOCs` | 4 — navigation only |
| `01 - Dev Logs & History` | 6 — dated build history |
| `02 - Bugs & Issues` | 6 active · 111 auto-archived |
| `03 - Pipeline & Visual DNA` | 58 references · 4 knowledge |
| `04 - Campaigns & Products` | 115 pins · 5 products · 2 campaigns |
| `05 - Architecture & Specs` | 5 — specs and PRDs |
| `06 - Ideas & Future Backlog` | 3 |
| `07 - Templates` | 6 |
| `08 - Live Generation Nodes` | 59 jobs · 3 critiques |
| `09 - Archive` | 2 — deprecated and junk |

---

## ⚡ Pipeline at a glance

```
[Reference] ➔ [Visual DNA] ➔ [Commerce DNA] ➔ [13-section prompt]
     ➔ [Google Flow ×4] ➔ [Anti-AI pass] ➔ [Editorial lookbook]
     ➔ [Git + Vercel] ➔ [Pin drafts] ➔ [Pinterest] ➔ [/api/go affiliate link]
```

See [[🗺️ System Map & Architecture MOC]] for the module-level detail.
