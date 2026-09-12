"""Find the min-content culprit forcing horizontal overflow."""
import functools, http.server, socketserver, threading
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
LOOKBOOKS = ROOT / "data" / "lookbooks"
PORT = 8794


class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


handler = functools.partial(Q, directory=str(LOOKBOOKS))
socketserver.TCPServer.allow_reuse_address = True
httpd = socketserver.TCPServer(("127.0.0.1", PORT), handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

with sync_playwright() as pw:
    b = pw.chromium.launch()
    ctx = b.new_context(viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True)
    page = ctx.new_page()
    page.goto(f"http://127.0.0.1:{PORT}/test-tldr-render.html", wait_until="networkidle")

    print("=== cluster card text content ===")
    print(page.evaluate("""
      () => Array.from(document.querySelectorAll('.cluster-card'))
        .map(c => c.textContent.trim().replace(/\\s+/g,' ').slice(0,120))
    """))

    print("\n=== ancestor chain widths of .cluster-card ===")
    print(page.evaluate("""
      () => {
        let el = document.querySelector('.cluster-card');
        const out = [];
        while (el && el !== document.documentElement) {
          const r = el.getBoundingClientRect();
          const cs = getComputedStyle(el);
          const cls = (typeof el.className === 'string' ? el.className : '')
            .trim().split(/\\s+/).slice(0,2).join('.');
          out.push(`${el.tagName.toLowerCase()}.${cls}  w=${Math.round(r.width)} ` +
                   `minW=${cs.minWidth} disp=${cs.display} gtc=${cs.gridTemplateColumns} ` +
                   `pad=${cs.padding} ovf=${cs.overflowX}`);
          el = el.parentElement;
        }
        return out;
      }
    """))

    print("\n=== mobile sticky bar ===")
    print(page.evaluate("""
      () => {
        const bar = document.querySelector('.mobile-sticky-bar');
        const inner = document.querySelector('.mobile-sticky-inner');
        const btn = document.querySelector('.mobile-sticky-btn');
        const name = document.querySelector('.mobile-sticky-name');
        const g = e => { const r=e.getBoundingClientRect(); const c=getComputedStyle(e);
          return `w=${Math.round(r.width)} h=${Math.round(r.height)} disp=${c.display} ` +
                 `ws=${c.whiteSpace} pos=${c.position} ovf=${c.overflowX}`; };
        return ['bar:   '+g(bar), 'inner: '+g(inner), 'btn:   '+g(btn), 'name:  '+g(name)];
      }
    """))

    print("\n=== images natural vs rendered ===")
    print(page.evaluate("""
      () => Array.from(document.querySelectorAll('img')).slice(0,6).map(i => {
        const r = i.getBoundingClientRect();
        return `nat=${i.naturalWidth}x${i.naturalHeight} rend=${Math.round(r.width)}x${Math.round(r.height)} cls=${i.className||i.parentElement.className}`;
      })
    """))

    ctx.close()
    b.close()

httpd.shutdown()
