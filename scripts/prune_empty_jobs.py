"""
Report (and optionally delete) jobs that were created but never used.

    python -m scripts.prune_empty_jobs            # dry run — lists, changes nothing
    python -m scripts.prune_empty_jobs --delete   # actually removes them

Every click on "Generate" used to create the job row *first* and only then
discover that the reference had no Visual DNA, so a 409 left an empty DRAFT job
behind. The Creative Lab now checks before creating the job, but the rows that
already accumulated are still there.

Only jobs that are DRAFT **and** have no outputs, no prompt versions and no pin
drafts are eligible (critiques hang off an output, so a job with no outputs has
none). Anything with a single artefact attached is real history and is never
touched.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "pre.db"

QUERY = """
SELECT j.id, j.reference_id, j.product_id, j.created_at
FROM jobs j
WHERE j.current_state = 'DRAFT'
  AND NOT EXISTS (SELECT 1 FROM job_outputs     o WHERE o.job_id = j.id)
  AND NOT EXISTS (SELECT 1 FROM prompt_versions p WHERE p.job_id = j.id)
  AND NOT EXISTS (SELECT 1 FROM pin_drafts      d WHERE d.job_id = j.id)
  -- critiques hang off an output, not a job, so a job with no outputs cannot
  -- have one; the outputs check above already covers them.
ORDER BY j.created_at
"""


def main(delete: bool) -> int:
    if not DB.is_file():
        print(f"No database at {DB}")
        return 1

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute(QUERY))

    total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    print(f"{len(rows)} empty DRAFT job(s) out of {total} total:")
    for r in rows:
        print(f"  {r['id']}  ref={r['reference_id'][:8]}  prod={r['product_id']}  {r['created_at']}")

    if not rows:
        return 0
    if not delete:
        print("\nDry run — nothing was changed. Re-run with --delete to remove them.")
        return 0

    conn.executemany("DELETE FROM jobs WHERE id = ?", [(r["id"],) for r in rows])
    conn.commit()
    print(f"\nDeleted {len(rows)} empty DRAFT job(s). {conn.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]} remain.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="python -m scripts.prune_empty_jobs")
    parser.add_argument("--delete", action="store_true", help="actually delete (default: dry run)")
    sys.exit(main(parser.parse_args().delete))
