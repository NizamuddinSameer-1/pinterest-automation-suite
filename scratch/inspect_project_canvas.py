import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

PROFILE_DIR = Path("./data/flow_profile").resolve()
URL = "https://labs.google/fx/tools/flow/project/b77512e8-1520-4bd1-b517-32a21b0e5c16"

async def inspect():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=True,
            viewport={"width": 1280, "height": 850},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        print(f"Navigating to {URL}...")
        await page.goto(URL, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(8)

        imgs = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('img')).map(i => ({
                src: i.src,
                currentSrc: i.currentSrc,
                width: i.naturalWidth || i.width,
                height: i.naturalHeight || i.height,
                classes: i.className,
                alt: i.alt
            }));
        }""")

        print(f"Found {len(imgs)} img elements.")
        flow_imgs = []
        for idx, img in enumerate(imgs):
            src = img.get("src") or img.get("currentSrc") or ""
            if "flow-content" in src or "/asb/" in src:
                print(f"Image #{idx}: {src}")
                flow_imgs.append(src)

        # Test downloading the latest flow image using page.request and urllib
        if flow_imgs:
            latest = flow_imgs[-1]
            print(f"\nTesting fetch of latest image:\n{latest}")
            
            # 1. page.request.get
            try:
                resp = await page.request.get(latest)
                print(f"page.request.get status: {resp.status}, length: {len(await resp.body()) if resp.status == 200 else 0}")
            except Exception as e:
                print(f"page.request.get error: {e}")

            # 2. urllib
            try:
                import urllib.request
                req = urllib.request.Request(latest, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as u_resp:
                    print(f"urllib status: {u_resp.status}, length: {len(u_resp.read())}")
            except Exception as e:
                print(f"urllib error: {e}")

        await ctx.close()

if __name__ == "__main__":
    asyncio.run(inspect())
