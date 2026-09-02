---
aliases:
  - Pinterest API Publishing
  - Direct Pin API
tags:
  - idea
  - backlog
  - phase3
created: 2026-08-20
updated: 2026-08-20
---

# 💡 Automated Pinterest API Publishing

## 🎯 Concept
Once the creator validates the vertical slice manually, integrate direct Pinterest v5 REST API endpoints to publish approved pins with a single click from the **Pin Composer UI**.

---

## 🛠️ Technical Plan
- Implement `PinterestApiPublisher` subclass in `app/providers/pinterest.py`.
- Endpoints utilized:
  - `POST https://api.pinterest.com/v5/pins`
  - `GET https://api.pinterest.com/v5/boards`
- Scopes required: `boards:read`, `pins:read`, `pins:write`.

---

## 🔗 Related Notes
- [[Project Roadmap & Milestones]]
- [[📋 Redesigned PRD v2]]
