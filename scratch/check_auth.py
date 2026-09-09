import asyncio
import sys
sys.path.insert(0, ".")
from playwright.async_api import async_playwright
from app.services.pinterest_profiles import get_profile_dir

async def check():
    for pid in ["default", "profile_2"]:
        pdir = get_profile_dir(pid)
        print(f"=== Checking Profile: {pid} at {pdir} ===")
        try:
            async with async_playwright() as p:
                ctx = await p.chromium.launch_persistent_context(
                    str(pdir),
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
                )
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                await page.goto("https://www.pinterest.com/", wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(2)
                cookies = await ctx.cookies()
                auth_cookies = [c["name"] for c in cookies if "_auth" in c["name"] or "session" in c["name"] or "csrf" in c["name"]]
                has_auth = any(c["name"] == "_auth" and c["value"] == "1" for c in cookies)
                print(f"  URL: {page.url}")
                print(f"  Title: {await page.title()}")
                print(f"  Has _auth=1 cookie: {has_auth}")
                print(f"  Auth cookies: {auth_cookies}")
                await ctx.close()
        except Exception as e:
            print(f"  Error checking {pid}: {e}")

if __name__ == "__main__":
    asyncio.run(check())
