"""
The account's real Pinterest board names, on disk, readable without a browser.

Why this module exists. Pin board names are *invented* — `pinterest_seo` asks the
model for a `board_suggestion` and `POST /api/pins/draft` stores whatever comes
back. On 2026-08-23 that produced 'Halloween Home Decor', 'Cozy Fall Aesthetics',
'Cozy Fall & Halloween Finds', 'Cozy Fall & Halloween Fashion' and 'Halloween
Outfits' across twenty pin drafts. The account has none of them. Every publish
attempt therefore cost a Chromium launch, thirty seconds, and one abandoned
Pinterest draft, and only said so *after* all of that — the operator found ten
drafts and no pins.

The publisher already read the account's boards, printed them into an error and
cached them here (`_remember_boards`). Nothing ever read the cache back: the
pre-flight check it was written for did not exist, so `data/pinterest_boards.json`
was write-only and, because only a *successful* selection wrote it, absent. This
module is the reader, and the publisher now writes through `write_catalog` so
there is exactly one owner of the file.

The contract is deliberately narrow:

  * The catalogue is **evidence, not authority.** It records what the board
    dropdown showed at `read_at`. `check_board` can say "this board was not there",
    which is enough to refuse before spending a browser; it can never say a board
    exists *now*. The dropdown remains the only authority, and the publisher still
    verifies against it.
  * A missing or stale catalogue is reported as `no_catalog` / `stale_catalog`,
    never as a missing board. Blaming the account for an unread file is the same
    mistake as blaming it for a slow dropdown.
  * Nothing here launches a browser. `start_refresh` spawns a child process for
    that, for the same reason publishing does (see `publish_runs`).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

logger = logging.getLogger("pre.board_catalog")

#: Written by a board refresh and by every successful `choose_board`.
CATALOG_PATH = Path("./data/pinterest_boards.json").resolve()
#: Where the refresh child reports progress. Separate from the catalogue so a
#: failed refresh cannot destroy the last good read.
REFRESH_STATUS_PATH = Path("./data/pinterest_boards_refresh.json").resolve()

#: How long a read stays trustworthy enough to refuse a publish on. Boards are
#: created by hand and rarely; a day is generous and still catches "I made the
#: board last week and PRE is still using a month-old list".
STALE_AFTER_HOURS = 24

# Refresh status values, mirroring publish_runs so the UI polls one shape.
STARTING = "starting"
RUNNING = "running"
DONE = "done"
ERROR = "error"
FINISHED = (DONE, ERROR)

class CatalogUnavailable(RuntimeError):
    """No usable board list on disk, so no board can be judged before publishing."""


@dataclass(frozen=True)
class Catalog:
    """One reading of the account's board dropdown."""

    boards: tuple[str, ...]
    read_at: datetime | None
    source: str

    @property
    def age_seconds(self) -> float | None:
        if self.read_at is None:
            return None
        return (datetime.now(timezone.utc) - self.read_at).total_seconds()

    @property
    def is_stale(self) -> bool:
        age = self.age_seconds
        return age is None or age > STALE_AFTER_HOURS * 3600

    @property
    def is_empty(self) -> bool:
        return not self.boards

    def as_dict(self) -> dict[str, Any]:
        return {
            "boards": list(self.boards),
            "count": len(self.boards),
            "read_at": self.read_at.isoformat() if self.read_at else None,
            "age_seconds": self.age_seconds,
            "stale": self.is_stale,
            "stale_after_hours": STALE_AFTER_HOURS,
            "source": self.source,
        }


EMPTY = Catalog(boards=(), read_at=None, source="none")

def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write atomically: a half-written catalogue would read as an empty account."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def read_catalog(profile_id: str | None = None) -> Catalog:
    """The last recorded board list for a given profile, or `EMPTY`. Never raises — absence is normal."""
    from app.services.pinterest_profiles import get_boards_catalog_path
    cat_path = get_boards_catalog_path(profile_id)
    raw = _read_json(cat_path)
    if not raw:
        return EMPTY

    boards = [str(b).strip() for b in (raw.get("boards") or []) if str(b).strip()]
    read_at: datetime | None = None
    stamp = raw.get("read_at")
    if stamp:
        try:
            parsed = datetime.fromisoformat(str(stamp))
            read_at = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            logger.warning("Board catalogue for profile %s has an unreadable read_at %r; treating as stale", profile_id, stamp)

    # Order is preserved but duplicates are dropped.
    seen: set[str] = set()
    unique = tuple(b for b in boards if not (b.lower() in seen or seen.add(b.lower())))
    return Catalog(boards=unique, read_at=read_at, source=str(raw.get("source") or "unknown"))


