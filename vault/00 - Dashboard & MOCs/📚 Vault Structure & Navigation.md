---
aliases:
  - Vault Structure
  - Folder Map
tags:
  - moc
  - index
  - navigation
created: 2026-08-29
updated: 2026-08-29
---
# 📚 Vault Structure & Navigation

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
