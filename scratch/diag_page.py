"""Generic overflow diagnostician: which elements overflow, and why."""
import functools, http.server, socketserver, sys, threading
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
LOOKBOOKS = ROOT / "data" / "lookbooks"
PORT = 8796
PAGE = sys.argv[1] if len(sys.argv) > 1 else "index.html"
WIDTH = int(sys.argv[2]) if len(sys.argv) > 2 else 320


class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


handler = functools.partial(Q, directory=str(LOOKBOOKS))
socketserver.TCPServer.allow_reuse_address = True
httpd = socketserver.TCPServer(("127.0.0.1", PORT), handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

with sync_playwright() as pw:
    b = pw.chromium.launch()
    ctx = b.new_context(viewport={"width": WIDTH, "height": 800}, is_mobile=True, has_touch=True)
    page = ctx.new_page()
    page.goto(f"http://127.0.0.1:{PORT}/{PAGE}", wait_until="networkidle")

    print(f"=== {PAGE} @ {WIDTH}px : overflowing elements ===")
    rows = page.evaluate("""
      (vw) => {
        const out = [];
        for (const el of document.querySelectorAll('body *')) {
          const r = el.getBoundingClientRect();
          if (r.width === 0 || r.height === 0) continue;
          if (getComputedStyle(el).position === 'fixed') continue;
          if (r.right > vw + 1) {
            const cs = getComputedStyle(el);
            const cls = (typeof el.className === 'string' ? el.className : '')
              .trim().split(/\\s+/).slice(0,3).join('.');
            out.push({t: el.tagName.toLowerCase(), c: cls,
                      right: Math.round(r.right), w: Math.round(r.width),
                      over: Math.round(r.right - vw),
                      txt: (el.textContent||'').trim().replace(/\\s+/g,' ').slice(0,45)});
          }
        }
        out.sort((a,b)=>b.over-a.over);
        const seen=new Set();
        return out.filter(o=>{const k=o.t+o.c+o.over; if(seen.has(k))return false;seen.add(k);return true;}).slice(0,14);
      }
    """, WIDTH)
    for r in rows:
        print(f"  over={r['over']:5d}px w={r['w']:5d} right={r['right']:5d}  "
              f"{r['t']}.{r['c']}  | {r['txt']}")

    print("\n=== smallest tap targets ===")
    taps = page.evaluate("""
      () => {
        const out=[];
        for (const el of document.querySelectorAll('a,button,summary,[onclick]')) {
          const r=el.getBoundingClientRect();
          if(r.width===0||r.height===0) continue;
          if(r.height<44||r.width<44){
            const cls=(typeof el.className==='string'?el.className:'').trim().split(/\\s+/).slice(0,2).join('.');
            out.push({t:el.tagName.toLowerCase(),c:cls,w:Math.round(r.width),h:Math.round(r.height),
                      txt:(el.textContent||'').trim().replace(/\\s+/g,' ').slice(0,30)});
          }
        }
        const seen=new Set();
        return out.filter(o=>{const k=o.t+o.c+o.w+o.h;if(seen.has(k))return false;seen.add(k);return true;}).slice(0,14);
      }
    """)
    for t in taps:
        print(f"  {t['w']:4d}x{t['h']:3d}  {t['t']}.{t['c']}  | {t['txt']}")

    ctx.close()
    b.close()

httpd.shutdown()
