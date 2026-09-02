"""
Pinterest Realism Engine — Google Flow (ImageFX) Network Interceptor & Session Capturer.

Launches a browser window, lets you log in and generate 1 image manually.
Automatically intercepts the exact underlying Google Image generation API call (URL, headers, auth token, payload),
and saves it to data/captured_flow_session.json for direct UI-less replay in Python!
"""

import asyncio
import json
import re
import sys
import time
from pathlib import Path
from playwright.async_api import async_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA_DIR = Path("./data").resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
SESSION_FILE = DATA_DIR / "captured_flow_session.json"
PROFILE_DIR = DATA_DIR / "flow_profile"
PROFILE_DIR.mkdir(parents=True, exist_ok=True)

FLOW_URL = "https://labs.google/fx/tools/image-fx"


async def main():
    print("=" * 70)
    print("🎯 GOOGLE FLOW / IMAGE-FX DIRECT API CAPTURER")
    print("=" * 70)
    print("This script will open Google Flow in a browser window.")
    print("👉 1. Sign into your Google account (if prompted).")
    print("👉 2. Type any simple prompt (e.g., 'a cute cat in a garden') and click Generate.")
    print("👉 3. The interceptor will automatically grab the internal API call, auth token, and headers!")
    print("=" * 70)

    captured_session = {}
    captured_event = asyncio.Event()

    async with async_playwright() as p:
        browser_context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1280, "height": 850},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ],
        )

        page = browser_context.pages[0] if browser_context.pages else await browser_context.new_page()

        async def handle_request(request):
            if captured_event.is_set():
                return

            url = request.url
            method = request.method
            post_data = request.post_data

            # Target Google image generation endpoints (ImageFX / Vertex / Gemini / Labs endpoints)
            is_gen_endpoint = any(kw in url for kw in [
                "runImageFx",
                "aisandbox-pa.googleapis.com",
                "generativelanguage.googleapis.com",
                "generateImages",
                "predict",
                "image-fx",
                "labs.google/api",
                "imagen",
            ])

            if method == "POST" and post_data and (is_gen_endpoint or "prompt" in post_data.lower() or "userinput" in post_data.lower() or "contents" in post_data.lower()):
                try:
                    headers = await request.all_headers()
                    # Chrome talks HTTP/2, so Playwright reports the request line
                    # as the pseudo-headers :authority/:method/:path/:scheme.
                    # httpx replays over HTTP/1.1 and h11 rejects any name that
                    # starts with ':' — writing them into the capture is what
                    # produced `Illegal header name b':authority'` on every
                    # replay. They duplicate the URL, so drop them here too and
                    # not only at replay time.
                    clean_headers = {
                        k: v for k, v in headers.items()
                        if not k.startswith(":")
                        and k.lower() not in ["content-length", "host", "connection", "accept-encoding"]
                    }

                    captured_session["url"] = url
                    captured_session["method"] = method
                    captured_session["headers"] = clean_headers
                    captured_session["captured_at"] = time.time()
                    try:
                        captured_session["json_payload"] = json.loads(post_data)
                    except Exception:
                        captured_session["raw_payload"] = post_data

                    print(f"\n[INTERCEPTED API REQUEST] -> {url[:80]}...")
                except Exception as e:
                    print(f"Notice during capture: {e}")

        async def handle_response(response):
            if captured_event.is_set():
                return

            req = response.request
            url = response.url

            is_gen_endpoint = any(kw in url for kw in [
                "runImageFx",
                "aisandbox-pa.googleapis.com",
                "generativelanguage.googleapis.com",
                "generateImages",
                "predict",
                "image-fx",
                "labs.google/api",
                "imagen",
            ])

            if req.method == "POST" and (is_gen_endpoint or "captured_session" in locals()):
                try:
                    if response.status == 200:
                        content_type = response.headers.get("content-type", "")
                        if "application/json" in content_type:
                            res_json = await response.json()
                            res_text = json.dumps(res_json)
                            # Check if response contains image markers
                            if any(marker in res_text for marker in ["image", "encodedImage", "inlineData", "bytesBase64Encoded", "imageUri", "media"]):
                                captured_session["sample_response_keys"] = list(res_json.keys()) if isinstance(res_json, dict) else []
                                if "url" in captured_session:
                                    captured_event.set()
                                    print("\n[SUCCESS] Captured complete request + successful image response payload!")
                except Exception:
                    pass

        page.on("request", handle_request)
        page.on("response", handle_response)

        print("\nOpening Google Flow in browser...")
        await page.goto(FLOW_URL, timeout=60000)

        print("\nWaiting for you to generate an image in Google Flow...")
        try:
            # Wait up to 5 minutes for generation
            await asyncio.wait_for(captured_event.wait(), timeout=300.0)
        except asyncio.TimeoutError:
            print("\n[TIMEOUT] Generation was not triggered within 5 minutes.")

        if "url" in captured_session:
            SESSION_FILE.write_text(json.dumps(captured_session, indent=2), encoding="utf-8")
            print("\n" + "=" * 70)
            print("🎉 Captured Google Flow request saved to:")
            print(f"📁 {SESSION_FILE}")
            print("=" * 70)
            print("⏳ This capture is SHORT-LIVED. It carries a Google OAuth token")
            print("   (~1 hour) and a reCAPTCHA token that is effectively single-use,")
            print("   and neither can be refreshed without a browser. The flow_api")
            print("   backend refuses a capture older than 15 minutes rather than")
            print("   spending a 90-second request on a rejection.")
            print("   For repeatable generation use the flow_ui backend, which signs in")
            print("   from data/flow_profile and does not expire.")
        else:
            print("\n[WARN] No generation request was captured. Please try again.")

        await asyncio.sleep(2)
        await browser_context.close()


if __name__ == "__main__":
    asyncio.run(main())
