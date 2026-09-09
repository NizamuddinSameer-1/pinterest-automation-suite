"""Test the new term_images-based popular pins scraper."""
import asyncio
import sys
sys.path.insert(0, ".")


async def test():
    from app.services.pinterest_trends_scraper import get_trend_deep_dive

    print("=== Testing get_trend_deep_dive with new /term_images/ strategy ===")
    print("(This will hit trends.pinterest.com /term_images/ — ~30s timeout)\n")

    data = await get_trend_deep_dive("fall nail colors 2026", force_refresh=True)

    print(f"Term: {data['term']}")
    print(f"Popular pins returned: {len(data['popular_pins'])}")
    print()

    has_real = 0
    has_fallback = 0
    for i, p in enumerate(data["popular_pins"]):
        img = p["image_url"]
        source = p.get("source", "?")
        is_real = "i.pinimg.com" in img
        if is_real:
            has_real += 1
        else:
            has_fallback += 1
        flag = "[OK] REAL PINTEREST" if is_real else "[--] FALLBACK"
        print(f"  [{i+1}] {flag} | source={source!r}")
        print(f"       img: {img[:80]}")
        print(f"       url: {p.get('pin_url', '')[:70]}")
        print()

    print(f"Summary: {has_real} real Pinterest pins, {has_fallback} fallback images")


if __name__ == "__main__":
    asyncio.run(test())
