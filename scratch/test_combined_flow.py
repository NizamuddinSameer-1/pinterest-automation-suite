import asyncio
import json
import sys
import urllib.parse
from typing import Any
sys.path.insert(0, ".")

from app.services.pinterest_profiles import get_profile_dir
from app.services.browser_utils import clean_stale_locks
from playwright.async_api import async_playwright

async def test_combined():
    clean_term = "fall nail colors 2026"
    related_terms = ["fall nail colors", "autumn nails", "fall nails 2026 trends"]
    country = "US"
    count = 10

    query_terms = [clean_term] + [t for t in related_terms if t.lower() != clean_term.lower()][:4]
    encoded_term = urllib.parse.quote_plus(clean_term)

    raw_pins: list[dict[str, Any]] = []
    _TERM_IMGS_PROFILES = ["profile_2", "default"]

    # 1. Strategy 1: trends.pinterest.com /term_images/ with POST
    for _pid in _TERM_IMGS_PROFILES:
        if raw_pins:
            break
        try:
            profile_dir = get_profile_dir(_pid)
            clean_stale_locks(profile_dir)
            async with async_playwright() as p:
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                )
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto("https://trends.pinterest.com/", wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(1.0)

                payload_json = json.dumps({
                    "terms": query_terms,
                    "country": country,
                    "cacheTtlInSeconds": 86400,
                    "limit": 5,
                    "batchSize": 20,
                    "requestImageSize": "75x75"
                })

                script = f"""async () => {{
                    try {{
                        const cookies = document.cookie.split('; ');
                        const csrfCookie = cookies.find(c => c.startsWith('csrftoken='));
                        const csrf = csrfCookie ? csrfCookie.split('=')[1] : '';
                        const r = await fetch('/term_images/', {{
                            method: 'POST',
                            headers: {{
                                'content-type': 'application/json',
                                'x-csrftoken': csrf
                            }},
                            body: JSON.stringify({payload_json})
                        }});
                        if (r.status !== 200) return {{ status: r.status, data: {{}} }};
                        return {{ status: 200, data: await r.json() }};
                    }} catch (e) {{
                        return {{ status: 500, error: e.toString(), data: {{}} }};
                    }}
                }}"""
                res = await page.evaluate(script)
                img_data = res.get("data", {}) if isinstance(res.get("data"), dict) else {}
                print(f"Profile {_pid} /term_images/ status: {res.get('status')}, returned terms: {list(img_data.keys())}")

                for term_key, url_list in img_data.items():
                    if not isinstance(url_list, list):
                        continue
                    for idx, img_url in enumerate(url_list):
                        if not isinstance(img_url, str) or "i.pinimg.com" not in img_url:
                            continue
                        high_res = (
                            img_url.replace("/75x75/", "/736x/")
                            .replace("/236x/", "/736x/")
                            .replace("/474x/", "/736x/")
                        )
                        raw_pins.append({
                            "pin_id": f"trend_{abs(hash(high_res)) % 1_000_000}",
                            "title": f"{term_key.title()} — Trending Idea #{idx+1}",
                            "description": "",
                            "image_url": high_res,
                            "pin_url": f"https://www.pinterest.com/search/pins/?q={urllib.parse.quote_plus(term_key)}",
                            "_source": "trends_term_images",
                        })

                await context.close()
        except Exception as err:
            print(f"Profile {_pid} failed: {err}")

    # Fallback to unauthenticated browser if profiles failed
    if not raw_pins:
        print("Trying unauthenticated browser context for /term_images/...")
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
                page = await browser.new_page()
                await page.goto("https://trends.pinterest.com/", wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(1.0)
                payload_json = json.dumps({
                    "terms": query_terms,
                    "country": country,
                    "cacheTtlInSeconds": 86400,
                    "limit": 5,
                    "batchSize": 20,
                    "requestImageSize": "75x75"
                })
                script = f"""async () => {{
                    try {{
                        const cookies = document.cookie.split('; ');
                        const csrfCookie = cookies.find(c => c.startsWith('csrftoken='));
                        const csrf = csrfCookie ? csrfCookie.split('=')[1] : '';
                        const r = await fetch('/term_images/', {{
                            method: 'POST',
                            headers: {{ 'content-type': 'application/json', 'x-csrftoken': csrf }},
                            body: JSON.stringify({payload_json})
                        }});
                        if (r.status !== 200) return {{ status: r.status, data: {{}} }};
                        return {{ status: 200, data: await r.json() }};
                    }} catch (e) {{
                        return {{ status: 500, data: {{}} }};
                    }}
                }}"""
                res = await page.evaluate(script)
                img_data = res.get("data", {}) if isinstance(res.get("data"), dict) else {}
                for term_key, url_list in img_data.items():
                    if isinstance(url_list, list):
                        for idx, img_url in enumerate(url_list):
                            if isinstance(img_url, str) and "i.pinimg.com" in img_url:
                                high_res = img_url.replace("/75x75/", "/736x/").replace("/236x/", "/736x/")
                                raw_pins.append({
                                    "pin_id": f"trend_{abs(hash(high_res)) % 1_000_000}",
                                    "title": f"{term_key.title()} — Trending Inspo",
                                    "description": "",
                                    "image_url": high_res,
                                    "pin_url": f"https://www.pinterest.com/search/pins/?q={urllib.parse.quote_plus(term_key)}",
                                    "_source": "trends_term_images",
                                })
                await browser.close()
        except Exception as e:
            print("Unauth /term_images/ error:", e)

    print(f"Total pins retrieved: {len(raw_pins)}")
    for i, p in enumerate(raw_pins[:6]):
        print(f" [{i+1}] {p['_source']} | {p['title']}")
        print(f"     img: {p['image_url']}")

if __name__ == "__main__":
    asyncio.run(test_combined())