def write_catalog(names: Sequence[str], *, source: str, profile_id: str | None = None) -> Catalog:
    """
    Record the board names just read from the dropdown for a given profile.
    """
    from app.services.pinterest_profiles import get_boards_catalog_path
    cat_path = get_boards_catalog_path(profile_id)
    cleaned = [str(n).strip() for n in names if str(n).strip()]
    if not cleaned:
        raise ValueError("Refusing to write an empty board catalogue — nothing was read")

    now = datetime.now(timezone.utc)
    _write_json(cat_path, {"read_at": now.isoformat(), "source": source, "boards": cleaned, "profile_id": profile_id or "default"})
    logger.info("Board catalogue updated for profile %s from %s: %d board(s)", profile_id or "default", source, len(cleaned))
    return read_catalog(profile_id=profile_id)

def normalise(name: str | None) -> str:
    """
    A board name reduced to what Pinterest actually compares.

    Case and surrounding space are ignored because the operator types the name by
    hand and Pinterest does not care. Ampersands fold to "and" because the model
    writes both ('Cozy Fall & Halloween Finds' vs '... and ...') and the difference
    has never been meaningful. Nothing else folds: 'Halloween Outfits' and
    'Halloween Outfit' are different boards and must stay different.
    """
    text = " ".join((name or "").split()).lower()
    return " ".join(text.replace("&", " and ").split())


def match(board_name: str | None, boards: Sequence[str]) -> str | None:
    """
    The catalogued board `board_name` refers to, exactly, or None.

    Returns the *catalogued spelling*, which is what should be typed into the
    dropdown. There is no fuzzy fallback on purpose: a near-match is how a
    Halloween pin lands on a Christmas board, and the operator can see the real
    list in the error instead.
    """
    wanted = normalise(board_name)
    if not wanted:
        return None
    for board in boards:
        if normalise(board) == wanted:
            return board
    return None


def close_names(board_name: str | None, boards: Sequence[str], *, limit: int = 3) -> list[str]:
    """
    Catalogued boards worth *suggesting* for a name that did not match.

    Suggestions only — never used to select anything. Ranked by shared words, so
    'Cozy Fall & Halloween Finds' suggests 'Halloween Outfits' before 'Recipes'.
    """
    wanted = set(normalise(board_name).split())
    if not wanted:
        return []
    scored = [(len(wanted & set(normalise(b).split())), b) for b in boards]
    return [b for score, b in sorted(scored, key=lambda s: -s[0]) if score][:limit]

#: `verdict` values. Checked by pins.py and by scripts/verify/verify_board_catalog.py.
OK = "ok"
UNKNOWN_BOARD = "unknown_board"
NO_BOARD = "no_board"
NO_CATALOG = "no_catalog"
STALE_CATALOG = "stale_catalog"

#: Verdicts that mean "do not launch a browser for this".
BLOCKING = (UNKNOWN_BOARD, NO_BOARD)


@dataclass(frozen=True)
class BoardCheck:
    """What can be said about a pin's board *without* opening Pinterest."""

    verdict: str
    requested: str | None
    resolved: str | None
    catalog: Catalog
    message: str
    suggestions: tuple[str, ...] = ()

    @property
    def blocks_publish(self) -> bool:
        return self.verdict in BLOCKING

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "requested_board": self.requested,
            "resolved_board": self.resolved,
            "blocks_publish": self.blocks_publish,
            "message": self.message,
            "suggestions": list(self.suggestions),
            "known_boards": list(self.catalog.boards),
            "catalog_read_at": self.catalog.read_at.isoformat() if self.catalog.read_at else None,
            "catalog_stale": self.catalog.is_stale,
        }


def _ago(catalog: Catalog) -> str:
    age = catalog.age_seconds
    if age is None:
        return "at an unknown time"
    if age < 3600:
        return f"{age / 60:.0f} minutes ago"
    if age < 86400:
        return f"{age / 3600:.0f} hours ago"
    return f"{age / 86400:.0f} days ago"

