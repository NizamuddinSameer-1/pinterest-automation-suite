"""Reconcile vault notes against the live database."""
from __future__ import annotations
import re, sqlite3, sys
from collections import Counter
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

VAULT = Path("vault")
DB = Path("data/pre.db")
FM = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n", re.S)

# ---- list all sqlite files ----
print("=== SQLITE FILES ===")
for p in Path("data").rglob("*.db"):
    print(f"  {p}  {p.stat().st_size/1024:.0f} KB")

conn = sqlite3.connect(DB)
print("\n=== TABLES ===")
tables = [r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
for t in tables:
    try:
        n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
    except sqlite3.Error as e:
        n = f"ERR {e}"
    print(f"  {t:<28} {n}")

# ---- pin reconciliation ----
print("\n=== PIN RECONCILIATION ===")
try:
    db_pins = {r[0] for r in conn.execute("SELECT id FROM pin_drafts")}
    print(f"  DB pin ids      : {len(db_pins)}")
except sqlite3.Error as e:
    db_pins = set()
    print(f"  pin_drafts error: {e}")

vault_pins = {}
for p in (VAULT / "04 - Campaigns & Products" / "Pins").glob("*.md"):
    raw = p.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'^pin_id:\s*"?([^"\n]+)"?', raw, re.M)
    pid = m.group(1).strip() if m else None
    vault_pins[p] = pid
print(f"  Vault pin notes : {len(vault_pins)}")
vids = {v for v in vault_pins.values() if v}
print(f"  distinct pin_ids: {len(vids)}")

if db_pins:
    orphan_notes = [(p, v) for p, v in vault_pins.items() if v and v not in db_pins]
    missing_notes = db_pins - vids
    print(f"  VAULT notes with NO DB row (stale) : {len(orphan_notes)}")
    print(f"  DB rows with NO vault note         : {len(missing_notes)}")
    print("  sample stale:", [p.name for p, _ in orphan_notes[:5]])
    dup_pids = [k for k, c in Counter(vids).items() if c > 1]
    print(f"  duplicate pin_id in vault          : {len(dup_pids)}")

# ---- job reconciliation ----
print("\n=== JOB RECONCILIATION ===")
try:
    db_jobs = {r[0] for r in conn.execute("SELECT id FROM jobs")}
    print(f"  DB job ids      : {len(db_jobs)}")
except sqlite3.Error as e:
    db_jobs = set(); print(f"  jobs error: {e}")

vault_jobs = {}
for p in (VAULT / "08 - Live Generation Nodes" / "Jobs").glob("*.md"):
    raw = p.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'^job_id:\s*"?([^"\n]+)"?', raw, re.M)
    vault_jobs[p] = m.group(1).strip() if m else None
print(f"  Vault job notes : {len(vault_jobs)}")
if db_jobs:
    stale_j = [p for p, v in vault_jobs.items() if v and v not in db_jobs]
    miss_j = db_jobs - {v for v in vault_jobs.values() if v}
    print(f"  stale job notes : {len(stale_j)}   missing: {len(miss_j)}")
    print("  sample stale:", [p.name for p in stale_j[:5]])

# ---- reference reconciliation ----
print("\n=== REFERENCE RECONCILIATION ===")
try:
    db_refs = {r[0] for r in conn.execute('SELECT id FROM "references"')}
    print(f"  DB ref ids      : {len(db_refs)}")
except sqlite3.Error as e:
    db_refs = set(); print(f"  references error: {e}")

vault_refs = {}
for p in (VAULT / "03 - Pipeline & Visual DNA" / "References").glob("*.md"):
    raw = p.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'^reference_id:\s*"?([^"\n]+)"?', raw, re.M)
    vault_refs[p] = m.group(1).strip() if m else None
print(f"  Vault ref notes : {len(vault_refs)}")
if db_refs:
    stale_r = [p for p, v in vault_refs.items() if v and v not in db_refs]
    print(f"  stale ref notes : {len(stale_r)}")

# ---- product reconciliation ----
print("\n=== PRODUCT RECONCILIATION ===")
try:
    db_prods = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM products")}
    print(f"  DB products     : {len(db_prods)}")
except sqlite3.Error as e:
    db_prods = {}; print(f"  products error: {e}")

vault_prods = set()
for p in (VAULT / "04 - Campaigns & Products" / "Products").glob("Product - *.md"):
    vault_prods.add(p.stem.replace("Product - ", ""))
print(f"  Vault product notes: {len(vault_prods)}")
missing_prod = {n for n in db_prods.values() if n not in vault_prods}
print(f"  DB products WITHOUT a note: {len(missing_prod)}")
for n in sorted(missing_prod)[:30]:
    print(f"      {n}")

# ---- test-data scope ----
print("\n=== TEST / SEED DATA IN DB ===")
for t, col in [("jobs", "id"), ("pin_drafts", "id"), ("products", "id"),
               ('"references"', "id"), ("campaigns", "id")]:
    try:
        rows = [r[0] for r in conn.execute(f'SELECT "{col}" FROM {t}')]
        tst = [r for r in rows if re.search(r"test|sample|dummy|placeholder", str(r), re.I)]
        print(f"  {t:<14} {len(tst)}/{len(rows)} look like test data")
        for x in tst[:6]:
            print(f"        {x}")
    except sqlite3.Error as e:
        print(f"  {t}: {e}")

conn.close()
