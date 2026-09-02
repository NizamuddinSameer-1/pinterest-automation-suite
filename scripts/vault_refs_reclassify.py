"""
Reclassify the reference notes misfiled by the first reorg pass.

The first pass looked for keyboard-mash anywhere in the note body, which
matched ordinary Markdown ("---", "|||") and swept every reference into the
junk folder. Junk is a property of the trend/category *values* only.
"""

from __future__ import annotations

import re
import shutil
from collections import Counter
from pathlib import Path

JUNK_DIR = Path("vault/03 - Pipeline & Visual DNA/_Archive - Junk")
REF_DIR = Path("vault/03 - Pipeline & Visual DNA/References")
REF_DIR.mkdir(parents=True, exist_ok=True)

# Keyboard mash: a run of 3+ identical characters, or a value that is pure
# noise (no vowel, absurdly long single token).
MASH = re.compile(r"(.)\1{2,}", re.IGNORECASE)


def field(text: str, key: str) -> str:
    m = re.search(rf'^{key}:\s*"?([^"\n]*?)"?\s*$', text, re.M)
    return m.group(1).strip() if m else ""


def is_junk(trend: str, category: str) -> bool:
    for v in (trend, category):
        if not v:
            continue
        if MASH.search(v):
            return True
        # "wwwwwwwwwenn", "eeeee", "zzzqqq" — no vowels or absurd repeats
        if len(v) > 2 and not re.search(r"[aeiou]", v, re.I):
            return True
    return False


stats: Counter[str] = Counter()
samples: list[tuple[str, str, str]] = []

for p in sorted(JUNK_DIR.glob("*.md")):
    text = p.read_text(encoding="utf-8", errors="replace")
    trend = field(text, "trend")
    category = field(text, "category")
    if is_junk(trend, category):
        stats["junk"] += 1
        samples.append((p.name, trend, category))
    else:
        shutil.move(str(p), str(REF_DIR / p.name))
        stats["restored"] += 1

print(f"restored to References: {stats['restored']}")
print(f"kept as junk:           {stats['junk']}")
print()
if samples:
    print("junk samples:")
    for name, t, c in samples[:20]:
        print(f"  {name[:46]:48s} trend={t!r} category={c!r}")
