import asyncio
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright

NOTEBOOK_URL = "https://colab.research.google.com/drive/1TgdpXgPBQ7pKlYO50PsuSX8RcRyu7y9U#scrollTo=HLsprCUNt-MT"
PROFILE_DIR = Path("./data/colab_profile").resolve()

# Read the new code
code_file = Path("./scripts/colab_upscaler/colab_notebook_code.py").resolve()
NEW_CODE = code_file.read_text(encoding="utf-8")

async def update_cell():
    print("🚀 Launching Chrome to update official Colab notebook...")
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            viewport=None,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ],
            ignore_default_args=["--enable-automation"],
        )
        
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        print(f"📄 Navigating to notebook: {NOTEBOOK_URL}")
        await page.goto(NOTEBOOK_URL, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(5)
        
        # Look for code editor or Monaco editor
        print("🔍 Locating Monaco / Colab editor cell...")
        
        # Inject new code via Monaco API if accessible, or via keyboard
        updated = False
        try:
            res = await page.evaluate("""(code) => {
                // Try Colab's monaco editor models
                if (window.monaco && window.monaco.editor) {
                    const models = window.monaco.editor.getModels();
                    if (models && models.length > 0) {
                        models[0].setValue(code);
                        return { success: true, via: 'monaco.getModels()[0]' };
                    }
                }
                
                // Try active colab-editor or monaco element
                const ed = document.querySelector('colab-editor, .monaco-editor');
                if (ed && ed.monaco) {
                    ed.monaco.setValue(code);
                    return { success: true, via: 'ed.monaco' };
                }
                return { success: false };
            }""", NEW_CODE)
            
            if res.get("success"):
                print(f"✅ Cell code replaced via {res.get('via')}!")
                updated = True
        except Exception as e:
            print(f"Notice injecting via JS: {e}")
            
        if not updated:
            print("⌨️ Fallback: Clicking code editor and replacing via keyboard...")
            # Click on code cell editor line
            code_cell = page.locator('.view-line, colab-editor, .monaco-editor, .cell.code').first
            if await code_cell.count() > 0:
                await code_cell.click()
                await asyncio.sleep(0.5)
                # Select all and delete
                await page.keyboard.press("Control+A")
                await asyncio.sleep(0.3)
                await page.keyboard.press("Backspace")
                await asyncio.sleep(0.3)
                
                # Write to clipboard and paste
                await page.evaluate("""async (text) => {
                    await navigator.clipboard.writeText(text);
                }""", NEW_CODE)
                await asyncio.sleep(0.3)
                await page.keyboard.press("Control+V")
                await asyncio.sleep(1)
                print("✅ Pasted new code into code cell!")
                updated = True
                
        # Save notebook (Ctrl+S)
        print("💾 Saving notebook to Google Drive (Ctrl+S)...")
        await page.keyboard.press("Control+S")
        await asyncio.sleep(3)
        
        print("🎉 Official Colab notebook cell successfully updated!")
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(update_cell())
