"""Quick diagnostic: is lookbook.css loading, and what is actually wide?"""
import functools, http.server, socketserver, threading
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
LOOKBOOKS = ROOT / "data" / "lookbooks"
PORT = 8793


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


handler = functools.partial(QuietHandler, directory=str(LOOKBOOKS))
socketserver.TCPServer.allow_reuse_address = True
httpd = socketserver.TCPServer(("127.0.0.1", PORT), handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

with sync_playwright() as pw:
    b = pw.chromium.launch()
    ctx = b.new_context(viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True)
    page = ctx.new_page()

    responses = []
    page.on("response", lambda r: responses.append((r.status, r.url)))
    page.goto(f"http://127.0.0.1:{PORT}/test-tldr-render.html", wait_until="networkidle")

    print("=== stylesheet requests ===")
    for st, u in responses:
        if "css" in u:
            print(f"  {st}  {u}")

    print("\n=== is the stylesheet applied? ===")
    print("  sheets:", page.evaluate("document.styleSheets.length"))
    print("  body font-family:", page.evaluate("getComputedStyle(document.body).fontFamily")[:60])
    print("  body font-size:", page.evaluate("getComputedStyle(document.body).fontSize"))
    print("  .post-card padding:", page.evaluate(
        "getComputedStyle(document.querySelector('.post-card')).padding"))
    print("  .content-grid cols:", page.evaluate(
        "getComputedStyle(document.querySelector('.content-grid')).gridTemplateColumns"))
    print("  .cluster-grid cols:", page.evaluate(
        "getComputedStyle(document.querySelector('.cluster-grid')).gridTemplateColumns"))

    print("\n=== widest elements (top 15) ===")
    rows = page.evaluate("""
      () => {
        const out = [];
        for (const el of document.querySelectorAll('body *')) {
          const r = el.getBoundingClientRect();
          if (r.width < 400) continue;
          const cls = (typeof el.className === 'string' ? el.className : '')
            .trim().split(/\\s+/).slice(0,3).join('.');
          out.push({t: el.tagName.toLowerCase(), c: cls, w: Math.round(r.width),
                    x: Math.round(r.x)});
        }
        out.sort((a,b) => b.w - a.w);
        const seen = new Set();
        return out.filter(o => {
          const k = o.t + o.c + o.w; if (seen.has(k)) return false; seen.add(k); return true;
        }).slice(0, 15);
      }
    """)
    for r in rows:
        print(f"  {r['w']:6d}px  x={r['x']:6d}  {r['t']}.{r['c']}")

    ctx.close()
    b.close()

httpd.shutdown()
