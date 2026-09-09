import asyncio
import json
import sys
sys.path.insert(0, ".")
from playwright.async_api import async_playwright
from app.services.pinterest_profiles import get_profile_dir

async def test():
    term = "fall nail colors 2026"
    terms_to_query = [term, "fall nail colors", "autumn nails", "fall nails"]
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

        payload_json = json.dumps({
            "terms": terms_to_query,
            "country": "US",
            "cacheTtlInSeconds": 86400,
            "limit": 5,
            "batchSize": 20,
            "requestImageSize": "75x75"
        })

        script = f"""async () => {{
            const cookies = document.cookie.split('; ');
            const csrfCookie = cookies.find(c => c.startsWith('csrftoken='));
            const csrf = csrfCookie ? csrfCookie.split('=')[1] : '';
            const payload = {payload_json};
            try {{
                const r = await fetch('/term_images/', {{
                    method: 'POST',
                    headers: {{
                        'content-type': 'application/json',
                        'x-csrftoken': csrf
                    }},
                    body: JSON.stringify(payload)
                }});
                return {{ status: r.status, data: await r.json() }};
            }} catch (e) {{
                return {{ error: e.toString() }};
            }}
        }}"""

        res = await page.evaluate(script)
        print("Status:", res.get("status"))
        data = res.get("data", {})
        total_imgs = 0
        for k, v in data.items():
            print(f"Term '{k}': {len(v)} images")
            for img in v:
                total_imgs += 1
                high_res = img.replace("/75x75/", "/736x/")
                print("   ->", high_res)
        print("Total official trend images gathered:", total_imgs)
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(test())
