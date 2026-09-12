"""
Retrofit already-generated lookbook pages with the responsive fixes.

New pages pick everything up from the updated Jinja template, but the pages
already sitting in data/lookbooks/ were rendered by the old one. Most of the
responsive work is carried by the external stylesheet, so those pages are
already fixed by the CSS swap alone. What the stylesheet *cannot* fix is:

  * Runaway HTML entity text inside the cluster cards, e.g.
    "Style &amp;amp;amp;...amp; Wear Tests" — this is content, not layout.
  * Missing hook classes the new stylesheet targets (.chip-sep, .price-brand,
    .sidebar-buy-widget, ...), which the old template never emitted.
  * The old viewport meta without viewport-fit=cover, so
    env(safe-area-inset-bottom) resolves to 0 and the sticky CTA sits under
    the iOS home indicator.

This script applies those mechanical edits in place. It is idempotent: running
it twice changes nothing the second time.

Usage:
    python scratch/retrofit_lookbooks.py --dry-run
    python scratch/retrofit_lookbooks.py
"""

from __future__ import annotations

import argparse
import html as html_lib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOOKBOOKS = ROOT / "data" / "lookbooks"

sys.path.insert(0, str(ROOT))


def clean_text(text: str, max_len: int = 120) -> str:
    """Fixed-point unescape + tag strip + ampersand-run collapse (see article_generator)."""
    if not text:
        return ""
    out = text
    for _ in range(64):
        unescaped = html_lib.unescape(out)
        if unescaped == out:
            break
        out = unescaped
    out = re.sub(r"<[^>]+>", " ", out)
    out = re.sub(r"(?:\s*&\s*){2,}", " & ", out)
    out = re.sub(r"\s+", " ", out).strip()
    if len(out) > max_len:
        out = out[:max_len].rsplit(" ", 1)[0] or out[:max_len]
    return out.strip()


def has_runaway(text: str) -> bool:
    """True if the text contains an escaped-entity run rather than real content."""
    return bool(re.search(r"&amp;(?:amp;){2,}", text)) or text.count("&amp;") >= 3


# Text nodes only: everything between a `>` and the next `<`.
_TEXT_NODE = re.compile(r">([^<>]+)<")
# Blocks whose contents are NOT HTML text and must not be touched.
_PROTECTED = re.compile(
    r"(<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>)",
    re.IGNORECASE | re.DOTALL,
)


def normalize_text_nodes(src: str) -> tuple[str, int]:
    """
    Repair entity-corrupted text in every text node of the document.

    Older lookbook pages were rendered by an earlier template that emitted
    different markup (inline styles instead of classes, e.g. an uppercase
    category `<div style="...">`). Rather than writing one regex per historical
    variant, this walks all text nodes and normalises any that carry an entity
    run. That covers old and new markup identically.

    Normalisation is idempotent — a correctly single-escaped value round-trips
    to itself, while a double-escaped or runaway one is repaired — so running
    this repeatedly is safe.

    `<script>`/`<style>` bodies are masked first: JSON-LD and CSS are not HTML
    text and must not be entity-decoded.
    """
    fixes = 0
    stash: list[str] = []

    def mask(m: re.Match) -> str:
        stash.append(m.group(1))
        return f"\x00{len(stash) - 1}\x00"

    src = _PROTECTED.sub(mask, src)

    def repl(m: re.Match) -> str:
        nonlocal fixes
        raw = m.group(1)
        if "&amp;" not in raw and "&#" not in raw:
            return m.group(0)

        out = raw
        for _ in range(64):
            unescaped = html_lib.unescape(out)
            if unescaped == out:
                break
            out = unescaped
        # One literal `&` becomes a run of adjacent ampersands; collapse it.
        out = re.sub(r"(?:\s*&\s*){2,}", " & ", out)
        if raw.strip():
            out = re.sub(r"\s+", " ", out).strip()

        if out == raw:
            return m.group(0)

        fixes += 1
        return ">" + html_lib.escape(out, quote=False) + "<"

    src = _TEXT_NODE.sub(repl, src)

    def unmask(m: re.Match) -> str:
        return stash[int(m.group(1))]

    src = re.sub(r"\x00(\d+)\x00", unmask, src)
    return src, fixes


