"""Classify stale vault notes and check overlap with manual user work."""
from __future__ import annotations
import re, sqlite3, sys
from collections import Counter
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

VAULT = Path("vault")
PINS = VAULT / "04 - Campaigns & Products" / "Pins"
JOBS = VAULT / "08 - Live Generation Nodes" / "Jobs"
REFS = VAULT / "03 - Pipeline & Visual DNA" / "References"

conn = sqlite3.connect("data/pre.db")
db_pins = {r[0] for r in conn.execute("SELECT id FROM pin_drafts")}
db_jobs = {r[0] for r in conn.execute("SELECT id FROM jobs")}
db_refs = {r[0] for r in conn.execute('SELECT id FROM "references"')}
conn.close()

def fm_field(raw, key):
    m = re.search(rf'^{key}:\s*"?([^"\n]*)"?', raw, re.M)
    return m.group(1).strip() if m else None

TICKED = re.compile(r'^\s*-\s*\[x\]', re.M)
TESTREF = re.compile(r'test|sample|dummy|placeholder|seed', re.I)

# ---------- PINS ----------
stale_pins, live_pins = [], []
ticked_stale, ticked_live = [], []
for p in PINS.glob("*.md"):
    raw = p.read_text(encoding="utf-8", errors="replace")
    pid = fm_field(raw, "pin_id")
    jid = fm_field(raw, "job_id") or ""
    dest = fm_field(raw, "live_url") or ""
    is_stale = pid not in db_pins
    has_tick = bool(TICKED.search(raw))
    looks_test = bool(TESTREF.search(jid)) or "test-affiliate" in raw
    rec = (p, jid, looks_test, has_tick)
    (stale_pins if is_stale else live_pins).append(rec)
    if has_tick:
        (ticked_stale if is_stale else ticked_live).append(rec)

print("=" * 72)
print("PIN NOTES")
print("=" * 72)
print(f"  live  (has DB row) : {len(live_pins)}")
print(f"  STALE (no DB row)  : {len(stale_pins)}")
print(f"    of stale, look like test/seed : {sum(1 for r in stale_pins if r[2])}")
print(f"    of stale, NOT obviously test  : {sum(1 for r in stale_pins if not r[2])}")
print()
print(f"  notes with MANUAL TICKS total : {len(ticked_stale) + len(ticked_live)}")
print(f"     -> in STALE set : {len(ticked_stale)}   <-- USER WORK AT RISK")
print(f"     -> in live set  : {len(ticked_live)}")
if ticked_stale:
    print("  STALE notes containing manual ticks:")
    for p, jid, _, _ in ticked_stale[:15]:
        print(f"      {p.name}")
    if len(ticked_stale) > 15:
        print(f"      ... +{len(ticked_stale)-15} more")

# ---------- JOBS ----------
stale_jobs = []
for p in JOBS.glob("*.md"):
    raw = p.read_text(encoding="utf-8", errors="replace")
    jid = fm_field(raw, "job_id")
    if jid not in db_jobs:
        stale_jobs.append((p, jid, bool(TESTREF.search(jid or ""))))
print()
print("=" * 72)
print("JOB NOTES")
print("=" * 72)
print(f"  STALE: {len(stale_jobs)}")
print(f"    look like test/seed: {sum(1 for r in stale_jobs if r[2])}")
for p, jid, t in stale_jobs[:10]:
    print(f"      {'[test] ' if t else '       '}{p.name}")

# ---------- REFS ----------
stale_refs = []
for p in REFS.glob("*.md"):
    raw = p.read_text(encoding="utf-8", errors="replace")
    rid = fm_field(raw, "reference_id")
    if rid not in db_refs:
        stale_refs.append((p, rid, bool(TESTREF.search(rid or ""))))
print()
print("=" * 72)
print("REFERENCE NOTES")
print("=" * 72)
print(f"  STALE: {len(stale_refs)}")
print(f"    look like test/seed: {sum(1 for r in stale_refs if r[2])}")
for p, rid, t in stale_refs[:10]:
    print(f"      {'[test] ' if t else '       '}{p.name}")

# ---------- summary ----------
tot_stale = len(stale_pins) + len(stale_jobs) + len(stale_refs)
print()
print("=" * 72)
print(f"TOTAL STALE NOTES: {tot_stale}")
print(f"  pins {len(stale_pins)} + jobs {len(stale_jobs)} + refs {len(stale_refs)}")
print(f"  STALE NOTES WITH MANUAL TICKS: {len(ticked_stale)}")
print("=" * 72)
