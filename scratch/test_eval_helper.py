import asyncio
import json
import sys
sys.path.insert(0, ".")
from playwright.async_api import Page
from app.services.pinterest_profiles import get_profile_dir
from playwright.async_api import async_playwright

async def evaluate_term_images(page: Page, terms: list[str], country: str = "US", limit: int = 5) -> dict[str, list[str]]:
    """Helper to call POST /term_images/ on trends.pinterest.com."""
    payload_json = json.dumps({
        "terms": terms,
        "country": country,
        "cacheTtlInSeconds": 86400,
        "limit": min(limit, 5),
        "batchSize": 20,
        "requestImageSize": "75x75"
    })
    script = f"""async () => {{
        try {{
            const cookies = document.cookie.split('; ');
            const csrfCookie = cookies.find(c => c.startsWith('csrftoken='));
            const csrf = csrfCookie ? csrfCookie.split('=')[1] : '';
            const r = await fetch('/term_images/', {{
                method: 'POST',
                headers: {{
                    'content-type': 'application/json',
                    'x-csrftoken': csrf
                }},
                body: JSON.stringify({payload_json})
            }});
            if (r.status !== 200) return {{ status: r.status, data: {{}} }};
            return {{ status: 200, data: await r.json() }};
        }} catch (e) {{
            return {{ status: 500, error: e.toString(), data: {{}} }};
        }}
    }}"""
    res = await page.evaluate(script)
    raw_data = res.get("data", {}) if isinstance(res.get("data"), dict) else {}
    cleaned = {}
    for term, urls in raw_data.items():
        if isinstance(urls, list):
            cleaned[term] = [
                u.replace("/75x75/", "/736x/").replace("/236x/", "/736x/")
                for u in urls if isinstance(u, str) and "i.pinimg.com" in u
            ]
    return cleaned

async def test():
    pdir = get_profile_dir("profile_2")
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(str(pdir), headless=True, args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto("https://trends.pinterest.com/", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(1)
        res = await evaluate_term_images(page, ["fall nail colors 2026", "autumn outfits", "home decor"], limit=3)
        print("Success! Result:")
        for t, imgs in res.items():
            print(f"  {t}: {len(imgs)} imgs -> {imgs[0] if imgs else 'none'}")
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(test())
