"""
One-off Obsidian vault reorganisation.

Creates the sub-folder taxonomy, files every note into it, repairs the
malformed frontmatter tags the sync service has been writing, and quarantines
junk test artefacts. Re-runnable: every step is idempotent.

Wikilinks are resolved by Obsidian on note *name*, not path, and the vault has
zero duplicate note names, so moving files cannot break a link.
"""

from __future__ import annotations

import os
import re
import shutil
from collections import Counter
from pathlib import Path

VAULT = Path("vault")

# ── Target taxonomy ────────────────────────────────────────────────────────
NEW_FOLDERS = [
    "00 - Dashboard & MOCs",
    "01 - Dev Logs & History",
    "02 - Bugs & Issues/Active",
    "02 - Bugs & Issues/_Archive - Auto Bugs",
    "02 - Bugs & Issues/_Archive - Retry Duplicates",
    "03 - Pipeline & Visual DNA/Knowledge",
    "03 - Pipeline & Visual DNA/References",
    "03 - Pipeline & Visual DNA/_Archive - Junk",
    "04 - Campaigns & Products/Campaigns",
    "04 - Campaigns & Products/Products",
    "04 - Campaigns & Products/Pins",
    "04 - Campaigns & Products/_Archive",
    "05 - Architecture & Specs",
    "06 - Ideas & Future Backlog",
    "07 - Templates",
    "08 - Live Generation Nodes/Jobs",
    "08 - Live Generation Nodes/Critiques",
    "09 - Archive",
]

# Reference notes whose trend/category is keyboard-mash test input. Matched
# against the trend/category *values* only — scanning the whole note body
# matched ordinary Markdown ("---", "|||") and misfiled every reference.
MASH = re.compile(r"(.)\1{2,}", re.IGNORECASE)


def _field(text: str, key: str) -> str:
    m = re.search(rf'^{key}:\s*"?([^"\n]*?)"?\s*$', text, re.M)
    return m.group(1).strip() if m else ""


def is_junk_reference(text: str) -> bool:
    for value in (_field(text, "trend"), _field(text, "category")):
        if not value:
            continue
        if MASH.search(value):
            return True
        if len(value) > 2 and not re.search(r"[aeiou]", value, re.I):
            return True
    return False

stats = Counter()


def read_notes() -> dict[str, str]:
    """Key each note by its vault-relative POSIX path."""
    notes = {}
    for p in VAULT.rglob("*.md"):
        if ".obsidian" in p.parts:
            continue
        rel = p.relative_to(VAULT).as_posix()
        notes[rel] = p.read_text(encoding="utf-8", errors="replace")
    return notes


# ── Step 1: repair frontmatter tags ───────────────────────────────────────
def fix_tags(text: str) -> tuple[str, int]:
    """Strip the stray '#' the sync service wrote into frontmatter tag lists."""
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    if not m:
        return text, 0
    fm = m.group(1)
    new_fm, n = re.subn(r"^(\s*-\s*)#(\S+)\s*$", r"\1\2", fm, flags=re.M)
    if n:
        return text[: m.start(1)] + new_fm + text[m.end(1) :], n
    return text, 0


# ── Step 2: decide each note's destination ────────────────────────────────
def destination(rel: str, body: str) -> str:
    name = os.path.basename(rel)
    top = rel.split("/")[0]

    if top == "02 - Bugs & Issues":
        if name.startswith("AUTO-BUG"):
            return "02 - Bugs & Issues/_Archive - Auto Bugs/" + name
        if name.startswith("BUG-"):
            return "02 - Bugs & Issues/Active/" + name
        if "_Archive - Retry Duplicates" in rel:
            return rel  # already filed
        return rel  # Issues Tracker Index etc. stay at top level

    if top == "03 - Pipeline & Visual DNA":
        if name.startswith("Ref -"):
            if is_junk_reference(body):
                return "03 - Pipeline & Visual DNA/_Archive - Junk/" + name
            return "03 - Pipeline & Visual DNA/References/" + name
        return "03 - Pipeline & Visual DNA/Knowledge/" + name

    if top == "04 - Campaigns & Products":
        if name.startswith("Pin -"):
            return "04 - Campaigns & Products/Pins/" + name
        if name.startswith("Product -") or name.startswith("\U0001f6cd"):
            return "04 - Campaigns & Products/Products/" + name
        if name.startswith("Campaign -"):
            return "04 - Campaigns & Products/Campaigns/" + name
        if "_Archive" in rel:
            return "04 - Campaigns & Products/_Archive/" + name
        return "04 - Campaigns & Products/Products/" + name

    if top == "08 - Live Generation Nodes":
        if name.startswith("Critique -"):
            return "08 - Live Generation Nodes/Critiques/" + name
        return "08 - Live Generation Nodes/Jobs/" + name

    if top == "05 - Architecture & Specs":
        # n8n was removed from the codebase; the note is a doc of record only.
        if "n8n" in name or name == "Commerce DNA - test.md":
            return "09 - Archive/" + name
        return rel

    return rel


def main() -> None:
    for f in NEW_FOLDERS:
        (VAULT / f).mkdir(parents=True, exist_ok=True)
        stats["folders_created"] += 1

    notes = read_notes()

    # ── Repair tags ───────────────────────────────────────────────────────
    for rel, text in notes.items():
        fixed, n = fix_tags(text)
        if n:
            Path(rel).write_text(fixed, encoding="utf-8")
            stats["tags_fixed"] += n
            stats["notes_tag_fixed"] += 1

    # ── Move files ────────────────────────────────────────────────────────
    for rel, text in notes.items():
        dest_rel = destination(rel, text)
        if dest_rel == rel:
            continue
        src = VAULT / rel
        dst = VAULT / dest_rel
        if dst.exists():
            stats["move_skipped_exists"] += 1
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        stats["moved"] += 1

    # ── Remove emptied directories ────────────────────────────────────────
    for p in sorted(VAULT.rglob("*"), key=lambda x: -len(x.parts)):
        if p.is_dir() and ".obsidian" not in p.parts and not any(p.iterdir()):
            p.rmdir()
            stats["empty_dirs_removed"] += 1

    print("Reorganisation complete:")
    for k, v in sorted(stats.items()):
        print(f"  {k:24s} {v}")


if __name__ == "__main__":
    main()
