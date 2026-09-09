"""Quick test of raw /term_images/ API response to see key format."""
import asyncio
import json
import sys
sys.path.insert(0, ".")


async def test():
    from playwright.async_api import async_playwright

    term = "fall nail colors 2026"
    import urllib.parse
    encoded = urllib.parse.quote_plus(term)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            locale="en-US",
        )
        page = await ctx.new_page()
        print("Loading trends.pinterest.com...")
        await page.goto("https://trends.pinterest.com/", wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(2)

        encoded_space = urllib.parse.quote(term)     # %20 spaces
        encoded_plus  = urllib.parse.quote_plus(term) # + spaces

        for enc_style, enc_val in [("quote", encoded_space), ("quote_plus", encoded_plus)]:
            result = await page.evaluate(f"""
                async () => {{
                    try {{
                        const r = await fetch('/term_images/?terms={enc_val}');
                        const data = await r.json();
                        return {{ status: r.status, keys: Object.keys(data), raw: data }};
                    }} catch(e) {{
                        return {{ error: e.toString() }};
                    }}
                }}
            """)
            print(f"Style={enc_style} ({enc_val!r}): status={result.get('status')} keys={result.get('keys')}")
            if result.get("keys"):
                raw = result.get("raw", {})
                for key, val in raw.items():
                    print(f"  Key in response: {key!r}")
                    if isinstance(val, list) and val:
                        first = val[0]
                        if isinstance(first, dict):
                            imgs = first.get("images", {})
                            print(f"  images keys: {list(imgs.keys())}")
                            best = imgs.get("orig") or imgs.get("736x") or imgs.get("474x")
                            print(f"  Sample image: {best}")
                            print(f"  Total pins: {len(val)}")
                break
        await browser.close()


if __name__ == "__main__":
    asyncio.run(test())
