"""
Vault Maintenance — Archive stale notes, create missing product notes, regenerate MOCs.

Run after audit confirms what is stale:
    python scratch/vault_maintenance.py
"""
from __future__ import annotations

import json
import re
import sqlite3
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

VAULT = Path("vault")
DB = Path("data/pre.db")
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")

FM = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n", re.S)
TICKED = re.compile(r"^\s*-\s*\[x\]", re.M)

# ── paths ────────────────────────────────────────────────────────────
PINS = VAULT / "04 - Campaigns & Products" / "Pins"
JOBS = VAULT / "08 - Live Generation Nodes" / "Jobs"
REFS = VAULT / "03 - Pipeline & Visual DNA" / "References"
PRODUCTS = VAULT / "04 - Campaigns & Products" / "Products"
ARCHIVE = VAULT / "09 - Archive" / f"Stale Sync {TODAY}"
ARCHIVE_PINS = ARCHIVE / "Pins"
ARCHIVE_JOBS = ARCHIVE / "Jobs"
ARCHIVE_REFS = ARCHIVE / "References"
ARCHIVE_PRODUCTS = ARCHIVE / "Products"


def fld(raw: str, key: str) -> str | None:
    m = re.search(rf'^{key}:\s*"?([^"\n]*)"?', raw, re.M)
    return m.group(1).strip() if m else None


