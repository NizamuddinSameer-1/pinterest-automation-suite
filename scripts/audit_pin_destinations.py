"""
Pin destination reconciliation — separates REAL product pins from TEST artifacts.

Why this exists
---------------
`data/pre.db` accumulated pin drafts and lookbook pages from months of testing
alongside real product work. Pins point at destinations that were never deployed
to the Vercel edge, so a click 404s. Before republishing or retiring anything we
need an evidence-based split: which destinations belong to a real affiliate
product (has an ASIN), and which are test scaffolding that should never have
been published.

Read-only by default. Pass --json to dump the full result set.

Usage
-----
    python -m scripts.audit_pin_destinations
    python -m scripts.audit_pin_destinations --json > report.json
    python -m scripts.audit_pin_destinations --no-probe      # skip HTTP
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "pre.db"
LOOKBOOKS_DIR = ROOT / "data" / "lookbooks"
LIVE_BASE = "https://pinterest-lookbooks-beta.vercel.app"
PROBE_TIMEOUT = 15

# Slugs that are unmistakably test scaffolding, never production content.
TEST_SLUG_MARKERS = (
    "test-", "-test-", "prod-", "prod-test", "job1", "job-batch",
    "reference-product", "job-batc", "test-tld", "test-com",
    "job-seo-test", "job-test",
)

# Product names that are structural placeholders, not merchandise.
PLACEHOLDER_PRODUCT_NAMES = {
    "reference product",
    "dog",
    "leggings",
    "black leggings",
    "maid costume",
    "halloween pajama pants",
    "adult pumpkin costume poncho set",
    "brown and plaid almond manicure",
    "fall polka dot manicure",
    "oversized black leather utility jacket",
}


def classify_slug(slug: str) -> bool:
    """True when the slug itself is test scaffolding."""
    s = slug.lower()
    return any(marker in s for marker in TEST_SLUG_MARKERS)


def classify_product(name: str | None, asin: str | None) -> tuple[str, str]:
    """
    Return (verdict, reason).

    verdict is one of: "real", "placeholder", "test".
    A product with an ASIN is real affiliate merchandise — full stop. Without an
    ASIN there is no trackable commission, so the page cannot monetise.
    """
    if asin and str(asin).strip():
        return "real", f"has ASIN {asin}"

    low = (name or "").strip().lower()
    if low in PLACEHOLDER_PRODUCT_NAMES:
        return "placeholder", "known placeholder product name"
    if "viral inspo guide" in low:
        return "placeholder", "trend-inspiration entry, not a product"
    if low in {"", "reference product"}:
        return "test", "unset product name"
    return "placeholder", "no ASIN — untrackable"


def probe(url: str) -> tuple[int | None, str]:
    """Return (http_status, error). Status None means the request failed."""
    if not url:
        return None, "empty"
    try:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT) as resp:
            return resp.status, ""
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:  # noqa: BLE001 — network noise is expected, report it
        return None, type(e).__name__


def load_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return list(
        conn.execute(
            """
            SELECT p.id            AS pin_id,
                   p.title         AS pin_title,
                   p.status        AS pin_status,
                   p.destination_url AS dest,
                   p.board_name    AS board,
                   j.id            AS job_id,
                   pr.id           AS product_id,
                   pr.name         AS product_name,
                   pr.asin         AS asin,
                   pr.affiliate_url AS affiliate_url
            FROM pin_drafts p
            LEFT JOIN jobs j     ON j.id = p.job_id
            LEFT JOIN products pr ON pr.id = j.product_id
            ORDER BY p.rowid
            """
        )
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="emit JSON instead of text")
    ap.add_argument("--no-probe", action="store_true", help="skip live HTTP checks")
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"database not found: {DB_PATH}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    rows = load_rows(conn)

    # ── classify every pin ────────────────────────────────────────────────
    pins: list[dict] = []
    for r in rows:
        dest = (r["dest"] or "").strip()
        slug = dest.rsplit("/", 1)[-1] if dest else ""
        if slug.startswith("?"):
            slug = ""
        verdict, reason = classify_product(r["product_name"], r["asin"])
        if slug and classify_slug(slug):
            verdict, reason = "test", "test slug pattern"

        pins.append({
            "pin_id": r["pin_id"],
            "pin_title": r["pin_title"],
            "pin_status": r["pin_status"],
            "destination": dest,
            "slug": slug,
            "board": r["board"],
            "job_id": r["job_id"],
            "product_name": r["product_name"],
            "asin": r["asin"],
            "verdict": verdict,
            "reason": reason,
        })

    # ── group by destination and probe once per unique URL ────────────────
    by_dest: dict[str, list[dict]] = defaultdict(list)
    for p in pins:
        by_dest[p["destination"]].append(p)

    destinations: list[dict] = []
    for dest, group in by_dest.items():
        slug = group[0]["slug"]
        local_exists = bool(slug) and (LOOKBOOKS_DIR / slug).exists()
        og_slug = slug.replace(".html", "-og.webp") if slug.endswith(".html") else ""
        og_exists = bool(og_slug) and (LOOKBOOKS_DIR / og_slug).exists()

        if args.no_probe:
            status, err = None, "skipped"
        else:
            status, err = probe(dest)

        verdicts = {g["verdict"] for g in group}
        if verdicts == {"real"}:
            mixed = "real"
        elif "real" in verdicts:
            mixed = "mixed"
        else:
            mixed = "non_real"

        destinations.append({
            "destination": dest,
            "slug": slug,
            "pin_count": len(group),
            "published_count": sum(1 for g in group if g["pin_status"] == "published"),
            "http_status": status,
            "probe_error": err,
            "local_file_exists": local_exists,
            "og_image_exists": og_exists,
            "verdict": mixed,
            "products": sorted({(g["product_name"] or "?") for g in group}),
            "reasons": sorted({g["reason"] for g in group}),
            "pins": group,
        })

    destinations.sort(key=lambda d: (-d["pin_count"], d["destination"]))

    if args.json:
        json.dump({"destinations": destinations, "pins": pins}, sys.stdout, indent=2)
        return 0

    # ── human-readable report ─────────────────────────────────────────────
    live = [d for d in destinations if d["http_status"] == 200]
    dead = [d for d in destinations if d["http_status"] not in (None, 200)]
    empty = [d for d in destinations if not d["destination"]]
    failed = [d for d in destinations if d["http_status"] is None and d["destination"]]

    print("=" * 78)
    print("PIN DESTINATION RECONCILIATION")
    print("=" * 78)
    print(f"pins total           : {len(pins)}")
    print(f"distinct destinations: {len(destinations)}")
    print(f"  live (200)         : {len(live)}")
    print(f"  dead (4xx/5xx)     : {len(dead)}")
    print(f"  probe failed       : {len(failed)}")
    print(f"  empty (no URL)     : {len(empty)}")
    print()

    print("-" * 78)
    print("DEAD DESTINATIONS  — every click from these pins is lost")
    print("-" * 78)
    if not dead:
        print("  none")
    for d in dead:
        tag = {"real": "REAL", "mixed": "MIXED", "non_real": "TEST"}[d["verdict"]]
        print(f"  [{tag:5}] HTTP {d['http_status']}  {d['slug'] or d['destination']}")
        print(f"           pins={d['pin_count']} (published={d['published_count']})"
              f"  local_file={'yes' if d['local_file_exists'] else 'NO'}")
        for pname in d["products"]:
            print(f"           product: {pname}")
    print()

    print("-" * 78)
    print("EMPTY DESTINATIONS — pins that cannot convert at all")
    print("-" * 78)
    if not empty:
        print("  none")
    for d in empty:
        tag = {"real": "REAL", "mixed": "MIXED", "non_real": "TEST"}[d["verdict"]]
        print(f"  [{tag:5}] {d['pin_count']} pins (published={d['published_count']})"
              f"  products: {', '.join(d['products'])}")
    print()

    print("-" * 78)
    print("SPLIT BY PRODUCT VERDICT")
    print("-" * 78)
    for verdict, label in (
        ("real", "REAL — has ASIN, monetisable, worth fixing"),
        ("placeholder", "PLACEHOLDER — no ASIN, cannot earn"),
        ("test", "TEST — scaffolding, never should have published"),
    ):
        subset = [p for p in pins if p["verdict"] == verdict]
        if not subset:
            continue
        pub = sum(1 for p in subset if p["pin_status"] == "published")
        print(f"  {label}")
        print(f"      pins={len(subset)}  published={pub}")
    print()

    print("-" * 78)
    print("TEST / PLACEHOLDER SLUGS STILL PUBLICLY DEPLOYED OR IN SITEMAP")
    print("-" * 78)
    sitemap = LOOKBOOKS_DIR / "sitemap.xml"
    if sitemap.exists():
        xml = sitemap.read_text(encoding="utf-8", errors="ignore")
        suspects = sorted({
            s for s in TEST_SLUG_MARKERS
            if s in xml
        })
        for slug_file in sorted(LOOKBOOKS_DIR.glob("*.html")):
            name = slug_file.name
            if classify_slug(name) or "index" in name:
                in_map = name in xml
                print(f"  {'IN SITEMAP' if in_map else 'not listed':11}  {name}")
        print()
        print(f"  (matched markers in sitemap: {suspects})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
