import asyncio
import json
import sys
sys.path.insert(0, ".")
from playwright.async_api import async_playwright
from app.services.pinterest_profiles import get_profile_dir

async def test_detail():
    pdir = get_profile_dir("profile_2")
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(pdir),
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        
        page.on("request", lambda r: print("REQ:", r.method, r.url[:120]) if not any(x in r.url for x in [".mjs", ".css", ".woff", "csp_report", "storage_report"]) else None)

        # Direct navigation to trend URL if Pinterest trends has a specific URL pattern
        print("Navigating to trends.pinterest.com...")
        await page.goto("https://trends.pinterest.com/", wait_until="networkidle")
        await asyncio.sleep(2)

        # Look for search input
        inputs = await page.locator("input").all()
        print(f"Found {len(inputs)} input elements")
        for i, inp in enumerate(inputs):
            placeholder = await inp.get_attribute("placeholder") or ""
            print(f"Input {i}: placeholder='{placeholder}'")
            if "search" in placeholder.lower() or "trend" in placeholder.lower():
                await inp.fill("fall nail colors")
                await asyncio.sleep(1)
                await page.keyboard.press("Enter")
                await asyncio.sleep(4)
                break

        print("Current URL:", page.url)
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(test_detail())
