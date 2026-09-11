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
            if method != "POST":
                return

            # Skip telemetry / analytics / logging endpoints that may send compressed binary payloads
            skip_endpoints = [
                "batchLogFrontendEvents",
                "fetchUserRecommendations",
                "checkAppAvailability",
                "play.google.com",
                "google-analytics",
                "stats",
                "telemetry",
            ]
            if any(skip in url for skip in skip_endpoints):
                return

            # Safely extract post_data (prevents UnicodeDecodeError on gzip/protobuf payloads)
            try:
                post_data = request.post_data
            except Exception:
                post_data = None

            if not post_data:
                return

            # Target Google image generation endpoints (ImageFX / Vertex / Gemini / Labs endpoints)
            is_gen_endpoint = any(kw in url for kw in [
                "runImageFx",
                "batchGenerateImages",
                "generateImages",
                "generateImage",
                ":generate",
                "predict",
                "image-fx",
                "flowMedia",
                "imagen",
            ])

            has_prompt_payload = any(kw in post_data.lower() for kw in ["prompt", "userinput", "contents", "instances"])

            if is_gen_endpoint or has_prompt_payload:
                try:
                    headers = await request.all_headers()
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

            url = response.url
            if any(skip in url for skip in ["batchLogFrontendEvents", "fetchUserRecommendations", "checkAppAvailability", "telemetry"]):
                return

            req = response.request
            if req.method == "POST" and response.status == 200:
                try:
                    content_type = response.headers.get("content-type", "")
                    if "application/json" in content_type:
                        res_json = await response.json()
                        res_text = json.dumps(res_json)
                        # Check if response contains image markers
                        if any(marker in res_text for marker in ["image", "encodedImage", "inlineData", "bytesBase64Encoded", "imageUri", "media"]):
                            if "url" not in captured_session:
                                try:
                                    headers = await req.all_headers()
                                    captured_session["url"] = req.url
                                    captured_session["method"] = req.method
                                    captured_session["headers"] = {
                                        k: v for k, v in headers.items()
                                        if not k.startswith(":")
                                        and k.lower() not in ["content-length", "host", "connection", "accept-encoding"]
                                    }
                                    captured_session["captured_at"] = time.time()
                                    try:
                                        p_data = req.post_data
                                        captured_session["json_payload"] = json.loads(p_data) if p_data else {}
                                    except Exception:
                                        captured_session["raw_payload"] = req.post_data
                                except Exception:
                                    pass
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
            # Wait up to 15 minutes for generation
            await asyncio.wait_for(captured_event.wait(), timeout=900.0)
        except asyncio.TimeoutError:
            print("\n[TIMEOUT] Generation was not triggered within 15 minutes.")

        if "url" in captured_session:
            SESSION_FILE.write_text(json.dumps(captured_session, indent=2), encoding="utf-8")
            print("\n" + "=" * 70)
            print("🎉 Captured Google Flow request saved to:")
            print(f"📁 {SESSION_FILE}")
            print("=" * 70)
            print("✅ Google Flow session and API tokens successfully captured!")
            print("🖼️  The browser is staying open so your image can finish generating and rendering.")
            print("👉 You can admire your generated image in the browser window.")
            print("👉 When you are done, press [ENTER] in this terminal or simply close the browser.")
            print("=" * 70)

            # Keep the browser open until the user presses ENTER or closes the window
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, input, "\nPress ENTER when you are done to close the browser...")
            except Exception:
                await asyncio.sleep(45)
        else:
            print("\n[WARN] No generation request was captured. Please try again.")
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, input, "\nPress ENTER to close the browser...")
            except Exception:
                await asyncio.sleep(15)

        try:
            await browser_context.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
