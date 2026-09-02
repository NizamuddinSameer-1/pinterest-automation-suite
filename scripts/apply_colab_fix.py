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

async def apply_fix():
    print("🚀 Connecting to Colab to update cell...")
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(NOTEBOOK_URL, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(6)
        
        # Search all Monaco models and replace the code cell
        res = await page.evaluate("""(code) => {
            const models = window.monaco ? window.monaco.editor.getModels() : [];
            let updated = [];
            for (let i = 0; i < models.length; i++) {
                const val = models[i].getValue();
                if (val.includes('basicsr') || val.includes('Install dependencies') || val.includes('realesrgan')) {
                    // Use pushEditOperations so Monaco registers the edit and notifies Colab
                    const range = models[i].getFullModelRange();
                    models[i].pushEditOperations([], [{ range: range, text: code }], () => null);
                    updated.push({ index: i, uri: models[i].uri.toString() });
                }
            }
            return updated;
        }""", NEW_CODE)
        
        print("Model update results:", res)
        await asyncio.sleep(1)
        
        # Focus and save notebook
        print("💾 Pressing Control+S to save to Google Drive...")
        await page.keyboard.press("Control+S")
        await asyncio.sleep(4)
        
        # Verify
        check = await page.evaluate("""() => {
            const models = window.monaco ? window.monaco.editor.getModels() : [];
            return models.map((m, idx) => ({ idx, text: m.getValue().slice(0, 150) }));
        }""")
        print("Current models after save:")
        for c in check:
            print(f"[{c['idx']}]: {c['text'].strip()}")
            
        await page.screenshot(path="data/colab_fixed_verified.png")
        print("📸 Saved verification screenshot to data/colab_fixed_verified.png")
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(apply_fix())
