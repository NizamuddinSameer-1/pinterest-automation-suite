---
aliases:
  - Batch Runner
  - Bulk Generation
tags:
  - idea
  - backlog
  - batch
  - phase2
created: 2026-08-20
updated: 2026-08-20
---

# 💡 Bulk Batch Automation Engine

## 🎯 Concept
Allow a single operator to select a single reference (e.g. `REF-001` Target Clothing Rack) and 20 products from the catalog, generating 20 complete Google Flow job packages with a single click.

---

## 🛠️ Implementation Plan
- Add batch job creation endpoint `POST /api/jobs/batch`.
- Create a multi-job export ZIP containing organized subfolders (`job_001/`, `job_002/`...).
- Bulk output upload drag-and-drop zone in the Creative Lab.

---

## 🔗 Related Notes
- [[Project Roadmap & Milestones]]
- [[🗺️ System Map & Architecture MOC]]