def slugify(text: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", text).strip()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ═════════════════════════════════════════════════════════════════════
# 1. ARCHIVE STALE NOTES
# ═════════════════════════════════════════════════════════════════════
def archive_stale() -> dict:
    conn = sqlite3.connect(DB)
    db_pins = {r[0] for r in conn.execute("SELECT id FROM pin_drafts")}
    db_jobs = {r[0] for r in conn.execute("SELECT id FROM jobs")}
    db_refs = {r[0] for r in conn.execute('SELECT id FROM "references"')}
    db_prods = {r[0] for r in conn.execute("SELECT name FROM products")}
    conn.close()

    stats = {"pins": 0, "jobs": 0, "refs": 0, "products": 0, "ticked_preserved": 0}

    for d in [ARCHIVE, ARCHIVE_PINS, ARCHIVE_JOBS, ARCHIVE_REFS, ARCHIVE_PRODUCTS]:
        d.mkdir(parents=True, exist_ok=True)

    # --- pins ---
    for p in PINS.glob("*.md"):
        raw = p.read_text(encoding="utf-8", errors="replace")
        pid = fld(raw, "pin_id")
        if pid not in db_pins:
            has_tick = bool(TICKED.search(raw))
            if has_tick:
                # copy to archive, keep original in Pins
                shutil.copy2(p, ARCHIVE_PINS / p.name)
                stats["ticked_preserved"] += 1
            else:
                shutil.move(str(p), str(ARCHIVE_PINS / p.name))
            stats["pins"] += 1

    # --- jobs ---
    for p in JOBS.glob("*.md"):
        raw = p.read_text(encoding="utf-8", errors="replace")
        jid = fld(raw, "job_id")
        if jid not in db_jobs:
            shutil.move(str(p), str(ARCHIVE_JOBS / p.name))
            stats["jobs"] += 1

    # --- refs ---
    for p in REFS.glob("*.md"):
        raw = p.read_text(encoding="utf-8", errors="replace")
        rid = fld(raw, "reference_id")
        if rid not in db_refs:
            shutil.move(str(p), str(ARCHIVE_REFS / p.name))
            stats["refs"] += 1

    # --- products ---
    for p in PRODUCTS.glob("Product - *.md"):
        name = p.stem[len("Product - "):]
        if name not in db_prods:
            shutil.move(str(p), str(ARCHIVE_PRODUCTS / p.name))
            stats["products"] += 1

    print(f"  Archived: {stats['pins']} pins ({stats['ticked_preserved']} ticked preserved), "
          f"{stats['jobs']} jobs, {stats['refs']} refs, {stats['products']} products")
    return stats


# ═════════════════════════════════════════════════════════════════════
# 2. CREATE MISSING PRODUCT NOTES FROM DB
# ═════════════════════════════════════════════════════════════════════
def create_product_notes() -> int:
    conn = sqlite3.connect(DB)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(products)")]
    rows = [dict(zip(cols, r)) for r in conn.execute("SELECT * FROM products")]
    conn.close()

    created = 0
    for r in rows:
        name = r["name"]
        safe = slugify(name)
        fp = PRODUCTS / f"Product - {safe}.md"
        if fp.exists():
            continue

        truth = json.loads(r["product_truth_json"]) if r.get("product_truth_json") else {}
        must_preserve = truth.get("must_preserve", [])
        must_not_invent = truth.get("must_not_invent", [])
        variations = truth.get("allowed_scene_variations", [])

        preserve_list = "\n".join(f"- [x] {item}" for item in must_preserve) or "*None registered yet.*"
        not_invent_list = "\n".join(f"- 🚫 {item}" for item in must_not_invent) or "*None registered yet.*"
        variations_list = "\n".join(f"- 🎬 {item}" for item in variations) or "*None registered yet.*"

        cat_tag = f"category/{(r['category'] or 'general').lower()}"
        campaign_link = "[[Campaign - Unassigned]]"
        if r.get("campaign_id"):
            c = sqlite3.connect(DB)
            camp = c.execute("SELECT name FROM campaigns WHERE id=?", (r["campaign_id"],)).fetchone()
            c.close()
            if camp:
                campaign_link = f"[[Campaign - {slugify(camp[0])}]]"

        content = f"""---
node_type: product
product_id: "{r['id']}"
name: "{name}"
category: "{r['category'] or 'general'}"
merchant: "{r['merchant'] or 'N/A'}"
price: {r['price'] or 0.00}
affiliate_link: "{r['affiliate_url'] or ''}"
created: "{r['created_at'] or now_iso()}"
tags:
  - product/active
  - {cat_tag}
---

# 🛍️ Product Node: {name}

- **Product ID:** `{r['id']}`
- **Brand / Merchant:** {r['brand'] or 'N/A'} / {r['merchant'] or 'N/A'}
- **Category:** {r['category'] or 'General'}
- **Retail Price:** `${r['price'] or 0.00} USD`
- **Affiliate Destination:** [{r['affiliate_url'] or 'No Link'}]({r['affiliate_url'] or '#'})
- **Campaign Association:** {campaign_link}
- **Last Sync:** `{now_iso()}`

---

## 🛡️ Product Truth Constraints

### 🔒 Must Preserve
{preserve_list}

### 🚫 Must NOT Invent (Anti-Hallucination)
{not_invent_list}

### 🎬 Allowed Scene Variations
{variations_list}

---

## 🔗 Graph Relationships & Backlinks
- [[📐 Product Truth Standards]]
- [[🛍️ Product Catalog & Truth Registry]]
- {campaign_link}
"""
        fp.write_text(content, encoding="utf-8")
        created += 1
        print(f"    ✅ Product: {name}")

    print(f"  Created {created} product notes")
    return created


# ═════════════════════════════════════════════════════════════════════
# 3. REGENERATE MOCS
# ═════════════════════════════════════════════════════════════════════
def db_counts() -> dict:
    out: dict[str, int | dict] = {}
    if not DB.exists():
        return out
    conn = sqlite3.connect(DB)
    for table, label in [
        ("campaigns", "campaigns"),
        ('"references"', "references"),
        ("products", "products"),
        ("jobs", "jobs"),
        ("job_outputs", "outputs"),
        ("pin_drafts", "pins"),
        ("critiques", "critiques"),
    ]:
        try:
            out[label] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.Error:
            out[label] = 0
    for key, sql in [
        ("job_states", "SELECT current_state, COUNT(*) FROM jobs GROUP BY current_state"),
        ("pin_states", "SELECT status, COUNT(*) FROM pin_drafts GROUP BY status"),
    ]:
        try:
            out[key] = dict(conn.execute(sql).fetchall())
        except sqlite3.Error:
            out[key] = {}
    conn.close()
    return out


def vault_counts() -> Counter[str]:
    c: Counter[str] = Counter()
    for p in VAULT.rglob("*.md"):
        if ".obsidian" in p.parts or ".trash" in p.parts:
            continue
        c[p.parent.relative_to(VAULT).as_posix()] += 1
    return c


def write(rel: str, frontmatter: dict[str, object], body: str) -> None:
    p = VAULT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---"]
    for k, v in frontmatter.items():
        if isinstance(v, list):
            lines.append(f"{k}:")
            lines += [f"  - {i}" for i in v]
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    p.write_text("\n".join(lines) + "\n" + body, encoding="utf-8")


def tag_of(path: Path, key: str) -> str:
    m = re.search(rf"^{key}:\s*\"?([^\"\n]*?)\"?\s*$", path.read_text(encoding="utf-8", errors="replace"), re.M)
    return m.group(1).strip() if m else ""


def regenerate_mocs() -> None:
    db = db_counts()
    vc = vault_counts()
    total = sum(vc.values())
    jobs = db.get("job_states", {})
    pins = db.get("pin_states", {})

    def bar(d: dict[str, int]) -> str:
        return " · ".join(f"`{v}` {k.lower()}" for k, v in sorted(d.items(), key=lambda x: -x[1]))

    # ── Main Dashboard ──
    write(
        "00 - Dashboard & MOCs/🏠 Main Dashboard.md",
        {
            "aliases": ["Main Dashboard", "Pinterest Realism Engine Cockpit"],
            "tags": ["dashboard", "moc", "index"],
            "created": "2026-08-20",
            "updated": TODAY,
        },
        f"""# 🚀 Pinterest Realism Engine — Knowledge & Telemetry Vault

Live knowledge graph for the Pinterest Realism Engine (PRE), synced with the
production database, the pipeline state machine, and the Google Flow batch
generator.

---

## 📊 Live system metrics

| Metric | Count | Notes |
|---|---|---|
| Campaigns | `{db.get('campaigns', 0)}` | |
| Products | `{db.get('products', 0)}` | includes Amazon PA-API ingestions |
| References | `{db.get('references', 0)}` | |
| Generation jobs | `{db.get('jobs', 0)}` | {bar(jobs)} |
| Job outputs | `{db.get('outputs', 0)}` | generated variation images |
| Pin drafts | `{db.get('pins', 0)}` | {bar(pins)} |
| Critiques | `{db.get('critiques', 0)}` | quality gate is under-used |
| Vault notes | `{total}` | across {len(vc)} folders |

> Snapshot taken {TODAY}. Re-run `python scripts/vault_regenerate_mocs.py` to refresh.

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
| `00 - Dashboard & MOCs` | {vc.get('00 - Dashboard & MOCs', 0)} — navigation only |
| `01 - Dev Logs & History` | {vc.get('01 - Dev Logs & History', 0)} — dated build history |
| `02 - Bugs & Issues` | {vc.get('02 - Bugs & Issues/Active', 0)} active · {vc.get('02 - Bugs & Issues/_Archive - Auto Bugs', 0)} auto-archived |
| `03 - Pipeline & Visual DNA` | {vc.get('03 - Pipeline & Visual DNA/References', 0)} references · {vc.get('03 - Pipeline & Visual DNA/Knowledge', 0)} knowledge |
| `04 - Campaigns & Products` | {vc.get('04 - Campaigns & Products/Pins', 0)} pins · {vc.get('04 - Campaigns & Products/Products', 0)} products · {vc.get('04 - Campaigns & Products/Campaigns', 0)} campaigns |
| `05 - Architecture & Specs` | {vc.get('05 - Architecture & Specs', 0)} — specs and PRDs |
| `06 - Ideas & Future Backlog` | {vc.get('06 - Ideas & Future Backlog', 0)} |
| `07 - Templates` | {vc.get('07 - Templates', 0)} |
| `08 - Live Generation Nodes` | {vc.get('08 - Live Generation Nodes/Jobs', 0)} jobs · {vc.get('08 - Live Generation Nodes/Critiques', 0)} critiques |
| `09 - Archive` | {vc.get('09 - Archive', 0)} — deprecated and junk |

---

## ⚡ Pipeline at a glance

```
[Reference] ➔ [Visual DNA] ➔ [Commerce DNA] ➔ [13-section prompt]
     ➔ [Google Flow ×4] ➔ [Anti-AI pass] ➔ [Editorial lookbook]
     ➔ [Git + Vercel] ➔ [Pin drafts] ➔ [Pinterest] ➔ [/api/go affiliate link]
```

See [[🗺️ System Map & Architecture MOC]] for the module-level detail.
""",
    )

    # ── Vault Structure ──
    write(
        "00 - Dashboard & MOCs/📚 Vault Structure & Navigation.md",
        {
            "aliases": ["Vault Structure", "Folder Map"],
            "tags": ["moc", "index", "navigation"],
            "created": TODAY,
            "updated": TODAY,
        },
        f"""# 📚 Vault Structure & Navigation

How this vault is organised, and what the sync service writes where.

---

## The rule

**Hand-written notes and machine-generated notes live in different folders.**

`app/services/vault_sync.py` writes one note per database row on every sync.
Left in the same folder as the notes you navigate by, that floods the folder —
115 pin drafts buried 5 product notes. So every auto-generated type gets its
own sub-folder, and the top level of each numbered folder stays readable.

## Layout

| Folder | Contents | Written by |
|---|---|---|
| `00 - Dashboard & MOCs` | Navigation notes | Hand |
| `01 - Dev Logs & History` | Dated build history, changelog | Hand |
| `02 - Bugs & Issues/Active` | Real `BUG-00x` issues | Hand |
| `02 - Bugs & Issues/_Archive - Auto Bugs` | Auto-captured exceptions | `log_runtime_bug` |
| `03 - Pipeline & Visual DNA/Knowledge` | Playbooks and taxonomies | Hand |
| `03 - Pipeline & Visual DNA/References` | One note per reference image | `sync_reference_node` |
| `04 - Campaigns & Products/Campaigns` | Campaign notes | Hand |
| `04 - Campaigns & Products/Products` | Product truth sheets | `sync_product_node` |
| `04 - Campaigns & Products/Pins` | One note per pin draft | `sync_pin_node` |
| `05 - Architecture & Specs` | Specs, PRDs, Commerce DNA | Hand + `sync_commerce_node` |
| `06 - Ideas & Future Backlog` | Backlog | Hand |
| `07 - Templates` | Note templates | Hand |
| `08 - Live Generation Nodes/Jobs` | One note per generation job | `sync_job_node` |
| `08 - Live Generation Nodes/Critiques` | Critique records | `sync_critique_node` |
| `09 - Archive` | Deprecated specs, junk test rows | Hand |

## Conventions

- **Wikilinks resolve by note name, not path.** Moving a note between folders
  never breaks a link, which is what made this reorganisation safe.
- **Frontmatter tags carry no `#`.** A tag written as `- #state/pass` becomes a
  tag literally named `#state/pass` in the tag pane. The `#` belongs to inline
  body tags only. Fixed at source in `vault_sync.py` and across all notes.
- **`Campaign - Unassigned` is a system bucket**, not a campaign. The sync
  service links rows with no campaign here so the link resolves.
- Archived folders are prefixed `_` so they sort to the bottom.

## Maintenance

| Task | Command |
|---|---|
| Refresh dashboard metrics | `python scripts/vault_regenerate_mocs.py` |
| File notes into folders | `python scripts/reorganize_vault.py` |
| Repair broken links | `python scripts/vault_fix_links.py` |
| Full resync from database | `python -m scripts.sync_all_to_vault` |

---

## Related

- [[🏠 Main Dashboard]]
- [[🗺️ System Map & Architecture MOC]]
""",
    )

    # ── Issues Tracker Index ──
    active_dir = VAULT / "02 - Bugs & Issues" / "Active"
    rows = []
    if active_dir.exists():
        for p in sorted(active_dir.glob("BUG-*.md")):
            text = p.read_text(encoding="utf-8", errors="replace")
            rows.append(
                (
                    tag_of(p, "id") or p.stem.split(" - ")[0],
                    p.stem.split(" - ", 1)[-1],
                    tag_of(p, "severity") or "—",
                    tag_of(p, "status") or "—",
                    tag_of(p, "subsystem") or "—",
                    p.stem,
                )
            )

    table = "\n".join(
        f"| [[{r[5]}\\|{r[0]}]] | {r[1]} | {r[2]} | {r[3]} | {r[4]} |" for r in rows
    ) or "| _none_ | | | | |"

    write(
        "02 - Bugs & Issues/Issues Tracker Index.md",
        {
            "aliases": ["Bug Index", "Issue Index"],
            "tags": ["moc", "bugs", "index"],
            "created": "2026-08-20",
            "updated": TODAY,
        },
        f"""# 🐛 Issues Tracker Index

**Hand-tracked bugs only.** Auto-captured exceptions are archived in
[[_Archive - Auto Bugs]] — {vc.get('02 - Bugs & Issues/_Archive - Auto Bugs', 0)} notes
that would otherwise bury the {len(rows)} real ones.

---

## Active issues

| ID | Title | Severity | Status | Subsystem |
|---|---|---|---|---|
{table}

---

## Auto-captured exceptions

Written by `log_runtime_bug` whenever an unhandled exception escapes the API.
They land in `_Archive - Auto Bugs/` and are grouped by endpoint.

| Endpoint | Notes |
|---|---|
| `POST /api/jobs/*` | {sum(1 for p in (VAULT / '02 - Bugs & Issues/_Archive - Auto Bugs').glob('*apijobs*.md')) if (VAULT / '02 - Bugs & Issues/_Archive - Auto Bugs').exists() else 0} |
| `POST /api/references/*` | {sum(1 for p in (VAULT / '02 - Bugs & Issues/_Archive - Auto Bugs').glob('*apireferences*.md')) if (VAULT / '02 - Bugs & Issues/_Archive - Auto Bugs').exists() else 0} |

---

## Related

- [[🐛 Bug Tracker MOC]]
- [[🏠 Main Dashboard]]
""",
    )

    print(f"  Regenerated 3 MOCs (vault now {total} notes)")


# ═════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════
def main() -> None:
    print("=" * 70)
    print("VAULT MAINTENANCE")
    print("=" * 70)

    print("\n[1] Archiving stale notes...")
    stats = archive_stale()

    print("\n[2] Creating missing product notes...")
    n_prods = create_product_notes()

    print("\n[3] Regenerating MOCs...")
    regenerate_mocs()

    print("\n" + "=" * 70)
    print("DONE")
    print(f"  Archived: {stats['pins']} pins, {stats['jobs']} jobs, {stats['refs']} refs, {stats['products']} products")
    print(f"  Preserved ticked pins: {stats['ticked_preserved']}")
    print(f"  Created product notes: {n_prods}")
    print(f"  Regenerated 3 MOCs")
    print("=" * 70)


if __name__ == "__main__":
    main()
