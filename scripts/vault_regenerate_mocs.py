"""
Regenerate the vault's navigation notes from the live database and vault.

Run after a reorganisation or whenever the dashboard metrics have drifted:
    python scripts/vault_regenerate_mocs.py

Rewrites:
  * 00 - Dashboard & MOCs/🏠 Main Dashboard.md
  * 00 - Dashboard & MOCs/📚 Vault Structure & Navigation.md
  * 02 - Bugs & Issues/Issues Tracker Index.md
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path("vault")
DB = Path("data/pre.db")

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")


def db_counts() -> dict[str, int]:
    out: dict[str, int] = {}
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
        if ".obsidian" in p.parts:
            continue
        c[p.parent.relative_to(VAULT).as_posix()] += 1
    return c


def tag_of(path: Path, key: str) -> str:
    m = re.search(rf"^{key}:\s*\"?([^\"\n]*?)\"?\s*$", path.read_text(encoding="utf-8", errors="replace"), re.M)
    return m.group(1).strip() if m else ""


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


def main() -> None:
    db = db_counts()
    vc = vault_counts()
    total = sum(vc.values())

    jobs = db.get("job_states", {})
    pins = db.get("pin_states", {})

    # ── Main Dashboard ────────────────────────────────────────────────────
    def bar(d: dict[str, int]) -> str:
        return " · ".join(f"`{v}` {k.lower()}" for k, v in sorted(d.items(), key=lambda x: -x[1]))

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

    # ── Vault structure note ──────────────────────────────────────────────
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

    # ── Issues tracker index ──────────────────────────────────────────────
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

    print(f"Regenerated 3 navigation notes (vault total {total} notes).")


if __name__ == "__main__":
    main()
