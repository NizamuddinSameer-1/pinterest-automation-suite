"""
Mobile / multi-device responsiveness audit harness.

Serves data/lookbooks/ over a local HTTP server (the pages use absolute
/lookbook.css and /img/* paths, so file:// will not resolve them), then
screenshots representative pages at real device widths and reports
horizontal-overflow offenders and undersized tap targets.

Usage:
    python scratch/mobile_audit.py [--tag before|after]
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import socketserver
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
LOOKBOOKS = ROOT / "data" / "lookbooks"
OUT_ROOT = ROOT / "scratch" / "mobile_audit"

PORT = 8791

# Real device viewports worth caring about, smallest first.
DEVICES = [
    ("320-small", 320, 568),      # iPhone SE 1st gen / Galaxy Fold folded
    ("360-android", 360, 800),    # Most common Android
    ("375-iphone", 375, 812),     # iPhone X/11/12/13 mini
    ("390-iphone14", 390, 844),   # iPhone 14 / 15
    ("414-iphoneplus", 414, 896), # iPhone Plus / XR
    ("768-ipad", 768, 1024),      # iPad portrait
    ("1024-ipad-ls", 1024, 768),  # iPad landscape / small laptop
    ("1440-desktop", 1440, 900),  # Desktop reference
]

# Pages to audit. Keep it to one representative review page + the catalog.
PAGES = [
    ("lookbook", "test-tldr-render.html"),
    ("lookbook2", "reference-product-88729bb1.html"),
    ("catalog", "index.html"),
]


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # silence request spam
        pass


def start_server() -> socketserver.TCPServer:
    handler = functools.partial(QuietHandler, directory=str(LOOKBOOKS))
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def audit_page(page, url: str, width: int) -> dict:
    """Collect objective responsiveness defects for the current viewport."""
    return page.evaluate(
        """
        (vw) => {
          const out = { scrollWidth: document.documentElement.scrollWidth,
                        clientWidth: document.documentElement.clientWidth,
                        overflow: [], smallTaps: [], tinyText: [] };

          // 1. Horizontal overflow offenders.
          //    Elements inside a horizontal scroll/clip container are skipped:
          //    they legitimately extend past the viewport and are contained by
          //    their ancestor, so they do not widen the page.
          const containedByScroller = (el) => {
            let p = el.parentElement;
            while (p && p !== document.body) {
              const ox = getComputedStyle(p).overflowX;
              if (ox === 'auto' || ox === 'scroll' || ox === 'hidden' || ox === 'clip') return true;
              p = p.parentElement;
            }
            return false;
          };
          const all = document.querySelectorAll('body *');
          for (const el of all) {
            const r = el.getBoundingClientRect();
            if (r.width === 0 || r.height === 0) continue;
            const style = getComputedStyle(el);
            if (style.position === 'fixed') continue;
            // element extends past the right edge (allow 1px rounding)
            if (r.right > vw + 1 && !containedByScroller(el)) {
              const cls = (el.className && typeof el.className === 'string')
                ? el.className.trim().split(/\\s+/).slice(0,3).join('.') : '';
              out.overflow.push({
                tag: el.tagName.toLowerCase(),
                cls: cls,
                right: Math.round(r.right),
                overBy: Math.round(r.right - vw)
              });
            }
          }

          // 2. Tap targets smaller than 44x44 (WCAG 2.5.5 / Apple HIG)
          for (const el of document.querySelectorAll('a, button, summary, [onclick]')) {
            const r = el.getBoundingClientRect();
            if (r.width === 0 || r.height === 0) continue;
            if (r.height < 40 || r.width < 40) {
              const cls = (el.className && typeof el.className === 'string')
                ? el.className.trim().split(/\\s+/).slice(0,2).join('.') : '';
              out.smallTaps.push({
                tag: el.tagName.toLowerCase(), cls: cls,
                w: Math.round(r.width), h: Math.round(r.height),
                text: (el.textContent || '').trim().slice(0, 28)
              });
            }
          }

          // 3. Body text below 12px hurts readability on phones
          for (const el of document.querySelectorAll('p, li, span, div')) {
            if (!el.textContent || el.textContent.trim().length < 12) continue;
            if (el.children.length > 0) continue;
            const fs = parseFloat(getComputedStyle(el).fontSize);
            if (fs && fs < 12) {
              const cls = (el.className && typeof el.className === 'string')
                ? el.className.trim().split(/\\s+/).slice(0,2).join('.') : '';
              out.tinyText.push({ cls, fs: Math.round(fs*10)/10 });
            }
          }
          // dedupe overflow entries by tag+class+overBy
          const seen = new Set();
          out.overflow = out.overflow.filter(o => {
            const k = o.tag + o.cls + o.overBy;
            if (seen.has(k)) return false; seen.add(k); return true;
          }).slice(0, 12);
          out.smallTaps = out.smallTaps.slice(0, 12);
          out.tinyText = out.tinyText.slice(0, 8);
          return out;
        }
        """,
        width,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="before")
    args = ap.parse_args()

    out_dir = OUT_ROOT / args.tag
    out_dir.mkdir(parents=True, exist_ok=True)

    httpd = start_server()
    report: dict = {}

    # A fresh browser per page. Reusing one Chromium across every
    # page x viewport combination accumulates renderer state and eventually
    # crashes the process partway through the run.
    for page_name, filename in PAGES:
        url = f"http://127.0.0.1:{PORT}/{filename}"
        report[page_name] = {}
        for dev_name, w, h in DEVICES:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                ctx = browser.new_context(
                    viewport={"width": w, "height": h},
                    device_scale_factor=1,
                    is_mobile=(w <= 480),
                    has_touch=(w <= 1024),
                )
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(500)

                data = audit_page(page, url, w)
                report[page_name][dev_name] = data

                # Viewport-sized captures. Full-page shots are avoided because
                # a long editorial review exceeds Chrome's capture limit.
                shot = out_dir / f"{page_name}_{dev_name}.png"
                try:
                    page.screenshot(path=str(shot))
                except Exception as exc:  # pragma: no cover - diagnostics only
                    print(f"  (screenshot skipped for {page_name}/{dev_name}: {exc})")

                ctx.close()
                browser.close()

    httpd.shutdown()

    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    # Console summary
    print(f"\n{'='*78}\nMOBILE AUDIT [{args.tag}]\n{'='*78}")
    for page_name, devs in report.items():
        print(f"\n### {page_name}")
        for dev_name, d in devs.items():
            flag = "OVERFLOW" if d["overflow"] else "ok"
            print(f"  {dev_name:16s} scrollW={d['scrollWidth']:5d} "
                  f"clientW={d['clientWidth']:5d}  {flag:9s} "
                  f"smallTaps={len(d['smallTaps']):2d} tinyText={len(d['tinyText']):2d}")
            for o in d["overflow"][:4]:
                print(f"       > {o['tag']}.{o['cls']} overflows by {o['overBy']}px")
    print(f"\nScreenshots + report.json -> {out_dir}")


if __name__ == "__main__":
    main()
