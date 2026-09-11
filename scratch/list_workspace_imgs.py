import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir="data/flow_profile",
            headless=True
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(
            "https://labs.google/fx/tools/flow/project/b77512e8-1520-4bd1-b517-32a21b0e5c16",
            wait_until="domcontentloaded"
        )
        await asyncio.sleep(6)
        imgs = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('img'))
                .map((i, idx) => ({idx: idx, src: i.src, alt: i.alt}))
                .filter(o => o.src.includes('/asb/'));
        }""")
        print(f"Total ASB images: {len(imgs)}")
        for o in imgs:
            print(f"DOM Index {o['idx']}: {o['src'][:70]} | alt: {o['alt'][:50]}")
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(main())
