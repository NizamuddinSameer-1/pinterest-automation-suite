import asyncio
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright

NOTEBOOK_URL = "https://colab.research.google.com/drive/1TgdpXgPBQ7pKlYO50PsuSX8RcRyu7y9U#scrollTo=HLsprCUNt-MT"
PROFILE_DIR = Path("./data/colab_profile").resolve()

code_file = Path("./scripts/colab_upscaler/colab_notebook_code.py").resolve()
NEW_CODE = code_file.read_text(encoding="utf-8")

async def replace():
    print("🚀 Launching Chrome to replace cell contents...")
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=True,
            viewport={"width": 1280, "height": 800},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(NOTEBOOK_URL, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(5)
        
        # Click directly inside the code editor box
        print("🖱️ Clicking inside code cell at (300, 600)...")
        await page.mouse.click(300, 600)
        await asyncio.sleep(0.5)
        
        # Select all and delete
        print("⌨️ Selecting all and deleting old code...")
        await page.keyboard.press("Control+A")
        await asyncio.sleep(0.3)
        await page.keyboard.press("Backspace")
        await asyncio.sleep(0.5)
        
        # Write new code to clipboard and paste
        print("📋 Writing new code to clipboard & pasting via Ctrl+V...")
        await page.evaluate("""async (text) => {
            await navigator.clipboard.writeText(text);
        }""", NEW_CODE)
        await asyncio.sleep(0.3)
        await page.keyboard.press("Control+V")
        await asyncio.sleep(1.5)
        
        # Save notebook
        print("💾 Saving notebook to Google Drive (Control+S)...")
        await page.keyboard.press("Control+S")
        await asyncio.sleep(3)
        
        # Take screenshot to verify
        await page.screenshot(path="data/colab_after_replace.png")
        print("📸 Saved verification screenshot to data/colab_after_replace.png")
        
        # Read back editor text
        ed_text = await page.evaluate("""() => {
            const ed = document.querySelector('colab-editor, .monaco-editor');
            return ed ? (ed.innerText || ed.textContent).slice(0, 300) : '';
        }""")
        print("=== UPDATED CODE PREVIEW ===")
        print(ed_text)
        
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(replace())
