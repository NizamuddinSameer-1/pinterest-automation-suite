import asyncio
import os
import re
import sys
from pathlib import Path
from playwright.async_api import async_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

NOTEBOOK_URL = "https://colab.research.google.com/drive/1TgdpXgPBQ7pKlYO50PsuSX8RcRyu7y9U"
FLOW_PROFILE = Path("./data/flow_profile").resolve()
CODE_PATH = Path("./scripts/colab_upscaler/colab_notebook_code.py").resolve()
NEW_CODE = CODE_PATH.read_text(encoding="utf-8")
TUNNEL_CACHE = Path("./data/colab_tunnel.txt").resolve()
ENV_FILE = Path("./.env").resolve()


def update_env(tunnel_url: str):
    if not ENV_FILE.exists():
        return
    text = ENV_FILE.read_text(encoding="utf-8")
    if "COLAB_UPSCALER_URL=" in text:
        text = re.sub(r"COLAB_UPSCALER_URL=.*", f"COLAB_UPSCALER_URL={tunnel_url}", text)
    else:
        text += f"\nCOLAB_UPSCALER_URL={tunnel_url}\n"
    ENV_FILE.write_text(text, encoding="utf-8")
    print(f"📝 [AUTO UPDATE] Updated .env with COLAB_UPSCALER_URL={tunnel_url}")


async def auto_update():
    print("🚀 [AUTO UPDATE] Launching Colab with active Google session...")
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(FLOW_PROFILE),
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(NOTEBOOK_URL, timeout=60000)
        await asyncio.sleep(6)

        print("🔍 [AUTO UPDATE] Checking Monaco code models in Colab...")
        updated = await page.evaluate("""(code) => {
            const models = window.monaco ? window.monaco.editor.getModels() : [];
            let count = 0;
            for (let i = 0; i < models.length; i++) {
                const val = models[i].getValue();
                if (val.includes('PINTEREST REALISM ENGINE') || val.includes('Real-ESRGAN') || val.includes('UltraSharp') || val.includes('basicsr') || val.includes('cloudflared')) {
                    const range = models[i].getFullModelRange();
                    models[i].pushEditOperations([], [{ range: range, text: code }], () => null);
                    count++;
                }
            }
            return count;
        }""", NEW_CODE)

        print(f"✅ [AUTO UPDATE] Replaced {updated} code cell(s) with 2K 4x-UltraSharp Tiled code!")
        await asyncio.sleep(2)

        # Save to Google Drive
        print("💾 [AUTO UPDATE] Saving notebook...")
        await page.keyboard.press("Control+S")
        await asyncio.sleep(2)

        # Run all cells in Colab via standard shortcut Control+F9
        print("▶️ [AUTO UPDATE] Pressing Control+F9 to execute notebook...")
        await page.keyboard.press("Control+F9")
        await asyncio.sleep(2)

        # Check for Google author warning dialog ("Run anyway")
        try:
            warning_btn = page.locator("mwc-button:has-text('Run anyway'), paper-button:has-text('Run anyway'), button:has-text('Run anyway')")
            if await warning_btn.count() > 0:
                await warning_btn.first.click()
                print("👉 Clicked 'Run anyway' dialog!")
        except Exception:
            pass

        # Monitor output for the Cloudflare URL
        print("⏳ [AUTO UPDATE] Waiting for 4x-UltraSharp setup and Cloudflare tunnel (up to 90s)...")
        tunnel_url = None
        for sec in range(90):
            await asyncio.sleep(1)
            content = await page.content()
            match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", content)
            if match:
                tunnel_url = match.group(0)
                print(f"\n🎉 [AUTO UPDATE] Tunnel URL extracted: {tunnel_url}")
                break
            if sec % 10 == 0 and sec > 0:
                print(f"   Still initializing... ({sec}s elapsed)")

        if tunnel_url:
            TUNNEL_CACHE.write_text(tunnel_url, encoding="utf-8")
            update_env(tunnel_url)
            print("✅ [AUTO UPDATE] Successfully fully automated Colab! 2K UGC engine is 100% active.")
        else:
            print("⚠️ [AUTO UPDATE] Could not extract tunnel URL within 90s, check screenshot.")

        await page.screenshot(path="data/colab_auto_update_result.png")
        print("📸 Screenshot saved to data/colab_auto_update_result.png")
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(auto_update())
