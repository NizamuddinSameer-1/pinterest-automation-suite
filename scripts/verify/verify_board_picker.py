"""
Execute `choose_board` against a fake board picker — the one Pinterest control
whose failure mode was a misdiagnosis rather than a bug.

On 2026-08-23 at 01:04 a publish reported: "Board 'Halloween Home Decor' is not in
this account's dropdown ... Boards offered: (none readable)". The screenshot showed
the menu open, the name typed into the search box, and an empty list — because the
rows had not arrived yet. Two seconds after opening the menu the publisher read the
options once, found none, and blamed the account for a slow page.

Playwright is not installed in the verification VM and is not needed: `choose_board`
only ever speaks to `self.page`. So the page is faked, with rows that arrive after a
configurable number of polls, and the three outcomes are checked by running them:

  1. rows arrive late      -> the board is selected (no error at all)
  2. rows never arrive     -> BoardListUnreadable: a statement about the page
  3. board truly absent    -> BoardNotFound whose message names the boards that do
                              exist, which is only possible if the search filter was
                              cleared first

Case 3 is the one that protects the operator's time: an error that lists the real
boards ends the investigation, and "(none readable)" started one.
"""

import asyncio
import logging
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# Neither package exists in this VM, and nothing under test touches them:
# choose_board talks to the page object, and only resolve_board reads settings.
if "playwright" not in sys.modules:
    sys.modules["playwright"] = types.ModuleType("playwright")
    pw = types.ModuleType("playwright.async_api")
    pw.Page = object                        # type: ignore[attr-defined]
    pw.async_playwright = lambda: None      # type: ignore[attr-defined]
    sys.modules["playwright.async_api"] = pw

if "app.config" not in sys.modules:
    cfg = types.ModuleType("app.config")

    class _Settings:
        default_board_name = "Configured Board"
        storage_path = str(Path(tempfile.gettempdir()) / "pre_verify_store")

    cfg.settings = _Settings()              # type: ignore[attr-defined]
    sys.modules["app.config"] = cfg

from app.services import board_catalog as bc  # noqa: E402
from app.services import pinterest_publisher as pp  # noqa: E402

# Real timeouts are 20 s and 8 s; the fake page's clock is the same clock, so they
# are shortened here. The waiting itself is what is under test, not its duration.
pp.BOARD_LIST_TIMEOUT_S = 2
pp.BOARD_FILTER_TIMEOUT_S = 1

# The catalogue module owns the file now — `_remember_boards` writes through
# `board_catalog.write_catalog`, so redirecting `pp.BOARDS_CACHE` alone would leave
# this test writing into the operator's real data/pinterest_boards.json while
# asserting on an empty temp file. Both names are pointed at the temp path so the
# alias in pinterest_publisher cannot drift away from what is actually written.
CACHE = Path(tempfile.gettempdir()) / "pre_verify_boards.json"
bc.CATALOG_PATH = CACHE
pp.BOARDS_CACHE = CACHE
CACHE.unlink(missing_ok=True)   # or a stale file would prove nothing
# Screenshots and log lines belong to real runs. Cases 2 and 3 fail on purpose, and
# their debug shots must not land in data/debug/ next to the operator's evidence.
pp.DEBUG_DIR = Path(tempfile.mkdtemp(prefix="pre_verify_shots_"))
logging.getLogger("pre.pinterest_publisher").setLevel(logging.CRITICAL)

fails: list[str] = []


class FakeLocator:
    """One selector's matches. `kind` is what the fake page decided this selector is."""

    def __init__(self, page: "FakePage", kind: str, texts=()) -> None:
        self.page, self.kind, self.texts = page, kind, list(texts)

    @property
    def first(self) -> "FakeLocator":
        return self

    async def count(self) -> int:
        return len(self.texts)

    def nth(self, i: int) -> "FakeLocator":
        return FakeLocator(self.page, self.kind, [self.texts[i]])

    async def is_visible(self) -> bool:
        return bool(self.texts)

    async def inner_text(self, timeout=None) -> str:
        # The button reports live, like a real locator: the label changes when a
        # row is clicked, and choose_board reads it back to prove the selection.
        if self.kind == "button":
            return self.page.selected
        return self.texts[0] if self.texts else ""

    async def click(self, timeout=None) -> None:
        if self.kind == "button":
            self.page.menu_open = True
        elif self.kind == "row":
            self.page.selected = pp._board_row_name(self.texts[0])
            self.page.menu_open = False

    async def fill(self, value: str, timeout=None) -> None:
        if self.kind != "search":
            raise RuntimeError("only the search box is fillable")
        self.page.filter = value
        # Typing re-queries: the rows disappear and come back. This is the state
        # the old code sampled and read as "this account has no such board".
        self.page.polls = 0


