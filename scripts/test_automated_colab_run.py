import asyncio
import os
import sys
import time
import re
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright

NOTEBOOK_URL = "https://colab.research.google.com/drive/1TgdpXgPBQ7pKlYO50PsuSX8RcRyu7y9U#scrollTo=HLsprCUNt-MT"
PROFILE_DIR = Path("./data/colab_profile").resolve()

async def test_auto_run():
    print("🚀 [TEST] Launching Colab automation...")
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=True,
            viewport={"width": 1280, "height": 850},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        print(f"📄 Navigating to: {NOTEBOOK_URL}")
        await page.goto(NOTEBOOK_URL, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(5)
        
        # Dismiss any popups
        for sel in ['button:has-text("Run anyway")', 'mwc-button:has-text("Run anyway")', 'button:has-text("OK")']:
            try:
                b = page.locator(sel).first
                if await b.count() > 0 and await b.is_visible():
                    await b.click()
                    print(f"Dismissed popup: {sel}")
            except Exception:
                pass
                
        # Trigger Run via Runtime -> Run all
        print("▶️ Triggering Run via Runtime menu...")
        ran = False
        try:
            runtime_menu = page.locator('div[id="runtime-menu-button"], div:text-is("Runtime")').first
            if await runtime_menu.count() > 0:
                await runtime_menu.click()
                await asyncio.sleep(0.8)
                run_all_item = page.locator('div:has-text("Run all"), [command="runall"]').first
                if await run_all_item.count() > 0:
                    await run_all_item.click()
                    print("✅ Clicked Runtime -> Run all successfully!")
                    ran = True
        except Exception as e:
            print(f"Notice menu run all: {e}")
            
        if not ran:
            print("⌨️ Trying Control+F9 shortcut...")
            await page.keyboard.press("Control+F9")
            await asyncio.sleep(1)
            
        # Also check cell run button directly inside colab-cell
        try:
            cell_run = page.locator('colab-cell colab-run-button, .cell.code colab-run-button').first
            if await cell_run.count() > 0 and await cell_run.is_visible():
                await cell_run.click()
                print("✅ Clicked colab-cell run button!")
        except Exception as e:
            print(f"Notice cell run button: {e}")
            
        # Dismiss warning if it appeared after run
        await asyncio.sleep(2)
        for sel in ['button:has-text("Run anyway")', 'mwc-button:has-text("Run anyway")']:
            try:
                b = page.locator(sel).first
                if await b.count() > 0 and await b.is_visible():
                    await b.click()
                    print(f"Dismissed run warning: {sel}")
            except Exception:
                pass

        # Monitor output for live execution
        print("⏳ Waiting for packages to install & Cloudflare tunnel to start...")
        start_time = time.time()
        tunnel_url = None
        
        while time.time() - start_time < 120:
            outputs = await page.locator('.output, .stream, colab-output-renderer').all_inner_texts()
            full_text = " ".join(outputs)
            
            # Look for progress keywords
            if "[1/4]" in full_text:
                print("   ⚡ [Colab Progress]: Installing FastAPI, Uvicorn & Spandrel...")
            if "[2/4]" in full_text:
                print("   ⚡ [Colab Progress]: Setting up Cloudflare tunnel...")
            if "[3/4]" in full_text:
                print("   ⚡ [Colab Progress]: Downloading AI model weights...")
            if "[4/4]" in full_text:
                print("   ⚡ [Colab Progress]: Starting Cloudflare tunnel...")
                
            m = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", full_text)
            if m:
                tunnel_url = m.group(0)
                print(f"\n🎉 SUCCESS! Tunnel is active: {tunnel_url}")
                break
                
            await asyncio.sleep(5)
            
        await page.screenshot(path="data/colab_auto_run_result.png")
        print("📸 Saved result screenshot to data/colab_auto_run_result.png")
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(test_auto_run())
