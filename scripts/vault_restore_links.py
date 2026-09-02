"""
Undo the over-eager de-linking from the previous pass.

That pass matched every `Ref - <uuid>` link against the UUID pattern without
first checking whether the note existed, so 100 *valid* links were struck
through. Restore any struck link whose target note is present; leave the rest
struck, since those really are gone.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

VAULT = Path("vault")
STRUCK = re.compile(r"~~(Ref - [0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})~~")
STRIKE_ANY = re.compile(r"~~([^~\n]+)~~")

stats: Counter[str] = Counter()


def main() -> None:
    index = {p.stem.lower() for p in VAULT.rglob("*.md") if ".obsidian" not in p.parts}

    for p in VAULT.rglob("*.md"):
        if ".obsidian" in p.parts:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")

        def sub(m: re.Match[str]) -> str:
            target = m.group(1)
            if target.lower() in index:
                stats["restored"] += 1
                return f"[[{target}]]"
            stats["left_struck"] += 1
            return m.group(0)

        new = STRIKE_ANY.sub(sub, text)
        if new != text:
            p.write_text(new, encoding="utf-8")
            stats["notes_edited"] += 1

    print("Link restoration:")
    for k, v in sorted(stats.items()):
        print(f"  {k:16s} {v}")


if __name__ == "__main__":
    main()
