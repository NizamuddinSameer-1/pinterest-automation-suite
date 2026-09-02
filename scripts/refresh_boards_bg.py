"""
The child process that reads the account's Pinterest board names.

    python -m scripts.refresh_boards_bg [--visible] [--profile <profile_id>]

Started by `app/services/board_catalog.start_refresh`. It opens the pin builder,
reads the board dropdown, and writes the names to the profile's board catalogue so
the API can refuse a pin whose board does not exist *before* spending a browser
launch and leaving an abandoned Pinterest draft behind.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pre.refresh_boards_bg")


async def main(*, headless: bool, profile_id: str = "default") -> int:
    from app.services import board_catalog as catalog

    started = catalog.read_refresh_status(profile_id=profile_id) or {}
    base = {
        **started,
        "status": catalog.RUNNING,
        "headless": headless,
        "profile_id": profile_id,
        "error": None,
    }
    catalog.write_refresh_status(base, profile_id=profile_id)

    try:
        from app.services.pinterest_publisher import read_account_boards

        names = await read_account_boards(headless=headless, profile_id=profile_id)
        written = catalog.write_catalog(names, source="refresh", profile_id=profile_id)
        catalog.write_refresh_status({
            **base,
            "status": catalog.DONE,
            "boards": list(written.boards),
            "count": len(written.boards),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }, profile_id=profile_id)
        logger.info("Board list refreshed for profile %s: %d board(s)", profile_id, len(written.boards))
        return 0
    except Exception as e:
        message = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
        logger.exception("Board refresh failed for profile %s: %s", profile_id, message)
        catalog.write_refresh_status({
            **base,
            "status": catalog.ERROR,
            "error": message,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }, profile_id=profile_id)
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Refresh Pinterest boards")
    parser.add_argument("--visible", action="store_true", help="Show browser window")
    parser.add_argument("--profile", default="default", help="Profile ID")
    args = parser.parse_args()

    try:
        raise SystemExit(asyncio.run(main(headless=not args.visible, profile_id=args.profile)))
    except SystemExit:
        raise
    except BaseException as exc:
        logger.exception("Board refresh died before it could record anything")
        try:
            from app.services import board_catalog as catalog

            catalog.write_refresh_status({
                **(catalog.read_refresh_status(profile_id=args.profile) or {}),
                "status": catalog.ERROR,
                "error": f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }, profile_id=args.profile)
        except Exception:
            pass
        raise SystemExit(3)
