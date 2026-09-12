"""
Comprehensive Obsidian vault audit for the Pinterest Realism Engine vault.

Read-only. Produces a report of structural problems:
  - broken wikilinks
  - orphan notes (no inbound links)
  - duplicate / near-duplicate titles
  - frontmatter problems (missing keys per node_type, bad YAML)
  - stub / empty notes
  - naming convention drift
  - test / junk data pollution
  - stale MOC metrics vs live DB
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

VAULT = Path("vault")
DB = Path("data/pre.db")

WIKILINK = re.compile(r"\[\[([^\]\|#]+)(?:#[^\]\|]*)?(?:\|[^\]]*)?\]\]")
MDLINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+\.md)\)")
FM = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n", re.S)

# expected frontmatter keys per node_type
REQUIRED = {
    "campaign": ["node_type", "campaign_id", "name", "status"],
    "product": ["node_type", "product_id", "name"],
    "reference": ["node_type", "reference_id"],
    "job": ["node_type", "job_id", "current_state"],
    "pin": ["node_type", "pin_id", "title"],
    "critique": ["node_type", "output_id"],
}
JUNK_PAT = re.compile(r"\btest\b|dummy|sample|placeholder|copy of|untitled|todo|asdf|foo\b|bar\b|temp\b|_test|test_", re.I)


def parse_frontmatter(text: str) -> dict:
    """Minimal YAML frontmatter parser (flat keys + simple nested)."""
    m = FM.match(text)
    if not m:
        return {}
    out: dict = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        if line.startswith((" ", "\t", "-")):
            continue
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def main() -> None:
    notes: dict[str, Path] = {}          # stem -> path
    dupes: dict[str, list[Path]] = defaultdict(list)
    fm_map: dict[Path, dict] = {}
    body_map: dict[Path, str] = {}
    raw_map: dict[Path, str] = {}

    for p in VAULT.rglob("*.md"):
        if ".obsidian" in p.parts:
            continue
        raw = p.read_text(encoding="utf-8", errors="replace")
        raw_map[p] = raw
        body_map[p] = FM.sub("", raw)
        fm_map[p] = parse_frontmatter(raw)
        stem = p.stem
        dupes[stem].append(p)
        notes.setdefault(stem, p)

    total = len(raw_map)
    print(f"{'='*70}\nVAULT AUDIT — {total} notes\n{'='*70}")

    # ---------- 1. broken links ----------
    inbound: Counter[str] = Counter()
    broken: list[tuple[Path, str]] = []
    total_links = 0
    for p, body in body_map.items():
        for target in WIKILINK.findall(body):
            t = target.strip()
            total_links += 1
            if t in notes:
                inbound[t] += 1
            else:
                # try path-qualified resolution
                cand = [n for n in notes if n.endswith("/" + t) or n == Path(t).stem]
                if cand:
                    inbound[Path(cand[0]).stem] += 1
                else:
                    broken.append((p, t))
        for t in MDLINK.findall(body):
            tgt = t.strip()
            if tgt.startswith(("http://", "https://", "mailto:")):
                continue
            total_links += 1
            if not (p.parent / tgt).exists() and not (VAULT / tgt).exists():
                broken.append((p, tgt))

    print(f"\n[1] LINKS  total={total_links}  broken={len(broken)}")
    bc = Counter(t for _, t in broken)
    for t, c in bc.most_common(15):
        print(f"      BROKEN x{c:<3} -> [[{t}]]")

    # ---------- 2. orphans ----------
    orphans = [p for p in raw_map if p.stem not in inbound]
    print(f"\n[2] ORPHANS (no inbound links): {len(orphans)}")
    oc = Counter(p.parent.name for p in orphans)
    for d, c in oc.most_common(12):
        print(f"      {c:<5} in {d}")

    # ---------- 3. duplicates ----------
    real_dupes = {k: v for k, v in dupes.items() if len(v) > 1}
    print(f"\n[3] DUPLICATE STEMS: {len(real_dupes)}")
    for k, v in list(real_dupes.items())[:12]:
        print(f"      '{k}' x{len(v)}")
        for pp in v:
            print(f"          {pp.relative_to(VAULT)}")

    # ---------- 4. frontmatter ----------
    no_fm = [p for p in raw_map if not fm_map[p]]
    bad = defaultdict(list)
    for p, fm in fm_map.items():
        nt = fm.get("node_type")
        if nt in REQUIRED:
            for key in REQUIRED[nt]:
                if key not in fm or fm.get(key) in ("", "None", "null"):
                    bad[f"{nt}: missing '{key}'"].append(p)
    print(f"\n[4] FRONTMATTER: {len(no_fm)} notes with NO frontmatter, {len(bad)} field problems")
    for issue, ps in sorted(bad.items(), key=lambda x: -len(x[1]))[:12]:
        print(f"      {len(ps):<5} {issue}")
    if no_fm:
        nc = Counter(p.parent.name for p in no_fm)
        for d, c in nc.most_common(8):
            print(f"      no-fm {c:<5} in {d}")

    # node_type distribution
    ntc = Counter(fm.get("node_type", "(none)") for fm in fm_map.values())
    print(f"      node_types: {dict(ntc.most_common(12))}")

    # ---------- 5. stubs ----------
    stubs = [p for p, b in body_map.items() if len(b.strip()) < 120]
    print(f"\n[5] STUBS (<120 chars body): {len(stubs)}")
    sc = Counter(p.parent.name for p in stubs)
    for d, c in sc.most_common(8):
        print(f"      {c:<5} in {d}")

    # ---------- 6. junk / test data ----------
    junk = [p for p in raw_map if JUNK_PAT.search(p.stem)]
    print(f"\n[6] JUNK / TEST-LOOKING FILENAMES: {len(junk)}")
    for p in junk[:25]:
        print(f"      {p.relative_to(VAULT)}")
    if len(junk) > 25:
        print(f"      ... +{len(junk)-25} more")

    # ---------- 7. naming drift ----------
    prefixes = Counter()
    for p in raw_map:
        m = re.match(r"^([A-Z][A-Za-z ]{1,20}?) - ", p.stem)
        if m:
            prefixes[m.group(1)] += 1
    print(f"\n[7] FILENAME PREFIX CONVENTIONS: {dict(prefixes.most_common(15))}")
    spaced = [p for p in raw_map if "  " in p.stem or p.stem != p.stem.strip()]
    print(f"      notes with double/edge spaces in name: {len(spaced)}")
    for p in spaced[:10]:
        print(f"      '{p.stem}'")

    # ---------- 8. stale MOC metrics ----------
    print(f"\n[8] STALE METRIC CHECK (live DB vs dashboard claims)")
    if DB.exists():
        conn = sqlite3.connect(DB)
        for table, label in [("campaigns", "campaigns"), ('"references"', "references"),
                             ("products", "products"), ("jobs", "jobs"),
                             ("job_outputs", "outputs"), ("pin_drafts", "pins"),
                             ("critiques", "critiques")]:
            try:
                live = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.Error:
                live = "ERR"
            print(f"      DB {label:<12} = {live}")
        conn.close()
    dash = VAULT / "00 - Dashboard & MOCs" / "🏠 Main Dashboard.md"
    if dash.exists():
        dtxt = dash.read_text(encoding="utf-8", errors="replace")
        for line in dtxt.splitlines():
            if re.search(r"Vault notes|Snapshot taken", line):
                print(f"      DASHBOARD SAYS: {line.strip()}")

    # ---------- 9. folder distribution ----------
    print(f"\n[9] FOLDER DISTRIBUTION")
    fc = Counter(str(p.parent.relative_to(VAULT)) for p in raw_map)
    for d, c in sorted(fc.items()):
        print(f"      {c:<6} {d}")

    # ---------- 10. tag inventory ----------
    tags: Counter[str] = Counter()
    for p, raw in raw_map.items():
        m = FM.match(raw)
        if not m:
            continue
        in_tags = False
        for line in m.group(1).splitlines():
            if re.match(r"^tags:", line):
                in_tags = True
                continue
            if in_tags:
                if re.match(r"^\s+-\s+", line):
                    tags[line.strip().lstrip("- ").strip()] += 1
                elif line.strip():
                    in_tags = False
    print(f"\n[10] TAGS: {len(tags)} distinct")
    for t, c in tags.most_common(20):
        print(f"      {c:<6} #{t}")

    print(f"\n{'='*70}\nSUMMARY")
    print(f"  notes                : {total}")
    print(f"  broken links         : {len(broken)}")
    print(f"  orphan notes         : {len(orphans)}")
    print(f"  duplicate stems      : {len(real_dupes)}")
    print(f"  no frontmatter       : {len(no_fm)}")
    print(f"  stub notes           : {len(stubs)}")
    print(f"  junk-looking names   : {len(junk)}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
