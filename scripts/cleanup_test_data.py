"""One-off cleanup of test data.

Deletes every PinDraft (all test uploads) and every Job that never produced an
image, plus the prompt versions belonging to those jobs. Everything removed is
exported to JSON first so the operation is recoverable.

What is deliberately KEPT:
  - Jobs that have at least one JobOutput (they own real generated images)
  - All references, reference_analyses, visual_dnas
  - All products
  - All critiques (they hang off outputs we keep)

Run:
    python scripts/cleanup_test_data.py            # report only
    python scripts/cleanup_test_data.py --apply    # actually delete
    python scripts/cleanup_test_data.py --restore  # put everything back
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "pre.db")
ARCH = os.path.join(ROOT, "data", "_archive_2026-08-31")
DUMP = os.path.join(ARCH, "deleted_rows.json")
QUEUE = os.path.join(ROOT, "data", "scheduled_pins.json")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def empty_job_ids(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT id FROM jobs j "
        "WHERE NOT EXISTS (SELECT 1 FROM job_outputs o WHERE o.job_id = j.id)"
    ).fetchall()
    return [r["id"] for r in rows]


def report(conn: sqlite3.Connection) -> None:
    ids = empty_job_ids(conn)
    ph = ",".join("?" * len(ids))
    print("PLAN — nothing will be changed without --apply\n")
    print(f"  pin_drafts        {conn.execute('SELECT COUNT(*) FROM pin_drafts').fetchone()[0]}")
    print(f"  jobs (no images)  {len(ids)}")
    if ids:
        n = conn.execute(
            f"SELECT COUNT(*) FROM prompt_versions WHERE job_id IN ({ph})", tuple(ids)
        ).fetchone()[0]
        print(f"  prompt_versions   {n}")
    kept_pv = (
        conn.execute("SELECT COUNT(*) FROM prompt_versions").fetchone()[0] - n if ids
        else conn.execute("SELECT COUNT(*) FROM prompt_versions").fetchone()[0]
    )
    print("\nKEPT (untouched):")
    print(f"  jobs with images  {conn.execute('SELECT COUNT(*) FROM jobs').fetchone()[0] - len(ids)}")
    print(f"  job_outputs       {conn.execute('SELECT COUNT(*) FROM job_outputs').fetchone()[0]}")
    print(f"  prompt_versions   {kept_pv}  (of {conn.execute('SELECT COUNT(*) FROM prompt_versions').fetchone()[0]} today)")
    print(f"  references        {conn.execute('SELECT COUNT(*) FROM \"references\"').fetchone()[0]}")
    print(f"  products          {conn.execute('SELECT COUNT(*) FROM products').fetchone()[0]}")
    print(f"  critiques         {conn.execute('SELECT COUNT(*) FROM critiques').fetchone()[0]}")


def apply(conn: sqlite3.Connection) -> None:
    os.makedirs(ARCH, exist_ok=True)
    ids = empty_job_ids(conn)
    ph = ",".join("?" * len(ids))

    dump = {
        "_meta": {
            "exported_at": datetime.now().isoformat(),
            "empty_job_ids": ids,
            "reason": "test-data cleanup: unused pins + jobs with no generated images",
            "restore_with": "python scripts/cleanup_test_data.py --restore",
        },
        "pin_drafts": [dict(r) for r in conn.execute("SELECT * FROM pin_drafts")],
        "jobs": [
            dict(r) for r in conn.execute(
                f"SELECT * FROM jobs WHERE id IN ({ph})", tuple(ids)
            )
        ],
        "prompt_versions": [
            dict(r) for r in conn.execute(
                f"SELECT * FROM prompt_versions WHERE job_id IN ({ph})", tuple(ids)
            )
        ],
    }
    with open(DUMP, "w", encoding="utf-8") as fh:
        json.dump(dump, fh, indent=1, default=str)
    print(f"Backup written: {DUMP} ({os.path.getsize(DUMP) / 1024:.0f} KB)")
    print(f"  pin_drafts {len(dump['pin_drafts'])} | jobs {len(dump['jobs'])} "
          f"| prompt_versions {len(dump['prompt_versions'])}\n")

    cur = conn.cursor()
    cur.execute("DELETE FROM pin_drafts")
    print(f"  deleted pin_drafts:      {cur.rowcount}")
    cur.execute(f"DELETE FROM prompt_versions WHERE job_id IN ({ph})", tuple(ids))
    print(f"  deleted prompt_versions: {cur.rowcount}")
    cur.execute(f"DELETE FROM jobs WHERE id IN ({ph})", tuple(ids))
    print(f"  deleted jobs:            {cur.rowcount}")
    conn.commit()

    if os.path.exists(QUEUE):
        with open(QUEUE, encoding="utf-8") as fh:
            data = json.load(fh)
        n = len(data) if isinstance(data, list) else len(data.get("entries", []))
        with open(os.path.join(ARCH, "scheduled_pins.json.bak"), "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, default=str)
        if isinstance(data, list):
            data = []
        else:
            data["entries"] = []
        with open(QUEUE, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        print(f"  cleared schedule queue:  {n} entries")

    conn.execute("VACUUM")
    print(f"\n  database vacated -> {os.path.getsize(DB) / 1024:.0f} KB")


def restore(conn: sqlite3.Connection) -> None:
    if not os.path.exists(DUMP):
        print(f"No backup at {DUMP}")
        return
    with open(DUMP, encoding="utf-8") as fh:
        dump = json.load(fh)
    cur = conn.cursor()
    for table in ("jobs", "prompt_versions", "pin_drafts"):
        rows = dump.get(table, [])
        if not rows:
            continue
        cols = list(rows[0].keys())
        sql = (f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) "
               f"VALUES ({','.join('?' * len(cols))})")
        cur.executemany(sql, [tuple(r[c] for c in cols) for r in rows])
        print(f"  restored {table}: {len(rows)}")
    conn.commit()
    print("Restore complete.")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--report"
    conn = connect()
    try:
        if mode == "--apply":
            apply(conn)
        elif mode == "--restore":
            restore(conn)
        else:
            report(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
