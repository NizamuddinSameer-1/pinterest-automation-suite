"""
Repoint published pins at working destinations.

Why this exists
---------------
`scripts/audit_pin_destinations.py` found that of the 11 published pins, only 2
belonged to a real ASIN product — and both pointed at lookbook pages that return
404. The remaining 9 belonged to placeholder products with no ASIN, so they could
never earn commission even when their page loaded.

Two approved fixes:

  1. Real ASIN pins -> the first-party smart redirect (`/api/go?asin=...`).
     Verified live: it resolves to the correct Amazon host and affiliate tag,
     and carries `ascsubtag` attribution. This monetises the click immediately
     instead of depending on a page that was never deployed.

  2. Placeholder pins -> the closest real ASIN product, where one genuinely
     exists (3 maid pins -> Avidlove Maid Lingerie; 1 pumpkin poncho pin ->
     WISHTEN Pumpkin Costume).

The mapping is EXPLICIT and hardcoded on purpose. Fuzzy product matching would
be a liability here: a wrong repoint sends a shopper to the wrong product and
burns trust, which costs more than the click is worth.

IMPORTANT — this only fixes the local database
----------------------------------------------
Pinterest stores the destination on the pin itself. Changing `destination_url`
here does NOT alter a pin that is already live; the stored destination must be
edited on Pinterest for the live click to change. This script prepares the
correct data and reports exactly which pins need that follow-up.

Dry-run by default. `--apply` writes inside a transaction and snapshots the
database first.

Usage
-----
    python -m scripts.remediate_pin_destinations
    python -m scripts.remediate_pin_destinations --apply
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "pre.db"

sys.path.insert(0, str(ROOT))
from app.config import settings  # noqa: E402
from app.services.affiliate_router import build_smart_redirect_url  # noqa: E402

# pin_id -> ASIN it should point at.
REPOINT_TO_ASIN: dict[str, str] = {
    # ── Real products whose lookbook page 404s ──────────────────────────
    "2d6aa051-e725-47c1-b23b-3dada5d0ed25": "B0CHQJLQTC",  # WISHTEN Pumpkin Costume
    "933977ae-c55e-4ebd-85a3-ff0066a6b0cf": "B07WPLQXFK",  # Halloween Pajama Pants
    # ── Placeholder pins repointed to the closest real product ──────────
    "35a06f48-1792-4fb2-a458-b61297c772b1": "B0C6JMBCLB",  # "Maid Costume" -> Avidlove
    "68677345-e127-429e-81d0-47e6149c51ca": "B0C6JMBCLB",  # "Maid Costume" -> Avidlove
    "d6487e6b-1857-4b55-b19d-1c8064dcbc27": "B0C6JMBCLB",  # "Maid Costume" -> Avidlove
    "dbb266e5-f48a-4876-8ec1-cf9dba1bb792": "B0CHQJLQTC",  # Poncho -> WISHTEN Pumpkin
}

# Published pins with NO real product equivalent. There is no ASIN-bearing nail
# product in the catalogue, so there is nothing honest to repoint them at.
# Recorded for review rather than silently rewritten.
NO_EQUIVALENT: dict[str, str] = {
    "6e58baa3-30e2-449e-a14b-fae873d010f4": "Dark Academia Nail Inspo",
    "8852d876-5b96-44b2-90db-cd4a3b7fcade": "Early September Nails | Press-On",
    "a293554e-b29f-4056-a89d-39a33d6e3ded": "Cottagecore Nail Art | Press-Ons",
    "d644a770-0c7c-4bdc-8574-818f60de27e4": "Coffee Girl Nails | Brown Plaid",
    "eed0f097-bc6e-4c29-97fb-6f0a5b81bfe0": "Cottagecore Nail Guide",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"database not found: {DB_PATH}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    print("=" * 78)
    print("REPOINT PIN DESTINATIONS" + ("" if args.apply else "  (DRY RUN — no writes)"))
    print("=" * 78)
    print(f"canonical host: {settings.bridge_domain}")
    print()

    planned: list[tuple[str, str, str, str]] = []  # pin_id, old, new, title
    missing: list[str] = []

    for pin_id, asin in REPOINT_TO_ASIN.items():
        row = cur.execute(
            "SELECT id, title, job_id, destination_url, status FROM pin_drafts WHERE id = ?",
            (pin_id,),
        ).fetchone()
        if row is None:
            missing.append(pin_id)
            continue

        new_url = build_smart_redirect_url(
            asin=asin,
            title=row["title"],
            job_id=row["job_id"],
            pin_id=pin_id,
            bridge_domain=settings.bridge_domain,
        )
        if (row["destination_url"] or "") == new_url:
            print(f"  unchanged  {row['title'][:60]}")
            continue
        planned.append((pin_id, row["destination_url"] or "(empty)", new_url, row["title"]))

    print("-" * 78)
    print(f"REPOINTS PLANNED: {len(planned)}")
    print("-" * 78)
    for pin_id, old, new, title in planned:
        print(f"  {title[:66]}")
        print(f"     from: {old[:72] or '(empty)'}")
        print(f"     to  : {new}")
    print()

    if missing:
        print("  WARNING — pin ids not found in database:")
        for m in missing:
            print(f"    {m}")
        print()

    print("-" * 78)
    print(f"NO REAL EQUIVALENT — left untouched ({len(NO_EQUIVALENT)})")
    print("-" * 78)
    for pin_id, label in NO_EQUIVALENT.items():
        row = cur.execute(
            "SELECT status FROM pin_drafts WHERE id = ?", (pin_id,)
        ).fetchone()
        state = row["status"] if row else "MISSING"
        print(f"  [{state}] {label}")
    print("  These need a decision (unpublish, or source a real nail product).")
    print()

    if not args.apply:
        print("  re-run with --apply to write these changes")
        conn.close()
        return 0

    # ── snapshot before writing ─────────────────────────────────────────
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup = DB_PATH.with_name(f"pre.db.backup_repoint_{stamp}")
    shutil.copy2(DB_PATH, backup)
    print(f"  database snapshot: {backup.name}")

    try:
        with conn:  # transaction
            for pin_id, _old, new, _title in planned:
                cur.execute(
                    "UPDATE pin_drafts SET destination_url = ? WHERE id = ?",
                    (new, pin_id),
                )
        print(f"  APPLIED — {len(planned)} pin destination(s) updated")
    except Exception as e:  # noqa: BLE001
        print(f"  FAILED, transaction rolled back: {e}", file=sys.stderr)
        conn.close()
        return 1

    print()
    print("  NEXT STEP — Pinterest stores the destination on the pin itself, so the")
    print("  live pins still point at the old URLs. Edit each pin's destination on")
    print("  Pinterest (or delete and republish) for the change to take effect live.")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