def check_board(board_name: str | None, *, fallback: str | None = None, profile_id: str | None = None) -> BoardCheck:
    """
    Judge a pin's board against the catalogue for a given profile, before anything is launched.
    """
    catalog = read_catalog(profile_id=profile_id)
    requested = (board_name or "").strip() or None
    resolved = requested or ((fallback or "").strip() or None)

    if not resolved:
        return BoardCheck(
            verdict=NO_BOARD, requested=requested, resolved=None, catalog=catalog,
            message=(
                "This pin has no board and DEFAULT_BOARD_NAME is unset. Pinterest requires "
                "a board and PRE will not choose one for you — pick one of your boards."
            ),
        )

    if catalog.is_empty:
        return BoardCheck(
            verdict=NO_CATALOG, requested=requested, resolved=resolved, catalog=catalog,
            message=(
                f"Publishing to {resolved!r} without checking it first: PRE has no record of "
                f"boards for account {profile_id or 'default'} yet. Refresh the board list to catch a wrong board "
                "name before it costs a browser launch and an abandoned draft."
            ),
        )

    hit = match(resolved, catalog.boards)
    if hit is None:
        suggestions = close_names(resolved, catalog.boards)
        hint = f" Closest boards you do have: {', '.join(suggestions)}." if suggestions else ""
        return BoardCheck(
            verdict=UNKNOWN_BOARD, requested=requested, resolved=resolved, catalog=catalog,
            suggestions=tuple(suggestions),
            message=(
                f"Board {resolved!r} was not in your Pinterest board list when it was last "
                f"read ({_ago(catalog)}). Publishing would open Chromium, fill the entire pin "
                f"in and then fail, leaving an abandoned Pinterest draft behind.{hint} "
                f"Your boards: {', '.join(catalog.boards[:15])}. Change the pin's board, create "
                "the board on Pinterest, or refresh the list if you created it since."
            ),
        )

    if catalog.is_stale:
        return BoardCheck(
            verdict=STALE_CATALOG, requested=requested, resolved=hit, catalog=catalog,
            message=(
                f"Board {hit!r} matched a board list read {_ago(catalog)}, older than "
                f"{STALE_AFTER_HOURS}h. Proceeding; refresh the list if a board was renamed."
            ),
        )

    return BoardCheck(
        verdict=OK, requested=requested, resolved=hit, catalog=catalog,
        message=f"Board {hit!r} is one of your {len(catalog.boards)} Pinterest boards.",
    )

#: A dropdown read is one page load. Longer than this and the child is gone.
REFRESH_STALL_MINUTES = 5


def read_refresh_status(profile_id: str | None = None) -> dict[str, Any] | None:
    from app.services.pinterest_profiles import get_boards_refresh_path
    return _read_json(get_boards_refresh_path(profile_id))


def write_refresh_status(payload: dict[str, Any], profile_id: str | None = None) -> None:
    from app.services.pinterest_profiles import get_boards_refresh_path
    _write_json(get_boards_refresh_path(profile_id), payload)


def _refresh_stalled(status: dict[str, Any], profile_id: str | None = None) -> bool:
    """True when a refresh still claims to be running but stopped writing."""
    from app.services.pinterest_profiles import get_boards_refresh_path
    if status.get("status") in FINISHED:
        return False
    try:
        rpath = get_boards_refresh_path(profile_id)
        age = datetime.now(timezone.utc).timestamp() - rpath.stat().st_mtime
    except OSError:
        return True
    return age > REFRESH_STALL_MINUTES * 60


def refresh_status_view(profile_id: str | None = None) -> dict[str, Any]:
    """The refresh status as the API reports it, with staleness folded in."""
    status = read_refresh_status(profile_id=profile_id)
    if status is None:
        return {"status": "never_run", "boards": None, "error": None, "stalled": False, "profile_id": profile_id or "default"}
    return {**status, "stalled": _refresh_stalled(status, profile_id=profile_id), "profile_id": profile_id or "default"}


def start_refresh(*, headless: bool = True, profile_id: str | None = None) -> dict[str, Any]:
    """
    Launch `python -m scripts.refresh_boards_bg [--profile <profile_id>]` and return its initial status.
    """
    running = read_refresh_status(profile_id=profile_id)
    if running and running.get("status") not in FINISHED and not _refresh_stalled(running, profile_id=profile_id):
        logger.info("Board refresh already running for profile %s (pid %s); not starting a second one",
                    profile_id or "default", running.get("pid"))
        return running

    status: dict[str, Any] = {
        "status": STARTING,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "headless": headless,
        "profile_id": profile_id or "default",
        "boards": None,
        "error": None,
        "pid": None,
    }
    write_refresh_status(status, profile_id=profile_id)

    root = Path(__file__).resolve().parents[2]
    log_name = f"board_refresh_{profile_id}.log" if profile_id and profile_id != "default" else "board_refresh.log"
    log_path = root / "data" / log_name
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log = open(log_path, "w", encoding="utf-8", buffering=1)
    except OSError as e:
        raise RuntimeError(f"Could not open {log_path} for the board refresh: {e}") from e

    command = [sys.executable, "-m", "scripts.refresh_boards_bg"]
    if not headless:
        command.append("--visible")
    if profile_id and profile_id != "default":
        command.extend(["--profile", profile_id])

    try:
        proc = subprocess.Popen(
            command, cwd=str(root), stdout=log,
            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        )
    except OSError as e:
        log.close()
        status = {**status, "status": ERROR,
                  "error": f"Could not start the board refresh: {e}",
                  "finished_at": datetime.now(timezone.utc).isoformat()}
        write_refresh_status(status, profile_id=profile_id)
        raise RuntimeError(status["error"]) from e

    status = {**status, "status": RUNNING, "pid": proc.pid}
    write_refresh_status(status, profile_id=profile_id)
    logger.info("Board refresh started for profile %s as pid %s (headless=%s)", profile_id or "default", proc.pid, headless)
    return status