class FakePage:
    """A board dropdown whose rows appear only after `ready_after` reads."""

    def __init__(self, boards, *, ready_after: int = 0, never_ready: bool = False) -> None:
        self.boards = list(boards)
        self.ready_after, self.never_ready = ready_after, never_ready
        self.menu_open = False
        self.filter = ""
        self.polls = 0
        self.selected = "Select a board"
        self.shots: list[str] = []

    def on(self, *a, **k) -> None:
        """PinterestBuilder wires network listeners in __init__."""

    def locator(self, sel: str):
        if sel in pp.SEL_BOARD_BUTTON:
            return FakeLocator(self, "button", ["button"])
        if sel in pp.SEL_BOARD_SEARCH:
            return FakeLocator(self, "search", ["searchbox"] if self.menu_open else [])
        if sel in pp.SEL_BOARD_OPTION:
            if not self.menu_open or self.never_ready:
                return FakeLocator(self, "row", [])
            self.polls += 1
            if self.polls <= self.ready_after:
                return FakeLocator(self, "row", [])          # still loading
            shown = [b for b in self.boards
                     if b.lower().startswith(self.filter.strip().lower())]
            # Real rows carry the pin count on a second line.
            return FakeLocator(self, "row", [f"{b}\n12 pins" for b in shown])
        return FakeLocator(self, "other", [])

    def get_by_role(self, role: str, name=None, exact: bool = False):
        return FakeLocator(self, "other", [])

    async def wait_for_timeout(self, ms: int) -> None:
        await asyncio.sleep(0)

    async def screenshot(self, **k) -> None:
        self.shots.append(str(k.get("path")))


async def run() -> None:
    # 1. The list is slow. This is the operator's run: rows on the sixth read.
    page = FakePage(["Just Random Photography", "Halloween Home Decor"], ready_after=6)
    builder = pp.PinterestBuilder(page)
    try:
        got = await builder.choose_board("Halloween Home Decor")
        if got != "Halloween Home Decor" or page.selected != "Halloween Home Decor":
            fails.append(f"a late-loading board list selected {page.selected!r}, "
                         f"not the board that was asked for")
    except Exception as e:
        fails.append(f"a board list that loaded on the sixth read raised "
                     f"{type(e).__name__}: {e} — the wait is not working, so a slow "
                     f"Pinterest is still reported as a missing board")

    # The cache is written from the successful path too, so it is checked here,
    # before the failing cases below have a chance to write it themselves.
    if not pp.BOARDS_CACHE.exists():
        fails.append(f"a successful board selection did not cache the account's board "
                     f"names to {pp.BOARDS_CACHE.name}, so nothing can check a board "
                     f"without launching a browser")

    # 2. The rows never render. That is a page fault, and must not be described as
    #    a missing board: the operator would go looking on Pinterest for nothing.
    page = FakePage(["Whatever"], never_ready=True)
    builder = pp.PinterestBuilder(page)
    try:
        await builder.choose_board("Halloween Home Decor")
        fails.append("a board picker that never listed anything selected a board anyway")
    except pp.BoardListUnreadable:
        pass
    except pp.BoardNotFound as e:
        fails.append(f"an unreadable board list was reported as a missing board: {e}")
    except Exception as e:
        fails.append(f"an unreadable board list raised {type(e).__name__}, not "
                     f"BoardListUnreadable: {e}")

    # 3. The board genuinely does not exist. The error has one job: name the boards
    #    that do, which requires clearing the filter that just matched nothing.
    page = FakePage(["Just Random Photography", "Aesthetic Style"])
    builder = pp.PinterestBuilder(page)
    try:
        await builder.choose_board("Halloween Home Decor")
        fails.append("a board this account does not have was accepted; the pin would "
                     "have gone somewhere unintended")
    except pp.BoardNotFound as e:
        message = str(e)
        if "Just Random Photography" not in message or "Aesthetic Style" not in message:
            fails.append(f"the missing-board error does not name the boards that exist "
                         f"(the search filter was never cleared): {message}")
        if "(none readable)" in message:
            fails.append("the missing-board error still says '(none readable)', the exact "
                         "wording that sent the operator looking for a Pinterest problem")
        if "12 pins" in message:
            fails.append("board names still carry their pin count, so the operator cannot "
                         "copy one into the composer as-is")
    except Exception as e:
        fails.append(f"a missing board raised {type(e).__name__}, not BoardNotFound: {e}")

    # 4. The cache exists for the API to check a board before launching Chromium.
    cached = pp.BOARDS_CACHE
    if not cached.exists():
        fails.append(f"the account's board names were not cached to {cached.name}, so "
                     "nothing can check a board without opening a browser")
    else:
        import json

        boards = (json.loads(cached.read_text(encoding="utf-8")) or {}).get("boards") or []
        if "Just Random Photography" not in boards:
            fails.append(f"the board cache holds {boards!r}, not the names just read")

    # 5. The parser, directly: rows are "name\ncount", and a name may contain digits.
    for raw, expected in (
        ("Halloween Home Decor\n12 pins", "Halloween Home Decor"),
        ("Just Random Photography\n1,204 pins  3 sections", "Just Random Photography"),
        ("Aesthetic Style", "Aesthetic Style"),
        ("Board 9 Lives\n0 pins", "Board 9 Lives"),
        ("", ""),
    ):
        got = pp._board_row_name(raw)
        if got != expected:
            fails.append(f"_board_row_name({raw!r}) = {got!r}, expected {expected!r}")


asyncio.run(run())

if fails:
    print("FAIL — board picker")
    for f in fails:
        print(f"  • {f}")
    sys.exit(1)

print("PASS — board picker (executed against a fake dropdown)")
print(f"  waits up to {pp.BOARD_LIST_TIMEOUT_S}s for the rows before judging the board")
print("  slow list -> selects; never renders -> board_list_unreadable; absent -> "
      "board_not_found naming the real boards")
print("  board names parsed without their pin counts, and cached for pre-flight checks")
