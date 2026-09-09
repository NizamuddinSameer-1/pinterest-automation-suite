"""Debug script for Pinterest Trend System."""
import asyncio
import sys
sys.path.insert(0, '.')

async def test():
    from app.services.pinterest_trends_scraper import (
        get_official_pinterest_trends,
        get_trend_deep_dive,
        _read_cache,
        _cache_dir,
    )

    # Check cache dir
    cache_path = _cache_dir()
    print(f"Cache dir: {cache_path}")
    cache_files = list(cache_path.glob("*.json"))
    print(f"Cache files: {[f.name for f in cache_files]}")

    print()
    print("=== Testing get_official_pinterest_trends (breakout, no refresh) ===")
    try:
        trends = await get_official_pinterest_trends(preset="breakout", force_refresh=False)
        print(f"Got {len(trends)} trends")
        for t in trends[:3]:
            term = t["term"]
            mom = t["mom_change"]
            spk = t["sparkline"]
            src = t.get("source", "N/A")
            print(f"  - {term!r} | mom:{mom} | sparkline len:{len(spk)}")
    except Exception as e:
        import traceback
        print(f"ERROR: {e}")
        traceback.print_exc()

    print()
    print("=== Testing get_trend_deep_dive (no refresh) ===")
    try:
        data = await get_trend_deep_dive("fall nail colors 2026", force_refresh=False)
        print(f"Term: {data['term']}")
        print(f"Popular pins count: {len(data['popular_pins'])}")
        for p in data["popular_pins"][:5]:
            source = p.get("source", "?")
            img = p["image_url"][:70]
            title = p.get("title", "?")[:40]
            hook = p.get("visual_hook", "?")
            print(f"  Pin: source={source!r} | hook={hook!r} | img={img}")
    except Exception as e:
        import traceback
        print(f"ERROR: {e}")
        traceback.print_exc()

    print()
    print("=== Checking for stale/poisoned deep dive cache ===")
    for cf in cache_files:
        if "deep_dive" in cf.name:
            import json
            try:
                payload = json.loads(cf.read_text(encoding="utf-8"))
                trends_list = payload.get("trends", [])
                if trends_list:
                    item = trends_list[0]
                    pins = item.get("popular_pins", [])
                    imgs = [p.get("image_url", "") for p in pins]
                    has_pinimg = any("i.pinimg.com" in u for u in imgs)
                    duplicates = len(imgs) != len(set(imgs))
                    old_catalog_source = any(p.get("source") == "Pinterest Popular Pins" for p in pins)
                    print(f"  {cf.name}: {len(pins)} pins | has_real_pinimg={has_pinimg} | has_duplicates={duplicates} | old_catalog_source={old_catalog_source}")
                    if duplicates or old_catalog_source:
                        print(f"    ⚠️  STALE CACHE! Delete {cf.name}")
            except Exception as e:
                print(f"  {cf.name}: ERROR reading - {e}")

if __name__ == "__main__":
    asyncio.run(test())
