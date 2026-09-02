---
aliases:
  - 2026-08-23 Dev Log
  - Pin Update Greenlet Fix
tags:
  - devlog
  - api
  - pins
  - fixes
created: 2026-08-23
updated: 2026-08-23
---

# 📅 Dev Log: 2026-08-23 — Pin Update Greenlet Fix & Publish Guard Explained

## 📌 Summary
After your Pinterest upload system improvements, `PUT /api/pins/{id}` started `500` and wiped the `destination_url` on every save, so publish kept `409`. Fixed in `app/api/pins.py:1215` and documented in real time.

---

## 🐛 Errors You Saw (from your log)

- **12:49:24 & 12:50:54 `PUT /api/pins/efb1e040…` → `500 Internal Server Error`**
  ```
  sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called
  app/api/pins.py:303 in update_pin → _serialize_pin
  app/api/pins.py:1217 if getattr(pin, "output", None) and pin.output:
  ```
  Auto-logged as `AUTO-BUG-20260823_071924` and `AUTO-BUG-20260823_072054`.

- **Repeated `POST /api/pins/efb1e040…/publish` → `409 Conflict`**
  ```
  This pin has no destination URL, so it would publish with nothing to click…
  ```
  UI banner: “Direct browser publish failed: This pin has no destination URL…” (screenshot).

---

## 🔍 How I Diagnosed It

1. **Read your log verbatim** — `MissingGreenlet` points to lazy load outside greenlet, not to Pinterest.
2. **Opened `app/api/pins.py:265` `update_pin`**: does `await db.get` + `flush` + `refresh` then `return _serialize_pin(pin)` where `1217` does `pin.output` lazy.
3. **Checked `app/models/models.py:PinDraft`** — `output` is `relationship(back_populates="pin_draft")` lazy by default.
4. **Traced the rollback**: `app/database.py:49` `except: rollback` — the `UPDATE` succeeded (`UPDATE pin_drafts SET destination_url=? ('https://amzn.to/4xWPJbg')`) but the later serialize threw, so the transaction rolled back and `GET /api/pins` still showed old value, hence publish guard kept 409.
5. **Noticed `create_pin_draft` same pattern**, `list_pins`/`get_pin` already use `selectinload` and were fine.

---

## 🩹 How I Solved It

### 1. `app/api/pins.py:1215` `_serialize_pin` — no lazy load
```python
# before (triggered IO):
if getattr(pin, "output", None) and pin.output:
    image_path = pin.output.image_path
# after (dict check, no IO):
output = pin.__dict__.get("output")
if output is not None:
    image_path = output.image_path
```

### 2. `app/api/pins.py:265` `update_pin` + `app/api/pins.py:84` `create_pin_draft` — eager load
```python
await db.flush()
res = await db.execute(select(PinDraft).options(selectinload(PinDraft.output)).where(PinDraft.id == pin_id))
pin = res.scalars().first()
```

### 3. Verified on live DB (pin `efb1e040`)
```
before: (empty) / Halloween Home Decor
after flush+select: https://amzn.to/4xWPJbg
serialize ok: https://amzn.to/4xWPJbg image_path data/outputs/67f008e1...
commit ok - no MissingGreenlet
persisted: https://amzn.to/4xWPJbg
```
After fix: `PUT` returns 200 with `image_path`, `POST /publish` no longer 409 when link set.

---

## ✅ What the 409 Actually Means (not a bug)

`app/api/pins.py:38 _link_problem()` blocks affiliate pins with no `destination_url` because Pinterest pins **cannot add a link after publishing** — you’d have to delete and remake. `409` with message “Pass `allow_no_link=true` to publish without one on purpose” is intentional. After this fix, set `Affiliate Destination URL` (e.g., `https://amzn.to/4xWPJbg`) and publish succeeds.

---

## 🗂️ Vault Updates (this session)

- Created `BUG-005` and this dev log
- Marked `AUTO-BUG-20260823_071924` + `AUTO-BUG-20260823_072054` as `resolved` with root cause + fix link
- Updated `🐛 Bug Tracker MOC`, `Issues Tracker Index`, `🏠 Main Dashboard`, `Changelog` to `v2.1.2`

---

## 🔗 Related Notes
- [[BUG-005 - Pin Update MissingGreenlet & Destination Rollback]]
- [[AUTO-BUG-20260823_071924 - Unhandled Exception on PUT apipinsefb1e040-c348]]
- [[AUTO-BUG-20260823_072054 - Unhandled Exception on PUT apipinsefb1e040-c348]]
- [[🐛 Bug Tracker MOC]]
- [[🏠 Main Dashboard]]
