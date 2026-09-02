"""
Final link cleanup — the cases a generic pass cannot decide.

  * Conceptual pipeline stages written as wikilinks in the architecture MOC.
    They name *code modules*, not vault notes, so they become inline code.
  * Two links missing an emoji prefix / with a stale one.
  * A dev-log table row where a `[[...]]` link was truncated mid-token.
  * Links to nodes that were deleted from the database; de-linked to plain
    text so the graph stops advertising notes that do not exist.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

VAULT = Path("vault")

# Pipeline stages are modules under app/pipeline/, not vault notes.
CONCEPTUAL = {
    "Reference Analyst": "app/pipeline/reference_analyst.py",
    "Visual DNA Extractor": "app/pipeline/visual_dna.py",
    "Scene Director": "app/pipeline/scene_director.py",
    "Prompt Compiler": "app/pipeline/prompt_compiler.py",
    "Realism Critic": "app/pipeline/realism_critic.py",
    "Rework Engine": "app/pipeline/rework_engine.py",
    "Pin Composer & SEO": "app/pipeline/pinterest_seo.py",
}

RENAMES = {
    "System Map & Architecture MOC": "🗺️ System Map & Architecture MOC",
    "📜 Changelog": "Changelog",
    "Visual DNA Knowledge Base": "🧬 Visual DNA Knowledge Base",
    "Prompt Engineering Playbook": "🎨 Prompt Engineering Playbook",
    "Product Truth Standards": "📐 Product Truth Standards",
    "Realism Critic Defect Taxonomy": "🔍 Realism Critic Defect Taxonomy",
}

#: Full-UUID reference notes that were purged from the database.
UUID_REF = re.compile(r"Ref - [0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

# Links to nodes deleted from the database — keep the text, drop the link.
DEAD = {"Job - test"}

stats: Counter[str] = Counter()


def fix(text: str, index: set[str]) -> str:
    def sub(m: re.Match[str]) -> str:
        inner = m.group(1)
        target = inner.split("|")[0].strip()

        # Never rewrite a link that already resolves. De-linking on the shape
        # of the target alone struck through 100 valid reference links.
        if target.lower() in index:
            return m.group(0)

        if target in CONCEPTUAL:
            stats["conceptual"] += 1
            label = inner.split("|")[-1] if "|" in inner else target
            return f"`{label}`"
        if target in RENAMES:
            stats["renamed"] += 1
            return f"[[{RENAMES[target]}]]"
        if target in DEAD:
            stats["dead"] += 1
            return f"~~{target}~~"
        if UUID_REF.fullmatch(target):
            stats["dead"] += 1
            return f"~~{target}~~"
        return m.group(0)

    return re.sub(r"\[\[([^\]]+)\]\]", sub, text)


def main() -> None:
    index = {p.stem.lower() for p in VAULT.rglob("*.md") if ".obsidian" not in p.parts}

    for p in VAULT.rglob("*.md"):
        if ".obsidian" in p.parts:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        new = fix(text, index)
        # Repair the truncated link left inside a dev-log table row.
        if "[[\U0001f383 Campaign" in new:
            new = re.sub(
                r"\[\[\U0001f383 Campaign[^\]]*?\|[^\]]*\]\]",
                "[[Campaign - Fall Halloween 2026]]",
                new,
            )
            stats["truncated"] += 1
        if new != text:
            p.write_text(new, encoding="utf-8")
            stats["notes_edited"] += 1

    print("Final link cleanup:")
    for k, v in sorted(stats.items()):
        print(f"  {k:18s} {v}")


if __name__ == "__main__":
    main()
