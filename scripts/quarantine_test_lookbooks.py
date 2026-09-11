"""
Quarantine test/dev lookbook pages from search engines.

Why this exists
---------------
Months of testing left generated pages in `data/lookbooks/` that are still
deployed to the live edge and were listed in `sitemap.xml` at priority 0.8.
On a young domain, thin near-duplicate pages burn crawl budget and dilute
quality signals. They are now excluded from the catalog/sitemap
(`git_publisher.is_public_lookbook_slug`); this script handles the pages that
are ALREADY deployed and may already be indexed, by adding a `noindex` robots
meta tag.

Adding noindex (rather than deleting) is deliberate: it is reversible, it does
not 404 anything a crawler has already seen, and Google drops the URL on the
next crawl.

Dry-run by default. Pass --apply to write changes (each file is backed up to
`data/lookbooks/.quarantine_backup/` first).

Usage
-----
    python -m scripts.quarantine_test_lookbooks
    python -m scripts.quarantine_test_lookbooks --apply
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOOKBOOKS_DIR = ROOT / "data" / "lookbooks"
BACKUP_DIR = LOOKBOOKS_DIR / ".quarantine_backup"

sys.path.insert(0, str(ROOT))
from app.services.git_publisher import is_public_lookbook_slug  # noqa: E402

NOINDEX_TAG = '<meta name="robots" content="noindex, nofollow" />'
ROBOTS_RE = re.compile(r'<meta\s+name=["\']robots["\'][^>]*>', re.IGNORECASE)
HEAD_RE = re.compile(r'<head[^>]*>', re.IGNORECASE)


def inject_noindex(html: str) -> tuple[str, str]:
    """
    Return (new_html, action) where action is one of:
    'already' | 'replaced' | 'inserted' | 'no_head'.
    """
    if ROBOTS_RE.search(html):
        existing = ROBOTS_RE.search(html)
        assert existing is not None
        if "noindex" in existing.group(0).lower():
            return html, "already"
        return ROBOTS_RE.sub(NOINDEX_TAG, html, count=1), "replaced"

    m = HEAD_RE.search(html)
    if not m:
        return html, "no_head"
    return html[: m.end()] + "\n  " + NOINDEX_TAG + html[m.end():], "inserted"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    if not LOOKBOOKS_DIR.exists():
        print(f"lookbooks dir not found: {LOOKBOOKS_DIR}", file=sys.stderr)
        return 1

    targets = [
        f for f in sorted(LOOKBOOKS_DIR.glob("*.html"))
        if f.name != "index.html" and not is_public_lookbook_slug(f.stem)
    ]

    print("=" * 74)
    print("QUARANTINE TEST LOOKBOOKS" + ("" if args.apply else "  (DRY RUN — no writes)"))
    print("=" * 74)
    if not targets:
        print("  no test/dev pages found")
        return 0

    if args.apply:
        BACKUP_DIR.mkdir(exist_ok=True)

    changed = 0
    for f in targets:
        html = f.read_text(encoding="utf-8", errors="ignore")
        new_html, action = inject_noindex(html)

        if action == "no_head":
            print(f"  SKIP (no <head>)   {f.name}")
            continue
        if action == "already":
            print(f"  ok (already set)   {f.name}")
            continue

        print(f"  {'WILL SET' if not args.apply else 'SET     '} noindex   {f.name}")
        if args.apply:
            shutil.copy2(f, BACKUP_DIR / f.name)
            f.write_text(new_html, encoding="utf-8")
        changed += 1

    print()
    print(f"  pages targeted : {len(targets)}")
    print(f"  pages changed  : {changed}")
    if args.apply and changed:
        print(f"  backups        : {BACKUP_DIR}")
    elif not args.apply and changed:
        print("  re-run with --apply to write these changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
