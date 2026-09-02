---
id: BUG-005
title: Pin Update MissingGreenlet & Destination Rollback on PUT /api/pins/{id}
severity: high
status: closed
subsystem: api
created: 2026-08-23
updated: 2026-08-23
resolved: 2026-08-23
tags:
  - bug/resolved
  - severity/high
  - subsystem/api
---

# 🐛 BUG-005: Pin Update MissingGreenlet & Destination Rollback

## 📋 Summary
`PUT /api/pins/{pin_id}` returned `500 MissingGreenlet` after your Pinterest upload improvements, and the `destination_url` you typed was lost on every save, so `POST /api/pins/{id}/publish` kept returning `409 "no destination URL"`. UI showed red banner “Direct browser publish failed: This pin has no destination URL…” even though you had just pasted `https://amzn.to/4xWPJbg`.

> **Status: ✅ CLOSED — Fixed 2026-08-23 13:00 UTC**

---

## 🔍 Root Cause Analysis

| Layer | Symptom | Root cause |
|---|---|---|
| **Serialize** | `sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called` at `app/api/pins.py:1217` | `_serialize_pin()` is sync but did `if getattr(pin, "output", None) and pin.output:` — that `pin.output` is a lazy `relationship` and triggers `await_only()` which needs a greenlet. Outside `selectinload`, it fails. |
| **Update path** | `PUT` logged `UPDATE pin_drafts SET destination_url=?` then `ROLLBACK` | `update_pin` did `await db.flush()` + `await db.refresh(pin)` then called `_serialize_pin(pin)` which threw, so `app/database.py:49` `except: rollback` wiped the update. |
| **Publish guard** | `POST /publish` kept `409 Conflict` “no destination URL” | Not a second bug — the guard `app/api/pins.py:38 _link_problem()` is correct (affiliate pins must not publish without a link). Because PUT rolled back, `destination_url` stayed empty, so the guard kept firing. |
| **Create path** | Same lazy load risk on draft creation | `create_pin_draft` had identical `refresh` + `_serialize_pin` pattern. |

Reproduced in `vault/02 - Bugs & Issues/AUTO-BUG-20260823_071924` and `AUTO-BUG-20260823_072054` — both `PUT /api/pins/efb1e040…` with identical stack through `_serialize_pin`.

---

## 🩹 Resolution (2026-08-23)

### `app/api/pins.py:1215` — make serialization greenlet-safe
```python
def _serialize_pin(pin: PinDraft) -> dict:
    # was: if getattr(pin, "output", None) and pin.output:  # ← lazy load
    output = pin.__dict__.get("output")  # no lazy load
    if output is not None:
        image_path = output.image_path
```

### `app/api/pins.py:265` `update_pin` + `84` `create_pin_draft` — eager load
```python
await db.flush()
# replaced: await db.refresh(pin)
res = await db.execute(
    select(PinDraft).options(selectinload(PinDraft.output)).where(PinDraft.id == pin_id)
)
pin = res.scalars().first()
```
Same fix applied to `create_pin_draft`. Now `image_path` is available without lazy IO, and `PUT` no longer throws.

### Verification (real DB `efb1e040-c348-4c95-92d9-8d3fa77d1e9e`)
```
before: (empty) / Halloween Home Decor
after flush+select: https://amzn.to/4xWPJbg
serialize ok: https://amzn.to/4xWPJbg image_path data/outputs/67f008e1...
commit ok - no MissingGreenlet
persisted: https://amzn.to/4xWPJbg
```
`GET /api/pins` and `POST /publish` (with `destination_url` set) now succeed; `409` only fires when link truly missing (intended guard).

---

## 📎 Related Auto-Bugs
- `AUTO-BUG-20260823_071924` — first PUT failure (12:49:24)
- `AUTO-BUG-20260823_072054` — second PUT failure (12:50:54) after you re-pasted `https://amzn.to/4xWPJbg`
- Both now marked `resolved`, root cause BUG-005.

---

## 🔗 Related Notes
- [[🏗️ Database & State Machine Architecture]]
- [[🐛 Bug Tracker MOC]]
- [[2026-08-23 - Pin Update Greenlet & Publish Guard Fix]]
