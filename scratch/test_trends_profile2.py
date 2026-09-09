import asyncio
import sys
sys.path.insert(0, ".")
from playwright.async_api import async_playwright
from app.services.pinterest_profiles import get_profile_dir

async def test_p2():
    pdir = get_profile_dir("profile_2")
    print(f"Testing profile_2 at {pdir}")
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(pdir),
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto("https://trends.pinterest.com/", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(2)
        print("trends page URL:", page.url)
        print("trends page title:", await page.title())

        # Test POST /term_images/
        res = await page.evaluate('''async () => {
            const cookies = document.cookie.split('; ');
            const csrfCookie = cookies.find(c => c.startsWith('csrftoken='));
            const csrf = csrfCookie ? csrfCookie.split('=')[1] : '';
            
            const payload = {
                terms: ['fall nail colors', 'fall nail colors 2026', 'casual blazer outfits'],
                country: 'US',
                cacheTtlInSeconds: 86400,
                limit: 1,
                batchSize: 20,
                requestImageSize: '75x75'
            };
            try {
                const r = await fetch('/term_images/', {
                    method: 'POST',
                    headers: {
                        'content-type': 'application/json',
                        'x-csrftoken': csrf
                    },
                    body: JSON.stringify(payload)
                });
                return { status: r.status, data: await r.json() };
            } catch (e) {
                return { error: e.toString() };
            }
        }''')
        print("POST /term_images/ result:", res)
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(test_p2())
