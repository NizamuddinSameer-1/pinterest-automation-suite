import asyncio
import sys
sys.path.insert(0, '.')
from app.services.pinterest_trends_scraper import get_trend_deep_dive

async def main():
    data = await get_trend_deep_dive('fall nail colors 2026', force_refresh=True)
    print("Term:", data["term"])
    print("Popular pins count:", len(data["popular_pins"]))
    for i, p in enumerate(data["popular_pins"][:8]):
        title = p["title"].encode("ascii", errors="replace").decode("ascii")
        hook = p["visual_hook"]
        img = p["image_url"]
        source = p["source"]
        print(f"Pin #{i+1}: {title} | Hook: {hook} | Img: {img[:70]} | Source: {source}")

if __name__ == "__main__":
    asyncio.run(main())
