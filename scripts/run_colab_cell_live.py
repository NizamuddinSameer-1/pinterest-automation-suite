import asyncio
import os
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright

NOTEBOOK_URL = "https://colab.research.google.com/drive/1TgdpXgPBQ7pKlYO50PsuSX8RcRyu7y9U#scrollTo=HLsprCUNt-MT"
PROFILE_DIR = Path("./data/colab_profile").resolve()

async def run_colab_live():
    print("🚀 Connecting to Colab to clear old output & run new cell...")
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1280, "height": 850},
            args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(NOTEBOOK_URL, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(5)
        
        # 1. Clear old cell output
        print("🧹 Clearing old cell outputs...")
        try:
            # Click Edit menu -> Clear all outputs
            edit_menu = page.locator('div[id="edit-menu-button"], div:text-is("Edit")').first
            if await edit_menu.count() > 0:
                await edit_menu.click()
                await asyncio.sleep(0.5)
                clear_item = page.locator('div:has-text("Clear all outputs"), [command="clear-all-outputs"]').first
                if await clear_item.count() > 0:
                    await clear_item.click()
                    await asyncio.sleep(1)
                    # Confirm dialog if any
                    confirm_btn = page.locator('button:has-text("Clear"), button:has-text("Yes")').first
                    if await confirm_btn.count() > 0 and await confirm_btn.is_visible():
                        await confirm_btn.click()
                        await asyncio.sleep(1)
        except Exception as e:
            print(f"Notice clearing output: {e}")
            
        # 2. Check connection status / Connect button
        print("⚡ Checking GPU connection...")
        connect_btn = page.locator('colab-connect-button, div[id*="connect"], button:has-text("Connect")').first
        if await connect_btn.count() > 0:
            text = await connect_btn.inner_text()
            print(f"Connect button text: {text}")
            if "Connect" in text:
                print("Clicking Connect...")
                await connect_btn.click()
                await asyncio.sleep(3)
                
        # 3. Click Play / Run cell
        print("▶️ Triggering cell execution...")
        play_btn = page.locator('colab-run-button, [aria-label*="Run cell" i], [aria-label*="Execute" i]').first
        if await play_btn.count() > 0:
            await play_btn.click()
            print("Clicked play button!")
        else:
            await page.keyboard.press("Control+Enter")
            print("Pressed Control+Enter!")
            
        await asyncio.sleep(3)
        
        # Dismiss any Google author warning popup
        candidate_popups = ['button:has-text("Run anyway")', 'mwc-button:has-text("Run anyway")', 'button:has-text("OK")']
        for pop in candidate_popups:
            b = page.locator(pop).first
            if await b.count() > 0 and await b.is_visible():
                await b.click()
                print(f"Dismissed popup: {pop}")
                await asyncio.sleep(1)
                
        # 4. Monitor live cell output
        print("⏳ Waiting for new cell to install packages and start Cloudflare tunnel...")
        start_time = time.time()
        tunnel_found = None
        while time.time() - start_time < 90:
            outputs = await page.locator('.output, .stream, colab-output-renderer').all_inner_texts()
            full_text = " ".join(outputs)
            
            # Print any progress lines
            for line in full_text.split("\n")[-5:]:
                if line.strip() and not line.startswith("error"):
                    print(f"   [Colab Output]: {line.strip()[:100]}")
                    
            if "trycloudflare.com" in full_text:
                import re
                m = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", full_text)
                if m:
                    tunnel_found = m.group(0)
                    print(f"\n🎉 SUCCESS! Tunnel is active: {tunnel_found}")
                    break
                    
            await asyncio.sleep(4)
            
        await page.screenshot(path="data/colab_run_live.png")
        print("📸 Screenshot saved to data/colab_run_live.png")
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(run_colab_live())