def add_hook_classes(src: str) -> tuple[str, int]:
    """Emit the class hooks the new stylesheet targets."""
    fixes = 0

    # viewport meta -> add viewport-fit=cover + companion metas
    old_vp = '<meta name="viewport" content="width=device-width, initial-scale=1.0" />'
    new_vp = (
        '<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />\n'
        '  <meta name="theme-color" content="#FFFFFF" />\n'
        '  <meta name="format-detection" content="telephone=no" />\n'
        '  <meta name="color-scheme" content="light" />'
    )
    if old_vp in src:
        src = src.replace(old_vp, new_vp, 1)
        fixes += 1

    # Trust-chip separators, so they can be hidden when the chips stack.
    before = src
    src = re.sub(
        r'(<div class="trust-chips">\s*<span>[^<]*</span>\s*)<span>•</span>',
        r'\1<span class="chip-sep">•</span>', src)
    src = src.replace('<span>•</span>\n            <span>✓', '<span class="chip-sep">•</span>\n            <span>✓')
    src = src.replace('<span>•</span>\n            <span>✓', '<span class="chip-sep">•</span>\n            <span>✓')
    if src != before:
        fixes += 1

    # Price row: inline styles -> classes, so the row can stack on small phones.
    src, n = re.subn(
        r'<div style="font-size: 11\.5px; text-transform: uppercase; letter-spacing: 0\.03em; color: var\(--ink-muted\); margin-bottom: 2px;">Verified Amazon Price</div>',
        '<div class="price-label">Verified Amazon Price</div>', src)
    fixes += n
    src, n = re.subn(
        r'<div style="text-align: right;">\s*<div style="font-size: 11\.5px; text-transform: uppercase; letter-spacing: 0\.03em; color: var\(--ink-muted\);">Brand</div>\s*<div style="font-family: var\(--font-display\); font-size: 18px; font-weight: 600; color: var\(--ink\);">',
        '<div class="price-brand">\n              <div class="price-brand-label">Brand</div>\n              <div class="price-brand-name">', src)
    fixes += n

    # Sidebar buy widget: tag it so it can be hidden where the sticky bar
    # already carries the same CTA.
    src, n = re.subn(
        r'<div class="sidebar-widget" style="padding: 24px;">',
        '<div class="sidebar-widget sidebar-buy-widget">', src)
    fixes += n

    # Sidebar product meta inline styles -> classes.
    src, n = re.subn(
        r'<div style="font-weight:600; font-size:15px; margin-bottom:4px;">',
        '<div class="sidebar-prod-name">', src)
    fixes += n
    src, n = re.subn(
        r'<div style="color:var\(--ink-muted\); font-size:12\.5px; margin-bottom:12px;">',
        '<div class="sidebar-prod-brand">', src)
    fixes += n
    src, n = re.subn(
        r'<div style="font-family:var\(--font-display\); font-size:24px; font-weight:700; margin-bottom:14px;">',
        '<div class="sidebar-prod-price">', src)
    fixes += n
    src, n = re.subn(
        r'style="width:100%; border-radius:6px;"',
        '', src)
    fixes += n

    # Older pages emitted the related-guide category as an inline-styled div.
    src, n = re.subn(
        r'<div style="font-size:10\.5px; font-weight:700; text-transform:uppercase; color:var\(--accent\);">',
        '<div class="sidebar-related-cat">', src)
    fixes += n

    # Sidebar related-guide rows -> classes.
    src, n = re.subn(
        r'<div style="margin-bottom:12px; padding-bottom:10px; border-bottom:1px solid var\(--border\);">',
        '<div class="sidebar-related-item">', src)
    fixes += n
    src, n = re.subn(
        r'<div style="font-size:11\.5px; font-weight:700; text-transform:uppercase; color:var\(--accent\);">',
        '<div class="sidebar-related-cat">', src)
    fixes += n
    src, n = re.subn(
        r'<a href="([^"]+)" style="font-size:13px; font-weight:600; color:var\(--ink\); line-height:1\.4; display:block;">',
        r'<a href="\1" class="sidebar-related-link">', src)
    fixes += n
    src, n = re.subn(
        r'<p style="font-size:13px; color:var\(--ink-soft\); line-height:1\.55; margin:0;">',
        '<p class="sidebar-guarantee">', src)
    fixes += n

    # Hero + look images: drop the fixed intrinsic dimensions (the frame now
    # owns the aspect ratio) and add modern loading hints.
    src, n = re.subn(
        r'(<img src="[^"]*" alt="[^"]*" loading="eager") width="640" height="960" />',
        r'\1 fetchpriority="high" decoding="async" />', src)
    fixes += n
    src, n = re.subn(
        r'(<img src="[^"]*" alt="[^"]*" loading="lazy") width="640" height="960" />',
        r'\1 decoding="async" />', src)
    fixes += n

    return src, fixes


def process(path: Path, dry_run: bool) -> tuple[bool, int]:
    original = path.read_text(encoding="utf-8")
    src = original

    src, f1 = normalize_text_nodes(src)
    src, f2 = add_hook_classes(src)

    total = f1 + f2
    if src != original:
        if not dry_run:
            path.write_text(src, encoding="utf-8")
        return True, total
    return False, 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    pages = sorted(LOOKBOOKS.glob("*.html"))
    pages = [p for p in pages if p.name != "index.html"]

    changed = 0
    total_fixes = 0
    for p in pages:
        did, n = process(p, args.dry_run)
        if did:
            changed += 1
            total_fixes += n
            print(f"  {'WOULD PATCH' if args.dry_run else 'patched'}: {p.name}  ({n} edits)")

    print(f"\n{changed}/{len(pages)} pages {'need' if args.dry_run else 'got'} "
          f"{total_fixes} total edits")


if __name__ == "__main__":
    main()
