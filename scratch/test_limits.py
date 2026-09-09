import asyncio
import json
import sys
sys.path.insert(0, ".")
from playwright.async_api import async_playwright
from app.services.pinterest_profiles import get_profile_dir

async def test_limits():
    pdir = get_profile_dir("profile_2")
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(pdir),
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto("https://trends.pinterest.com/", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(1)

        term = "fall nail colors 2026"
        for lim in [1, 3, 5, 10]:
            script = f"""async () => {{
                const cookies = document.cookie.split('; ');
                const csrfCookie = cookies.find(c => c.startsWith('csrftoken='));
                const csrf = csrfCookie ? csrfCookie.split('=')[1] : '';
                const payload = {{
                    terms: [{json.dumps(term)}],
                    country: 'US',
                    cacheTtlInSeconds: 86400,
                    limit: {lim},
                    batchSize: 20,
                    requestImageSize: '75x75'
                }};
                try {{
                    const r = await fetch('/term_images/', {{
                        method: 'POST',
                        headers: {{ 'content-type': 'application/json', 'x-csrftoken': csrf }},
                        body: JSON.stringify(payload)
                    }});
                    return {{ status: r.status, data: await r.json() }};
                }} catch (e) {{
                    return {{ error: e.toString() }};
                }}
            }}"""
            res = await page.evaluate(script)
            images = res.get("data", {}).get(term, []) if isinstance(res.get("data"), dict) else []
            print(f"limit={lim}: status={res.get('status')}, count={len(images)}")
            for img in images:
                print("   ", img)
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(test_limits())
