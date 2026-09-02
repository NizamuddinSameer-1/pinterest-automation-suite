---
aliases:
  - n8n Automation Spec
  - Pinterest n8n Architecture
  - Publishing Webhook Spec
tags:
  - architecture
  - n8n
  - deprecated
  - pinterest
  - publishing
  - webhook
created: 2026-08-21
updated: 2026-08-29
---

# ⚡ n8n Workflow & Pinterest Automation Architecture

> [!WARNING]
> **Deprecated — retained for history only.**
> n8n is no longer part of this codebase. There is no `n8n/` workflow
> directory and no `app/services/n8n_service.py` in the main tree; the only
> copy survives in a `.claude/worktrees` snapshot. Publishing is done by
> `app/services/pinterest_publisher.py` (Playwright) and scheduling by
> `app/services/scheduler.py`.
> This note is linked from ~114 generated notes, so it is kept rather than
> deleted. Do not build against it.

> [!NOTE]
> **System Goal:** Decouple Pinterest publishing, cron scheduling, and multi-channel distribution from the core AI engine by using a local **n8n workflow instance** (`http://localhost:5678`). This eliminates brittle browser scripts and avoids complex Pinterest Developer API review bottlenecks.

---

## 🏗️ Decoupled Webhook Architecture

```
┌───────────────────────────────────────────────────────────┐
│         Pinterest Realism Engine (FastAPI Backend)        │
│  • Generates 9:16 authentic visual variations             │
│  • Enforces physical Product Truth constraints            │
│  • Compiles SEO Titles, Descriptions, Hashtags & Links    │
└─────────────────────────────┬─────────────────────────────┘
                              │
                              │  POST Webhook (Rich JSON Payload)
                              ▼
┌───────────────────────────────────────────────────────────┐
│               Local n8n Workflow Engine                   │
│               (http://localhost:5678)                     │
│                                                           │
│  [Webhook Trigger: /webhook/pinterest-publish]            │
│          │                                                │
│          ├─► [IF Mode == 'schedule']                      │
│          │        │                                       │
│          │        └─► [Wait / Delay Node]                 │
│          │                                                │
│          ▼                                                │
│  [Format & Post Node (Pinterest / Buffer / Social API)]   │
│          │                                                │
│          ▼                                                │
│  [HTTP Callback to PRE Engine: /api/pins/{id}/callback]   │
└─────────────────────────────┬─────────────────────────────┘
                              │
                              │  POST /api/pins/{id}/callback
                              ▼
┌───────────────────────────────────────────────────────────┐
│    PRE SQLite DB & Obsidian Vault Synced to "PUBLISHED"   │
└───────────────────────────────────────────────────────────┘
```

---

## 📦 Dispatched Webhook Payload Schema

When a creator clicks **⚡ Publish via n8n** or **📅 Schedule**, PRE sends this payload to n8n:

```json
{
  "event": "pin_publish_requested",
  "pin_id": "87dae852-19bb-4cfa-81a1-26f634563ac4",
  "job_id": "f671ff4d-3fe0-4132-91e3-39801b7a2e2b",
  "mode": "publish",
  "title": "Look at this cute Two-Piece Ruffled French Maid Costume! 🎃",
  "description": "Obsessed with this Two-Piece Ruffled French Maid Halloween Costume Set! Perfect for this season. Adding to my cozy Pinterest wishlist! (affiliate link)",
  "keywords": [
    "french maid halloween costume",
    "cosplay outfit",
    "aesthetic dress",
    "halloween finds"
  ],
  "destination_url": "https://amazon.com/dp/B0EXAMPLE?tag=myaffiliate-20",
  "board_name": "Halloween Costume Finds & Inspo",
  "product_name": "Two-Piece Ruffled French Maid Halloween Costume Set",
  "image_url": "http://localhost:8000/data/outputs/f671ff4d/flow_var_1.jpg",
  "image_local_path": "C:\\...\\data\\outputs\\f671ff4d\\flow_var_1.jpg",
  "scheduled_time": "2026-08-21T18:00:00.000Z",
  "callback_url": "http://localhost:8000/api/pins/87dae852-19bb-4cfa-81a1-26f634563ac4/callback",
  "is_affiliate": true,
  "disclosure": "affiliate link",
  "is_ai_generated": true,
  "dispatched_at": "2026-08-21T12:00:00.000Z"
}
```

---

## 🔁 Two-Way Callback Specification

Upon completing the publication, n8n sends a simple callback payload to PRE:

- **Endpoint:** `POST /api/pins/{pin_id}/callback`
- **Payload:**
```json
{
  "status": "published",
  "pin_url": "https://www.pinterest.com/pin/123456789012345678/",
  "published_at": "2026-08-21T18:00:05.000Z",
  "board": "Halloween Costume Finds & Inspo"
}
```
- **Outcome:** PRE marks `PinDraft.status = 'published'`, updates `PinDraft.exported_at`, and updates the Obsidian Vault graph node with the clickable live URL.

---

## 🚀 How to Run n8n Locally

1. **Start n8n via Terminal:**
   ```bash
   npx n8n
   ```
   *Or double-click `scripts/start_n8n.bat` in the project root.*

2. **Open Dashboard:**
   Navigate to [http://localhost:5678](http://localhost:5678) in your browser.

3. **Import Ready Workflow:**
   Click **Workflows ➔ Import from File** and select `n8n/pinterest_auto_publisher.json`.

4. **Activate Workflow:**
   Toggle the workflow to **Active** to start listening for webhook triggers from PRE!

---

## 🔗 Related Notes
- [[🏠 Main Dashboard]]
- [[🗺️ System Map & Architecture MOC]]
- [[🛡️ Compliance & Spam Guardrails]]
- [[📋 Redesigned PRD v2]]
