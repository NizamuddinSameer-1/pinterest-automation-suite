"""
Repair broken wikilinks in the vault.

Two causes:
  1. `[[Campaign - Unassigned]]` — the sync service emits this for every
     reference that has no campaign, but no such note was ever created.
  2. Typo / keyboard-mash campaign and product names written during testing.

Broken campaign links are folded onto the real campaign where the intent is
obvious, and onto a single `Campaign - Unassigned` stub otherwise, so the graph
has one honest bucket instead of 38 dangling targets.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

VAULT = Path("vault")

# Typo / mash variants that clearly mean the real Halloween campaign.
HALLOWEEN_VARIANTS = {
    "campaign - halloween",
    "campaign - halloooo",
    "campaign - haloowen",
    "campaign - haloweeen",
    "campaign - hallow",
    "campaign - hallo",
}
CAMPAIGN_FALLBACK = "Campaign - Unassigned"
PRODUCT_FALLBACK = "🛍️ Product Catalog & Truth Registry"

stats: Counter[str] = Counter()


def build_index() -> set[str]:
    return {
        p.stem.lower() for p in VAULT.rglob("*.md") if ".obsidian" not in p.parts
    }


def resolve(target: str, index: set[str]) -> str | None:
    """Return the link text to use, or None if it is already valid."""
    key = target.split("|")[0].split("#")[0].strip()
    if not key or key.lower() in index:
        return None
    low = key.lower()
    if low.startswith("campaign - "):
        if low in HALLOWEEN_VARIANTS:
            return "Campaign - Fall Halloween 2026"
        return CAMPAIGN_FALLBACK
    if low.startswith("product - "):
        return PRODUCT_FALLBACK
    return None


def main() -> None:
    index = build_index()

    # 1. Create the honest default bucket note if it is referenced.
    stub = VAULT / "04 - Campaigns & Products" / "Campaigns" / f"{CAMPAIGN_FALLBACK}.md"
    if not stub.exists():
        stub.parent.mkdir(parents=True, exist_ok=True)
        stub.write_text(
            "---\n"
            "node_type: campaign\n"
            "campaign_id: unassigned\n"
            "name: Unassigned\n"
            "status: system\n"
            "tags:\n"
            "  - campaign/system\n"
            "  - campaign/unassigned\n"
            "---\n\n"
            "# Campaign Node: Unassigned\n\n"
            "System bucket. The sync service links a reference or product here "
            "when no campaign was chosen, so this note exists to keep those "
            "links resolvable instead of dangling.\n\n"
            "Notes here are **not** a campaign — they are uncategorised input. "
            "File them under a real campaign when you pick one.\n\n"
            "## Related\n"
            "- [[🛍️ Product Catalog & Truth Registry]]\n"
            "- [[Campaign - Fall Halloween 2026]]\n",
            encoding="utf-8",
        )
        stats["stub_created"] += 1
        index.add(CAMPAIGN_FALLBACK.lower())

    # 2. Rewrite broken links.
    for p in VAULT.rglob("*.md"):
        if ".obsidian" in p.parts:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        m = re.match(r"^(---\n.*?\n---\n?)", text, re.S)
        head = m.group(1) if m else ""
        body = text[len(head) :]

        def sub(match: re.Match[str]) -> str:
            replacement = resolve(match.group(1), index)
            if replacement is None:
                return match.group(0)
            stats["links_fixed"] += 1
            alias = match.group(1).split("|")[-1] if "|" in match.group(1) else None
            return f"[[{replacement}|{alias}]]" if alias else f"[[{replacement}]]"

        new_body = re.sub(r"\[\[([^\]]+)\]\]", sub, body)
        if new_body != body:
            p.write_text(head + new_body, encoding="utf-8")
            stats["notes_edited"] += 1

    print("Link repair:")
    for k, v in sorted(stats.items()):
        print(f"  {k:20s} {v}")


if __name__ == "__main__":
    main()
