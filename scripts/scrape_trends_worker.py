"""
Standalone CLI worker for Pinterest Trends scraping.
Runs in a separate Python process with WindowsProactorEventLoopPolicy
so Playwright can launch Chromium cleanly without uvicorn's SelectorEventLoop restrictions.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.WARNING)


async def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Missing command argument"}))
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "popular_pins":
        # python -m scripts.scrape_trends_worker popular_pins <term> <count> <country> [related_terms_json]
        from app.services.pinterest_trends_scraper import scrape_popular_pins_for_term
        term = sys.argv[2] if len(sys.argv) > 2 else "fall nail colors 2026"
        count = int(sys.argv[3]) if len(sys.argv) > 3 else 12
        country = sys.argv[4] if len(sys.argv) > 4 else "US"
        related = json.loads(sys.argv[5]) if len(sys.argv) > 5 else []
        pins = await scrape_popular_pins_for_term(term, count=count, related_terms=related, country=country)
        print(json.dumps(pins))

    elif cmd == "official_trends":
        # python -m scripts.scrape_trends_worker official_trends <preset> <country> <limit>
        from app.services.pinterest_trends_scraper import scrape_pinterest_trends_playwright
        preset = sys.argv[2] if len(sys.argv) > 2 else "breakout"
        country = sys.argv[3] if len(sys.argv) > 3 else "US"
        limit = int(sys.argv[4]) if len(sys.argv) > 4 else 10
        trends = await scrape_pinterest_trends_playwright(preset=preset, country=country, limit=limit)
        print(json.dumps(trends))

    elif cmd == "custom_metrics":
        # python -m scripts.scrape_trends_worker custom_metrics <term> <country>
        from app.services.pinterest_trends_scraper import scrape_custom_pinterest_trend_metrics
        term = sys.argv[2] if len(sys.argv) > 2 else "casual blazer outfits"
        country = sys.argv[3] if len(sys.argv) > 3 else "US"
        metrics = await scrape_custom_pinterest_trend_metrics(query=term, country=country)
        print(json.dumps(metrics))

    else:
        print(json.dumps({"error": f"Unknown command {cmd}"}))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
