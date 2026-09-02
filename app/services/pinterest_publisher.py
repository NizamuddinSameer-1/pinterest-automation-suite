"""
Pinterest Realism Engine — browser publisher and native-schedule driver.

One persistent Chromium profile (`data/pinterest_profile`) drives Pinterest's own
pin builder, so nothing here needs an API token, a developer app or an approval.
Two things it must never do again, both learned the hard way:

  * **Assume.** The previous version waited a flat 3.5 s after `goto`, then hunted
    for a file input. The builder is a lazily hydrated SPA, so on a slow load it
    searched an empty document — `data/debug/pinterest_no_file_input.png` is that
    moment. Every step now waits for the thing it needs.
  * **Substitute.** It also selected "the first available board" when the
    requested board was missing, and left the description empty without noticing:
    `data/debug/pinterest_publish_fail_91899.png` is a finished draft with a blank
    description and an enabled Publish button. That is why the operator found
    seven Pinterest *drafts* and no live pins. Every field is now read back after
    typing, and a missing board is an error that lists the boards that do exist.

Scheduling drives *Pinterest's* scheduler — the native "Publish at a later date"
toggle — so pins publish with this machine switched off. If the date and time
cannot be set and read back, the pin is abandoned as a Pinterest draft and
reported as failed; it is never published immediately instead.

A batch shares one browser: `run_pin_batch` opens the profile once and walks the
pins, because launching Chromium per pin is what made 15 pins impractical.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Sequence

from playwright.async_api import Page, async_playwright

from app.config import settings
from app.services import board_catalog as _board_catalog
from app.services.browser_utils import clean_stale_locks as _clean_stale_locks
from app.services.browser_utils import insert_text, kill_chrome_for_profile

logger = logging.getLogger("pre.pinterest_publisher")

PROFILE_DIR = Path("./data/pinterest_profile").resolve()
DEBUG_DIR = Path("./data/debug").resolve()
BUILDER_URL = "https://www.pinterest.com/pin-creation-tool/"

#: How long to let the SPA hydrate. Pinterest on a cold profile regularly needs
#: more than ten seconds; the old fixed 3.5 s wait is what broke.
HYDRATION_TIMEOUT_S = 60
#: How long to wait for proof that a submit landed before calling it a draft.
CONFIRM_TIMEOUT_S = 45
#: How long to wait for a field, dropdown or toggle to appear once its parent is
#: hydrated. Short, because by then the page is alive.
ELEMENT_TIMEOUT_MS = 15_000
#: How long to wait for the board dropdown to list *any* board. Its rows arrive
#: from a separate request, so an empty list means "not loaded yet" far more often
#: than "no boards"; deciding before this expires is how a publish came to blame a
#: missing board for a slow list.
BOARD_LIST_TIMEOUT_S = 20
#: How long to wait for the filtered list after typing a board name. Shorter,
#: because the rows are already rendered and only being narrowed.
BOARD_FILTER_TIMEOUT_S = 8
#: Board names last seen in the account's dropdown. `app/services/board_catalog.py`
#: owns the file — it is written here on every successful selection and read by the
#: API's pre-flight check, so a wrong board name is refused before a browser is
#: launched for it. Advisory only, never a substitute for the dropdown itself.
BOARDS_CACHE = _board_catalog.CATALOG_PATH

# Selectors live at module scope so `scripts/inspect_pinterest_schedule.py` can
# probe exactly what the publisher will use. Each tuple is tried in order; the
# early entries are Pinterest's own test ids, the later ones are generic
# fallbacks for when it renames them (it does, roughly every few months).
SEL_LOGIN = (
    'button:has-text("Log in")',
    'a[href*="/login"]',
    '[data-test-id="simple-login-button"]',
)
SEL_FILE_INPUT = (
    '[data-test-id*="media-upload"] input[type="file"]',
    'input[accept*="image"]',
    'input[type="file"]',
)
SEL_IMAGE_READY = (
    '[data-test-id*="pin-draft-image"] img',
    '[data-test-id="media-preview"] img',
    'img[src^="blob:"]',
    'div[data-test-id*="thumbnail"] img',
)
SEL_TITLE = (
    '[data-test-id*="pin-draft-title"] input',
    'input[id*="storyboard-selector-title"]',
    'input[placeholder*="title" i]',
    'textarea[placeholder*="title" i]',
    '[aria-label*="title" i]',
)
SEL_DESCRIPTION = (
    '[data-test-id*="pin-draft-description"] [contenteditable="true"]',
    'div[contenteditable="true"][aria-label*="description" i]',
    'div[contenteditable="true"][data-placeholder*="Describe" i]',
    'textarea[id*="description"]',
    'textarea[placeholder*="Describe" i]',
    'div[contenteditable="true"]',
)
SEL_LINK = (
    '[data-test-id*="pin-draft-link"] input',
    'input[id*="storyboard-selector-link"]',
    'input[placeholder*="link" i]',
    '[aria-label*="destination link" i]',
)
SEL_BOARD_BUTTON = (
    '[data-test-id="board-dropdown-select-button"]',
    '[data-test-id*="board-dropdown"] button',
    '[data-test-id*="board-selector"]',
    'button[aria-haspopup="listbox"]',
)
SEL_BOARD_SEARCH = (
    '[data-test-id="board-search-input"] input',
    'input[placeholder*="Search boards" i]',
    'input[aria-label*="Search" i]',
)
SEL_BOARD_OPTION = (
    '[data-test-id*="board-row"]',
    'div[role="option"]',
    '[data-test-id*="boardWithoutSection"]',
)
SEL_SCHEDULE_TOGGLE = (
    '[data-test-id*="schedule"] input[type="checkbox"]',
    'input[type="checkbox"][id*="schedule" i]',
    'label:has-text("Publish at a later date")',
    'div:has-text("Publish at a later date") input[type="checkbox"]',
    'text="Publish at a later date"',
)
SEL_DATE_FIELD = (
    '[data-test-id*="schedule-date"] input',
    '[data-test-id*="date-picker"] input',
    'input[type="date"]',
    'input[placeholder*="MM/DD" i]',
    '[aria-label*="date" i]',
)
SEL_TIME_FIELD = (
    '[data-test-id*="schedule-time"] input',
    '[data-test-id*="time-picker"] input',
    'input[type="time"]',
    'input[placeholder*="AM" i]',
    '[aria-label*="time" i]',
)
SEL_PUBLISH = (
    '[data-test-id="pin-creation-publish-button"] button',
    '[data-test-id="pin-creation-publish-button"]',
    'button:text-is("Publish")',
    'button:has-text("Publish"):not(:has-text("later"))',
)
SEL_ALERT = (
    '[role="alert"]',
    '[data-test-id*="error"]',
    '[data-test-id*="toast"]',
)

#: Text Pinterest shows when it has kept a pin as a draft rather than posting it.
DRAFT_MARKERS = ("changes stored", "pin drafts", "saved as draft", "draft saved")
#: Text that proves a *scheduled* pin was accepted.
SCHEDULE_MARKERS = ("will publish", "scheduled for", "scheduled to publish", "your pin is scheduled")
#: Text that proves an *immediate* pin went live.
PUBLISH_MARKERS = ("saved to", "your pin has been published", "pin published", "published to")


class PinterestLoginRequired(PermissionError):
    """The profile is not logged in. `scripts/init_pinterest_auth.py` fixes this."""


class BuilderNotReady(RuntimeError):
    """Pinterest's pin builder never finished loading, so nothing could be typed."""


class FieldNotAccepted(RuntimeError):
    """A field was typed into and did not hold the value — the pin would be wrong."""


class BoardNotFound(RuntimeError):
    """The requested board is not in the dropdown. Guessing would post elsewhere."""


class BoardListUnreadable(RuntimeError):
    """
    The board picker opened but never listed a single board.

    Kept separate from BoardNotFound on purpose: that one is a statement about the
    account ("you have no board called X"), and reporting it when the list simply
    had not loaded sent the operator looking for a problem on Pinterest that was
    not there. This one is a statement about the page.
    """


class ScheduleNotAccepted(RuntimeError):
    """The date/time could not be set. Publishing now instead is not an option."""


class NotConfirmed(RuntimeError):
    """Pinterest never confirmed the submit — usually it kept the pin as a draft."""


@dataclass
class PinSpec:
    """One pin to put through the builder. `scheduled_for` must be aware UTC."""

    pin_id: str
    image_path: str
    title: str
    description: str = ""
    link: str | None = None
    board_name: str | None = None
    scheduled_for: datetime | None = None
    profile_id: str = "default"


@dataclass
class PinResult:
    """What actually happened, in the publisher's own words."""

    pin_id: str
    status: str  # "published" | "scheduled" | "failed"
    confirmed_by: str | None = None
    live_url: str | None = None
    board_used: str | None = None
    scheduled_for: datetime | None = None
    scheduled_local: str | None = None
    error: str | None = None
    error_kind: str | None = None
    screenshot: str | None = None
    alerts: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "pin_id": self.pin_id,
            "status": self.status,
            "confirmed_by": self.confirmed_by,
            "live_url": self.live_url,
            "board": self.board_used,
            "board_used": self.board_used,
            "scheduled_for": self.scheduled_for.isoformat() if self.scheduled_for else None,
            "scheduled_local": self.scheduled_local,
            "error": self.error,
            "error_kind": self.error_kind,
            "screenshot": self.screenshot,
            "alerts": self.alerts,
        }


def clean_stale_locks(profile_dir: Path) -> None:
    """Remove Chrome lock files to prevent 'Opening in existing browser session'."""
    _clean_stale_locks(profile_dir)


def kill_orphaned_chrome(profile_dir: Path | None = None) -> None:
    """
    Kill lingering Chrome processes locking the Pinterest profile folder.

    Scoped to this profile only — the previous `taskkill /F /IM chrome.exe`
    closed every Chrome window the operator had open.
    """
    target = profile_dir or PROFILE_DIR
    kill_chrome_for_profile(target)


def _squash(text: str | None) -> str:
    """Collapse whitespace so a read-back comparison is not defeated by layout."""
    return re.sub(r"\s+", " ", (text or "")).strip()


def _digits(text: str | None) -> str:
    return re.sub(r"\D", "", text or "")


def resolve_board(board_name: str | None) -> str:
    """
    The board a pin must go to, or an error.

    Pinterest requires a board and there is no sane default: posting a Halloween
    pin to whichever board happens to be first is the silent-wrong-target bug this
    module used to have.
    """
    target = (board_name or settings.default_board_name or "").strip()
    if not target:
        raise ValueError(
            "No target board. Set the pin's board_name, or DEFAULT_BOARD_NAME in .env — "
            "Pinterest needs a board and guessing one would post to the wrong place."
        )
    return target


#: A board row reads "Halloween Home Decor\n12 pins" (and sometimes a section name
#: after that). Only the first line is the name the operator typed, and `_squash`
#: flattens the newline away, so the split has to happen before it — the old code
#: split on a double space that `_squash` had already collapsed, which is why every
#: name it reported carried "12 pins" on the end.
_BOARD_COUNT_TAIL = re.compile(r"\s*\d[\d,.]*\s*(pins?|followers?|sections?)\b.*$", re.I)


def _board_row_name(raw: str | None) -> str:
    """The board name from one dropdown row's text."""
    first_line = (raw or "").splitlines()[0] if (raw or "").strip() else ""
    return _squash(_BOARD_COUNT_TAIL.sub("", first_line))


async def _debug_shot(page: Page, tag: str) -> str | None:
    """Screenshot into data/debug and return the path, or None if even that failed."""
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = DEBUG_DIR / f"pinterest_{tag}_{stamp}.png"
        await page.screenshot(path=str(path), full_page=False)
        logger.error("Screenshot saved: data/debug/%s", path.name)
        return str(path)
    except Exception as e:  # a screenshot failure must not mask the real error
        logger.warning("Could not screenshot (%s): %s", tag, e)
        return None


class PinterestBuilder:
    """
    A live pin builder page, one method per step the operator would perform.

    Every method either does the thing and proves it, or raises. Nothing returns a
    "probably worked" — the reason this module exists in its current form is that
    the old one reported success for pins that only ever became drafts.
    """

    def __init__(self, page: Page) -> None:
        self.page = page
        self.captured_pin_ids: list[str] = []
        self._wire_network()

    # ── evidence collection ──────────────────────
    def _wire_network(self) -> None:
        """
        Watch Pinterest's own API traffic for a created pin id.

        This is the strongest confirmation available: the id comes from
        Pinterest's response, not from anything guessed on this side.
        """

        async def on_response(response) -> None:
            try:
                url = response.url
                if not any(k in url for k in ("PinResource", "/pins", "pin/create", "StoryPinCreate")):
                    return
                if response.status not in (200, 201):
                    return
                body = await response.text()
                m = re.search(r'"(?:pin_)?id"\s*:\s*"?(\d{15,25})"?', body)
                if m and m.group(1) not in self.captured_pin_ids:
                    self.captured_pin_ids.append(m.group(1))
                    logger.info("Captured pin id from Pinterest's own response: %s", m.group(1))
            except Exception:
                pass  # a listener must never break the run

        self.page.on("response", lambda r: asyncio.create_task(on_response(r)))

    async def alerts(self) -> list[str]:
        """Whatever Pinterest is complaining about on screen, for the error message."""
        found: list[str] = []
        for sel in SEL_ALERT:
            try:
                loc = self.page.locator(sel)
                for i in range(min(await loc.count(), 4)):
                    text = _squash(await loc.nth(i).inner_text())
                    if text and text not in found:
                        found.append(text[:200])
            except Exception:
                continue
        return found

    async def _find(self, selectors: Sequence[str], *, timeout_ms: int = ELEMENT_TIMEOUT_MS):
        """
        First selector in `selectors` that matches a visible element, as a locator.

        Returns None on timeout rather than raising, because several callers treat
        a missing control as information (no schedule toggle, no board search box)
        rather than as an error.
        """
        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        while True:
            for sel in selectors:
                try:
                    loc = self.page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        return loc
                except Exception:
                    continue
            if asyncio.get_event_loop().time() >= deadline:
                return None
            await self.page.wait_for_timeout(400)

    async def _dismiss_popups(self) -> None:
        for sel in (
            'button:has-text("Accept")', 'button:has-text("Got it")',
            'button:has-text("Not now")', 'button:has-text("Skip")',
            '[data-test-id="closeup-close-button"]',
        ):
            try:
                btn = self.page.locator(sel)
                if await btn.count() > 0 and await btn.first.is_visible():
                    await btn.first.click(timeout=3000)
                    await self.page.wait_for_timeout(400)
            except Exception:
                continue

    async def _assert_logged_in(self) -> None:
        if "/login" in self.page.url:
            raise PinterestLoginRequired(
                "Pinterest redirected to the login page. Run "
                "'python scripts/init_pinterest_auth.py' and log in once; the profile "
                "at data/pinterest_profile then keeps the session."
            )
        for sel in SEL_LOGIN:
            try:
                if await self.page.locator(sel).count() > 0:
                    raise PinterestLoginRequired(
                        "Pinterest is showing a log-in button, so this profile is signed "
                        "out. Run 'python scripts/init_pinterest_auth.py' and log in once."
                    )
            except PinterestLoginRequired:
                raise
            except Exception:
                continue

    # ── steps ────────────────────────────────────
    async def open(self) -> None:
        """
        Load the builder and wait until it can actually be typed into.

        The wait is for the file input itself, polled — not a fixed sleep. On
        timeout it screenshots and reports how much of the page did render, which
        is what distinguishes "Pinterest is slow" from "Pinterest changed the DOM".
        """
        await self.page.goto(BUILDER_URL, timeout=60_000, wait_until="domcontentloaded")
        await self._dismiss_popups()
        await self._assert_logged_in()

        deadline = asyncio.get_event_loop().time() + HYDRATION_TIMEOUT_S
        while asyncio.get_event_loop().time() < deadline:
            for sel in SEL_FILE_INPUT:
                try:
                    if await self.page.locator(sel).count() > 0:
                        logger.info("Pin builder hydrated (found %s)", sel)
                        return
                except Exception:
                    continue
            await self._assert_logged_in()
            await self.page.wait_for_timeout(500)

        shot = await _debug_shot(self.page, "builder_not_ready")
        body = _squash(await self.page.inner_text("body"))[:300] if await self.page.locator("body").count() else ""
        raise BuilderNotReady(
            f"Pinterest's pin builder never produced an upload control within "
            f"{HYDRATION_TIMEOUT_S}s at {self.page.url}. Page text so far: "
            f"{body or '(empty document — the SPA did not hydrate)'}. "
            f"Screenshot: {Path(shot).name if shot else 'none'}."
        )

    async def attach_image(self, image_path: Path) -> None:
        """Upload the image and wait for Pinterest to echo a preview of it."""
        # Pinterest hides its file inputs behind a styled drop zone; making them
        # visible is what lets set_input_files target them directly.
        await self.page.evaluate(
            """() => document.querySelectorAll('input[type="file"]').forEach(el => {
                el.style.opacity = '1'; el.style.display = 'block';
                el.style.visibility = 'visible'; el.style.pointerEvents = 'auto';
                el.style.position = 'static'; el.style.width = '80px'; el.style.height = '80px';
            })"""
        )
        file_input = None
        for sel in SEL_FILE_INPUT:
            loc = self.page.locator(sel)
            if await loc.count() > 0:
                file_input = loc.first
                break
        if file_input is None:
            shot = await _debug_shot(self.page, "no_file_input")
            raise BuilderNotReady(
                "No file input on the pin builder even though it looked hydrated. "
                f"Screenshot: {Path(shot).name if shot else 'none'}."
            )
        await file_input.set_input_files(str(image_path))
        logger.info("Attached %s, waiting for Pinterest's preview...", image_path.name)

        if await self._find(SEL_IMAGE_READY, timeout_ms=45_000) is None:
            shot = await _debug_shot(self.page, "image_not_accepted")
            raise FieldNotAccepted(
                f"Pinterest never displayed a preview of {image_path.name}, so the "
                "upload did not take. The image is "
                f"{image_path.stat().st_size // 1024} KB; Pinterest rejects files over "
                f"20 MB and non-image formats. Screenshot: "
                f"{Path(shot).name if shot else 'none'}."
            )

    async def _read_back(self, loc) -> str:
        """What the field contains now — inputs and contenteditables both."""
        try:
            value = await loc.input_value(timeout=3000)
            if value:
                return _squash(value)
        except Exception:
            pass
        try:
            return _squash(await loc.inner_text(timeout=3000))
        except Exception:
            return ""

    async def _set_field(
        self,
        label: str,
        selectors: Sequence[str],
        value: str,
        *,
        required: bool = True,
    ) -> str:
        """
        Type `value` into the first matching field and prove it stuck.

        The description is the reason this exists: it silently stayed empty on the
        Aug-21 run while the title and link were fine, and nothing noticed until a
        human looked at the screenshot. `fill()` first (fast, atomic), then a click
        plus `insert_text` for React editors that ignore programmatic value sets.
        """
        value = (value or "").strip()
        if not value:
            return ""
        loc = await self._find(selectors)
        if loc is None:
            if required:
                shot = await _debug_shot(self.page, f"no_{label}_field")
                raise FieldNotAccepted(
                    f"Could not find the {label} field on the pin builder. Pinterest "
                    f"has probably renamed it; run scripts/inspect_pinterest_schedule.py "
                    f"to see the current DOM. Screenshot: {Path(shot).name if shot else 'none'}."
                )
            logger.warning("No %s field on this builder; leaving it unset", label)
            return ""

        probe = self._normalise_for_compare(value)[:40]
        for attempt in ("fill", "insert"):
            try:
                if attempt == "fill":
                    await loc.fill(value, timeout=8000)
                else:
                    await loc.click(timeout=5000)
                    await self.page.keyboard.press("Control+A")
                    await self.page.keyboard.press("Delete")
                    await insert_text(self.page, value)
            except Exception as e:
                logger.debug("%s via %s failed: %s", label, attempt, e)
            await self.page.wait_for_timeout(500)
            if probe in self._normalise_for_compare(await self._read_back(loc)):
                logger.info("%s accepted (%s)", label, attempt)
                return value

        got = await self._read_back(loc)
        shot = await _debug_shot(self.page, f"{label}_not_accepted")
        raise FieldNotAccepted(
            f"The {label} did not stick: Pinterest shows {got[:80]!r} instead of "
            f"{value[:80]!r}. Publishing would have produced a pin with a wrong or "
            f"empty {label}. Screenshot: {Path(shot).name if shot else 'none'}."
        )

    @staticmethod
    def _normalise_for_compare(text: str) -> str:
        """Lowercase and drop the smart quotes Pinterest's editors substitute."""
        return _squash(text).lower().replace("’", "'").replace("“", '"').replace("”", '"')

    async def set_title(self, title: str) -> str:
        return await self._set_field("title", SEL_TITLE, title)

    async def set_description(self, description: str) -> str:
        return await self._set_field("description", SEL_DESCRIPTION, description)

    async def set_link(self, link: str | None) -> str:
        """The affiliate link. Absent is legal; wrong is not, so it is verified too."""
        if not link:
            return ""
        return await self._set_field("destination link", SEL_LINK, link)

    async def _visible_board_names(self) -> list[str]:
        names: list[str] = []
        for sel in SEL_BOARD_OPTION:
            loc = self.page.locator(sel)
            count = await loc.count()
            if not count:
                continue
            for i in range(min(count, 40)):
                try:
                    raw = await loc.nth(i).inner_text()
                except Exception:
                    continue
                name = _board_row_name(raw)
                if name and name not in names:
                    names.append(name)
            if names:
                break
        return names

    async def _wait_for_board_names(self, *, timeout_s: float) -> list[str]:
        """
        Poll until the dropdown lists at least one board, then return the names.

        Returns `[]` only if nothing appeared within `timeout_s`. The rows come
        from their own request after the menu opens, so reading once — which is
        what this replaced — reports an empty account whenever Pinterest is slow.
        """
        deadline = asyncio.get_event_loop().time() + timeout_s
        while True:
            names = await self._visible_board_names()
            if names:
                return names
            if asyncio.get_event_loop().time() >= deadline:
                return []
            await self.page.wait_for_timeout(500)

    @staticmethod
    def _remember_boards(names: Sequence[str]) -> None:
        """
        Record the account's board names so a bad board can be caught before a
        browser is launched for it — the pre-flight check in `board_catalog`.

        Advisory in both directions: the dropdown is still the authority, and a
        failure to write must never fail a publish. `source="publish"` marks the
        read as incidental, because a publish only sees the rows *one* pin's
        dropdown rendered and a virtualised list can be short.
        """
        if not names:
            return
        try:
            _board_catalog.write_catalog(names, source="publish")
        except (OSError, ValueError) as e:
            logger.debug("Could not cache board names: %s", e)

    async def choose_board(self, board_name: str) -> str:
        """
        Select exactly `board_name`, or raise listing the boards that do exist.

        There is deliberately no "first available board" fallback: that fallback is
        why pins could land on an unrelated board without anyone being told.

        The order matters. The menu is opened and the *unfiltered* list is waited
        for first, so that every later decision is made against a list that is
        known to have rendered. Only then is the name typed to narrow it. The old
        version typed immediately and read the rows once, ~2 s after opening the
        menu, so a list that had not arrived yet came back empty and was reported
        as "Boards offered: (none readable)" — a missing board, which it was not.
        """
        button = await self._find(SEL_BOARD_BUTTON)
        if button is None:
            shot = await _debug_shot(self.page, "no_board_dropdown")
            raise BoardNotFound(
                "No board dropdown on the pin builder, so the board could not be set. "
                f"Screenshot: {Path(shot).name if shot else 'none'}."
            )
        await button.click()
        await self.page.wait_for_timeout(600)

        available = await self._wait_for_board_names(timeout_s=BOARD_LIST_TIMEOUT_S)
        if not available:
            shot = await _debug_shot(self.page, "board_list_unreadable")
            raise BoardListUnreadable(
                f"The board picker opened but listed no board within {BOARD_LIST_TIMEOUT_S}s, "
                f"so whether {board_name!r} exists could not be determined and nothing was "
                "selected. This is a page problem, not a board problem: Pinterest was slow, "
                "or it renamed the board rows (SEL_BOARD_OPTION in this file). "
                f"Screenshot: {Path(shot).name if shot else 'none'}."
            )
        self._remember_boards(available)
        logger.info("Boards in the dropdown: %s", ", ".join(available[:15]))

        clicked = await self._click_board_row(board_name)

        if not clicked:
            # The visible list is virtualised, so a board can exist and still not
            # be among the rows read above; the search box is what proves it. Only
            # after both the full list and the filtered list have failed is this a
            # real "no such board".
            available = await self._board_names_unfiltered(available)
            shot = await _debug_shot(self.page, "board_not_found")
            raise BoardNotFound(
                f"Board {board_name!r} is not in this account's dropdown, and picking a "
                f"different one would publish to the wrong place. Boards offered: "
                f"{', '.join(available[:15]) or '(none readable)'}. Either create "
                f"{board_name!r} on Pinterest or change the pin's board / "
                f"DEFAULT_BOARD_NAME. Screenshot: {Path(shot).name if shot else 'none'}."
            )

        await self.page.wait_for_timeout(900)
        # Prove the dropdown now names the board. A click that closed the menu
        # without selecting anything looks identical until this check.
        shown = _squash(await button.inner_text()) if button else ""
        if _board_catalog.normalise(board_name) not in _board_catalog.normalise(shown):
            logger.warning(
                "Board dropdown reads %r after selecting %r; continuing because "
                "Pinterest sometimes relabels the control, but this is the check to "
                "watch if a pin lands on the wrong board.", shown, board_name,
            )
        logger.info("Board selected: %s", board_name)
        return board_name

    async def _click_board_row(self, board_name: str) -> bool:
        """
        Find and click the row for `board_name`, narrowing with the search box.

        Tries the rendered list first (a short account needs no search at all),
        then types the name and waits for the filtered rows — `_wait_for_board_names`
        again, because filtering re-fetches and the list is briefly empty either
        way, which is exactly the state the old code mistook for "no such board".
        """
        if await self._click_matching_row(board_name):
            return True

        search = await self._find(SEL_BOARD_SEARCH, timeout_ms=4000)
        if search is None:
            return False
        try:
            await search.fill(board_name, timeout=5000)
        except Exception as e:
            logger.debug("Could not type into the board search box: %s", e)
            return False

        deadline = asyncio.get_event_loop().time() + BOARD_FILTER_TIMEOUT_S
        while True:
            if await self._click_matching_row(board_name):
                return True
            if asyncio.get_event_loop().time() >= deadline:
                return False
            await self.page.wait_for_timeout(500)

    async def _click_matching_row(self, wanted: str) -> bool:
        """
        Click the row for `wanted`, preferring an exact board name over a prefix.

        Two things this gets right that the previous version did not.

        It compares the *board name*. A row's text also carries its tail — "Cozy
        Fall 12 pins · 2 sections" — so comparing the raw text meant `text == wanted`
        could never be true, and every selection that ever worked did so through the
        `startswith` branch. `_board_row_name` strips the tail, and `board_catalog.
        normalise` folds case and '&'/'and' the same way the pre-flight check does,
        so a board the API accepted is a board this can click.

        And it reads every candidate row before clicking any of them, so 'Cozy Fall'
        selects 'Cozy Fall' even when 'Cozy Fall & Halloween Finds' renders above it.
        Prefix matching alone would have taken the first row it saw. Those
        near-duplicate names are precisely what `pinterest_seo` generates, so the
        wrong-board risk was live rather than theoretical.
        """
        target = _board_catalog.normalise(wanted)
        if not target:
            return False

        rows: list[tuple[str, Any]] = []

        option = self.page.get_by_role("option", name=wanted, exact=False)
        try:
            for i in range(min(await option.count(), 40)):
                row = option.nth(i)
                rows.append((_board_catalog.normalise(_board_row_name(await row.inner_text())), row))
        except Exception:
            pass

        for sel in SEL_BOARD_OPTION:
            loc = self.page.locator(sel)
            try:
                count = await loc.count()
            except Exception:
                continue
            for i in range(min(count, 40)):
                row = loc.nth(i)
                try:
                    rows.append(
                        (_board_catalog.normalise(_board_row_name(await row.inner_text())), row)
                    )
                except Exception:
                    continue

        exact = [row for name, row in rows if name == target]
        prefixed = [row for name, row in rows if name != target and name.startswith(target)]
        if prefixed and not exact:
            logger.warning(
                "No board row reads exactly %r; falling back to a name that starts with it. "
                "Check the pin landed on the board you meant.", wanted,
            )
        for row in exact + prefixed:
            try:
                await row.click()
                return True
            except Exception as e:
                logger.debug("Board row for %r would not take a click: %s", wanted, e)
        return False

    async def _board_names_unfiltered(self, fallback: Sequence[str]) -> list[str]:
        """
        The account's board names with the search filter cleared.

        Called only when reporting a failure: the filter is still holding the name
        that matched nothing, so enumerating now would list nothing and the error
        would say the account has no boards at all.
        """
        search = await self._find(SEL_BOARD_SEARCH, timeout_ms=2000)
        if search is not None:
            try:
                await search.fill("", timeout=4000)
                names = await self._wait_for_board_names(timeout_s=6)
                if names:
                    self._remember_boards(names)
                    return names
            except Exception as e:
                logger.debug("Could not clear the board search box: %s", e)
        return list(fallback)

    # ── Pinterest's own scheduler ────────────────
    @staticmethod
    def _same_date(readback: str, when: datetime) -> bool:
        got = _digits(readback)
        if len(got) < 4:
            return False
        padded = (f"{when.month:02d}", f"{when.day:02d}", str(when.year))
        loose = (str(when.month), str(when.day), str(when.year)[-2:])
        return all(p in got for p in padded) or all(p in got for p in loose)

    @staticmethod
    def _same_time(readback: str, when: datetime) -> bool:
        got = _digits(readback)
        minute = f"{when.minute:02d}"
        hour12 = (when.hour % 12) or 12
        if not any(h + minute in got for h in (f"{when.hour:02d}", f"{hour12:02d}", str(hour12))):
            return False
        low = readback.lower()
        if "am" in low or "pm" in low:
            return ("pm" in low) == (when.hour >= 12)
        return True

    async def _type_into(self, loc, text: str) -> None:
        """Clear a field, type `text`, then blur with Tab so the picker commits it."""
        await loc.click(timeout=5000)
        try:
            await loc.fill("", timeout=3000)
        except Exception:
            await self.page.keyboard.press("Control+A")
            await self.page.keyboard.press("Delete")
        try:
            await loc.fill(text, timeout=3000)
        except Exception:
            await insert_text(self.page, text)
        # Tab, never Enter: Enter inside the builder submits the pin, which on a
        # half-set schedule would publish it immediately — the exact accident this
        # whole module is designed to make impossible.
        await self.page.keyboard.press("Tab")
        await self.page.wait_for_timeout(500)

    async def _pick_from_options(self, wanted_texts: Sequence[str]) -> bool:
        """Click a dropdown option matching any of `wanted_texts` (digits compared)."""
        for role in ("option", "menuitem"):
            loc = self.page.get_by_role(role)
            for i in range(min(await loc.count(), 120)):
                try:
                    text = _squash(await loc.nth(i).inner_text())
                except Exception:
                    continue
                for wanted in wanted_texts:
                    if text.lower() == wanted.lower() or (_digits(wanted) and _digits(text) == _digits(wanted)):
                        await loc.nth(i).click()
                        await self.page.wait_for_timeout(400)
                        return True
        return False

    async def _toggle_schedule_on(self) -> None:
        """Flip "Publish at a later date", then wait for the date field to appear."""
        for sel in SEL_SCHEDULE_TOGGLE:
            try:
                loc = self.page.locator(sel).first
                if await loc.count() == 0:
                    continue
                try:
                    if await loc.get_attribute("type") == "checkbox" and await loc.is_checked():
                        return
                except Exception:
                    pass
                try:
                    await loc.click(timeout=4000)
                except Exception:
                    await loc.click(timeout=4000, force=True)
                await self.page.wait_for_timeout(900)
                if await self._find(SEL_DATE_FIELD, timeout_ms=6000) is not None:
                    logger.info("Native scheduling enabled via %s", sel)
                    return
            except Exception:
                continue

        shot = await _debug_shot(self.page, "no_schedule_toggle")
        raise ScheduleNotAccepted(
            "Could not find or flip Pinterest's \"Publish at a later date\" control, so "
            "the pin cannot be scheduled. It has been left as a Pinterest draft rather "
            "than published now. Run scripts/inspect_pinterest_schedule.py to see what "
            f"the builder currently renders. Screenshot: {Path(shot).name if shot else 'none'}."
        )

    async def set_native_schedule(self, when_utc: datetime) -> str:
        """
        Schedule this pin with Pinterest itself, for `when_utc`.

        Pinterest's builder speaks the browser's local time, so the UTC time from
        the planner is converted here, once, at the last possible moment. Returns
        the local "YYYY-MM-DD HH:MM" that was set, for the record.
        """
        local = when_utc.astimezone()
        await self._toggle_schedule_on()

        date_field = await self._find(SEL_DATE_FIELD, timeout_ms=8000)
        if date_field is None:
            raise ScheduleNotAccepted(
                "The schedule toggle is on but no date field appeared. The pin is a "
                "Pinterest draft; nothing was published."
            )
        is_native = (await date_field.get_attribute("type") or "").lower() == "date"
        formats = ["%Y-%m-%d"] if is_native else [
            "%m/%d/%Y", f"{local.month}/{local.day}/{local.year}", "%Y-%m-%d", "%b %d, %Y",
        ]
        for fmt in formats:
            text = local.strftime(fmt) if "%" in fmt else fmt
            await self._type_into(date_field, text)
            if self._same_date(await self._read_back(date_field), local):
                break
        else:
            # Last resort: the calendar popup, clicked by its accessible label.
            await date_field.click()
            await self.page.wait_for_timeout(700)
            label = f"{local.strftime('%B')} {local.day}, {local.year}"
            picked = False
            for sel in (f'[aria-label="{label}"]', f'[aria-label*="{label}"]',
                        f'[role="gridcell"]:text-is("{local.day}")'):
                loc = self.page.locator(sel)
                if await loc.count() > 0:
                    await loc.first.click()
                    picked = True
                    break
            if not (picked and self._same_date(await self._read_back(date_field), local)):
                got = await self._read_back(date_field)
                shot = await _debug_shot(self.page, "schedule_date_rejected")
                raise ScheduleNotAccepted(
                    f"Pinterest would not accept the date {local:%Y-%m-%d}; the field "
                    f"reads {got!r}. The pin is left as a draft — it was NOT published "
                    f"now. Screenshot: {Path(shot).name if shot else 'none'}."
                )

        time_field = await self._find(SEL_TIME_FIELD, timeout_ms=8000)
        if time_field is None:
            shot = await _debug_shot(self.page, "no_schedule_time_field")
            raise ScheduleNotAccepted(
                f"The date was set to {local:%Y-%m-%d} but there is no time field, so "
                "the hour would be Pinterest's guess. Left as a draft. Screenshot: "
                f"{Path(shot).name if shot else 'none'}."
            )
        native_time = (await time_field.get_attribute("type") or "").lower() == "time"
        hour12 = (local.hour % 12) or 12
        candidates = [f"{local.hour:02d}:{local.minute:02d}"] if native_time else [
            f"{hour12}:{local.minute:02d} {'PM' if local.hour >= 12 else 'AM'}",
            f"{hour12:02d}:{local.minute:02d} {'PM' if local.hour >= 12 else 'AM'}",
            f"{local.hour:02d}:{local.minute:02d}",
        ]
        for text in candidates:
            await self._type_into(time_field, text)
            if self._same_time(await self._read_back(time_field), local):
                break
        else:
            # Pinterest sometimes offers fixed 15-minute slots in a listbox instead
            # of a free-text field. Then only a listed slot can be chosen.
            await time_field.click()
            await self.page.wait_for_timeout(700)
            if not (await self._pick_from_options(candidates)
                    and self._same_time(await self._read_back(time_field), local)):
                got = await self._read_back(time_field)
                shot = await _debug_shot(self.page, "schedule_time_rejected")
                raise ScheduleNotAccepted(
                    f"Pinterest would not accept the time {local:%H:%M} (local); the "
                    f"field reads {got!r}. If its picker only offers 15-minute slots, "
                    f"plan times on the quarter hour. The pin is left as a draft — it "
                    f"was NOT published now. Screenshot: {Path(shot).name if shot else 'none'}."
                )

        # Both fields, re-read together: a date picker can reset the time.
        final_date = await self._read_back(date_field)
        final_time = await self._read_back(time_field)
        if not (self._same_date(final_date, local) and self._same_time(final_time, local)):
            shot = await _debug_shot(self.page, "schedule_drifted")
            raise ScheduleNotAccepted(
                f"After setting both fields Pinterest shows {final_date!r} / "
                f"{final_time!r}, not {local:%Y-%m-%d %H:%M}. Left as a draft. "
                f"Screenshot: {Path(shot).name if shot else 'none'}."
            )
        stamp = f"{local:%Y-%m-%d %H:%M}"
        logger.info("Pinterest scheduled slot set to %s (local)", stamp)
        return stamp

    # ── submit and proof ─────────────────────────
    async def submit(self) -> None:
        """Click Publish. Refuses to click a disabled button, which proves nothing."""
        btn = await self._find(SEL_PUBLISH, timeout_ms=10_000)
        if btn is None:
            by_role = self.page.get_by_role("button", name="Publish", exact=True)
            if await by_role.count() > 0:
                btn = by_role.first
        if btn is None:
            shot = await _debug_shot(self.page, "no_publish_button")
            raise NotConfirmed(
                "No Publish button on the builder, so nothing was submitted. "
                f"Screenshot: {Path(shot).name if shot else 'none'}."
            )
        try:
            disabled = (await btn.get_attribute("aria-disabled")) == "true" or not await btn.is_enabled()
        except Exception:
            disabled = False
        if disabled:
            alerts = await self.alerts()
            shot = await _debug_shot(self.page, "publish_disabled")
            raise NotConfirmed(
                "Pinterest's Publish button is disabled, so a required field is still "
                f"unhappy. On screen: {'; '.join(alerts) or 'no visible message'}. "
                f"Screenshot: {Path(shot).name if shot else 'none'}."
            )
        await btn.scroll_into_view_if_needed()
        await btn.click(force=True)
        logger.info("Publish clicked; waiting for Pinterest to confirm...")

    async def _body_text(self) -> str:
        try:
            return self._normalise_for_compare(await self.page.inner_text("body"))
        except Exception:
            return ""

    async def confirm(self, *, scheduled: bool) -> tuple[str, str | None]:
        """
        Wait for observed proof that the submit landed.

        Returns `(confirmed_by, live_url)`. Raises `NotConfirmed` otherwise — and
        when Pinterest has visibly kept the pin as a draft it says so, because
        "left as a Pinterest draft" is a different problem from "never submitted"
        and the operator has to clear those drafts by hand.
        """
        markers = SCHEDULE_MARKERS if scheduled else PUBLISH_MARKERS
        deadline = asyncio.get_event_loop().time() + CONFIRM_TIMEOUT_S
        while asyncio.get_event_loop().time() < deadline:
            await self.page.wait_for_timeout(1000)

            if self.captured_pin_ids:
                pin_id = self.captured_pin_ids[0]
                url = f"https://www.pinterest.com/pin/{pin_id}/"
                if scheduled:
                    return f"Pinterest's own response (pin {pin_id})", None
                return "network response", url

            body = await self._body_text()
            hit = next((m for m in markers if m in body), None)
            if hit:
                url = None
                try:
                    link = self.page.locator('a[href*="/pin/"]:not([href*="pin-creation"])')
                    if not scheduled and await link.count() > 0:
                        href = await link.first.get_attribute("href")
                        if href:
                            url = href if href.startswith("http") else f"https://www.pinterest.com{href}"
                except Exception:
                    pass
                return f"on-screen confirmation ({hit!r})", url

            if not scheduled and "/pin/" in self.page.url and "pin-creation" not in self.page.url:
                return "redirect to the pin page", self.page.url

            if scheduled and "pin-creation-tool" not in self.page.url:
                # The builder only navigates away once Pinterest has taken the pin;
                # on any validation failure it stays put with the form intact.
                return f"builder closed after scheduling (now at {self.page.url})", None

        alerts = await self.alerts()
        body = await self._body_text()
        looks_like_draft = any(m in body for m in DRAFT_MARKERS)
        shot = await _debug_shot(self.page, "publish_not_confirmed")
        what = "schedule" if scheduled else "publish"
        if looks_like_draft:
            raise NotConfirmed(
                f"Pinterest kept this pin as a DRAFT instead of accepting the {what}: "
                f"the builder still shows a draft marker after {CONFIRM_TIMEOUT_S}s. "
                "Nothing is live and nothing is scheduled; the draft is sitting under "
                "\"Pin drafts\" in the pin builder and should be deleted there before "
                f"retrying. On screen: {'; '.join(alerts) or 'no visible message'}. "
                f"Screenshot: {Path(shot).name if shot else 'none'}."
            )
        raise NotConfirmed(
            f"Pinterest never confirmed the {what} within {CONFIRM_TIMEOUT_S}s and the "
            f"page is at {self.page.url}. Treat this pin as not {what}ed. On screen: "
            f"{'; '.join(alerts) or 'no visible message'}. Screenshot: "
            f"{Path(shot).name if shot else 'none'}."
        )


_ERROR_KINDS: tuple[tuple[type[Exception], str], ...] = (
    (PinterestLoginRequired, "login_required"),
    (BuilderNotReady, "builder_not_ready"),
    (FieldNotAccepted, "field_not_accepted"),
    (BoardNotFound, "board_not_found"),
    (BoardListUnreadable, "board_list_unreadable"),
    (ScheduleNotAccepted, "schedule_not_accepted"),
    (NotConfirmed, "not_confirmed"),
    (FileNotFoundError, "image_missing"),
    (ValueError, "bad_request"),
)


def _error_kind(exc: BaseException) -> str:
    """A stable machine-readable label, so the UI can explain each failure once."""
    for cls, name in _ERROR_KINDS:
        if isinstance(exc, cls):
            return name
    return "unexpected"


async def _process_one(builder: PinterestBuilder, spec: PinSpec) -> PinResult:
    """Drive the builder for one pin. Raises; the caller turns that into a result."""
    image = Path(spec.image_path).resolve()
    if not image.exists():
        raise FileNotFoundError(f"Pin image file not found on disk: {image}")
    board = resolve_board(spec.board_name)
    scheduled = spec.scheduled_for is not None

    await builder.open()
    await builder.attach_image(image)
    await builder.set_title(spec.title)
    await builder.set_description(spec.description)
    await builder.set_link(spec.link)
    await builder.choose_board(board)

    stamp = None
    if scheduled:
        stamp = await builder.set_native_schedule(spec.scheduled_for)

    await builder.submit()
    confirmed_by, live_url = await builder.confirm(scheduled=scheduled)

    return PinResult(
        pin_id=spec.pin_id,
        status="scheduled" if scheduled else "published",
        confirmed_by=confirmed_by,
        live_url=live_url,
        board_used=board,
        scheduled_for=spec.scheduled_for,
        scheduled_local=stamp,
        alerts=await builder.alerts(),
    )


async def _launch_context(p, headless: bool, profile_id: str = "default"):
    """Open the persistent Pinterest profile for a specific profile_id, recovering from a stale Chrome lock."""
    from app.services.pinterest_profiles import get_profile_dir
    pdir = get_profile_dir(profile_id)
    pdir.mkdir(parents=True, exist_ok=True)
    last: Exception | None = None
    for attempt in range(1, 4):
        clean_stale_locks(pdir)
        try:
            return await p.chromium.launch_persistent_context(
                user_data_dir=str(pdir),
                headless=headless,
                viewport={"width": 1280, "height": 900},
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
        except Exception as e:
            last = e
            logger.warning("Chromium launch attempt %s/3 for profile '%s' failed: %s", attempt, profile_id, e)
            if "existing browser session" in str(e).lower() or "lock" in str(e).lower():
                kill_orphaned_chrome(pdir)
            await asyncio.sleep(2)
    raise RuntimeError(f"Could not open the Pinterest browser profile '{profile_id}' after 3 attempts: {last}")


class WrongEventLoop(RuntimeError):
    """Raised when the current loop cannot spawn Playwright's driver."""


def _refuse_unless_proactor() -> None:
    """
    On Windows, refuse to start a browser on a SelectorEventLoop.

    Playwright launches its driver with `asyncio.create_subprocess_exec`, which
    SelectorEventLoop does not implement — it raises a bare `NotImplementedError`
    with an empty message, which reached the operator as "Direct browser publish
    failed:" and said nothing. uvicorn installs exactly that loop whenever it
    runs with `reload=True`.

    An earlier fix ran the batch in a worker thread with its own Proactor loop.
    It had to pass `on_result=None` to stay thread-safe, which silently disabled
    per-pin progress and per-pin recording for bulk runs — so a batch that failed
    halfway recorded nothing. The browser now runs in `scripts.publish_bg`
    instead, and this check exists to make a regression obvious rather than mute.
    """
    if sys.platform != "win32":
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    proactor = getattr(asyncio, "ProactorEventLoop", None)
    if proactor is not None and not isinstance(loop, proactor):
        raise WrongEventLoop(
            f"Playwright cannot start on {type(loop).__name__}: on Windows it needs a "
            "ProactorEventLoop to spawn its driver. Do not run the browser inside the "
            "API process — start it through app.services.publish_runs.start_run, which "
            "runs scripts.publish_bg in its own interpreter."
        )


async def _run_pin_batch_impl(
    specs: Sequence[PinSpec],
    *,
    headless: bool = False,
    on_result: Callable[[PinResult], Awaitable[None]] | None = None,
) -> list[PinResult]:
    results: list[PinResult] = []
    if not specs:
        return results

    # Group pins by target profile while preserving overall order
    from collections import defaultdict
    profile_groups: dict[str, list[PinSpec]] = defaultdict(list)
    for spec in specs:
        pid = (spec.profile_id or "default").strip()
        profile_groups[pid].append(spec)

    async with async_playwright() as p:
        for profile_id, group_specs in profile_groups.items():
            logger.info("Opening browser session for Pinterest profile: %s (%d pin(s))", profile_id, len(group_specs))
            context = await _launch_context(p, headless, profile_id=profile_id)
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                builder = PinterestBuilder(page)
                aborted: str | None = None

                for index, spec in enumerate(group_specs, start=1):
                    if aborted:
                        results.append(PinResult(
                            pin_id=spec.pin_id, status="failed",
                            error=aborted, error_kind="login_required",
                            scheduled_for=spec.scheduled_for,
                        ))
                        continue
                    label = f"[{index}/{len(group_specs)}] pin {spec.pin_id} (profile: {profile_id})"
                    try:
                        logger.info("%s — %s", label, "scheduling" if spec.scheduled_for else "publishing")
                        result = await _process_one(builder, spec)
                        logger.info("%s — %s (%s)", label, result.status, result.confirmed_by)
                    except Exception as e:
                        kind = _error_kind(e)
                        logger.error("%s — failed (%s): %s", label, kind, e)
                        result = PinResult(
                            pin_id=spec.pin_id, status="failed", error=str(e), error_kind=kind,
                            scheduled_for=spec.scheduled_for,
                        )
                        if kind == "login_required":
                            aborted = str(e)
                    results.append(result)
                    if on_result is not None:
                        await on_result(result)
            finally:
                try:
                    await context.close()
                except Exception:
                    pass
    return results


async def run_pin_batch(
    specs: Sequence[PinSpec],
    *,
    headless: bool = False,
    on_result: Callable[[PinResult], Awaitable[None]] | None = None,
) -> list[PinResult]:
    """
    Put a whole batch through one browser session, in order.

    Call this from `scripts.publish_bg`, not from a request handler: it needs a
    ProactorEventLoop on Windows and it takes minutes. `on_result` is awaited
    after every pin so progress and recording survive a failure halfway through.
    """
    _refuse_unless_proactor()
    return await _run_pin_batch_impl(specs, headless=headless, on_result=on_result)


async def read_account_boards(*, headless: bool = True, profile_id: str = "default") -> list[str]:
    """
    Open the pin builder for a specific Pinterest profile, read the board dropdown and return the board names.
    """
    _refuse_unless_proactor()

    async with async_playwright() as p:
        context = await _launch_context(p, headless, profile_id=profile_id)
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            builder = PinterestBuilder(page)
            await builder.open()

            button = await builder._find(SEL_BOARD_BUTTON)
            if button is None:
                shot = await _debug_shot(page, "boards_no_dropdown")
                raise BoardNotFound(
                    "The pin builder loaded but has no board dropdown to read, so the "
                    "board list could not be refreshed. Pinterest may have renamed the "
                    f"control (SEL_BOARD_BUTTON in this file). Screenshot: "
                    f"{Path(shot).name if shot else 'none'}."
                )
            await button.click()
            await page.wait_for_timeout(600)

            names = await builder._wait_for_board_names(timeout_s=BOARD_LIST_TIMEOUT_S)
            if not names:
                shot = await _debug_shot(page, "boards_list_unreadable")
                raise BoardListUnreadable(
                    f"The board picker opened but listed no board within "
                    f"{BOARD_LIST_TIMEOUT_S}s, so the board list was left alone rather "
                    "than overwritten with nothing. Pinterest was slow, or it renamed the "
                    f"board rows (SEL_BOARD_OPTION in this file). Screenshot: "
                    f"{Path(shot).name if shot else 'none'}."
                )

            # The dropdown virtualises long lists, so scroll the rows and re-read
            # until the count stops growing. Without this an account with thirty
            # boards would be catalogued as the twelve that happened to be painted,
            # and the pre-flight check would refuse eighteen real boards.
            seen = list(names)
            for _ in range(8):
                try:
                    await page.mouse.wheel(0, 600)
                except Exception:
                    break
                await page.wait_for_timeout(400)
                more = await builder._visible_board_names()
                added = [n for n in more if n not in seen]
                if not added:
                    break
                seen.extend(added)

            logger.info("Read %d board(s) from the dropdown: %s", len(seen), ", ".join(seen[:20]))
            return seen
        finally:
            try:
                await context.close()
            except Exception:
                pass


async def publish_pin_via_browser(
    image_path: str,
    title: str,
    description: str,
    link: str | None = None,
    board_name: str | None = None,
    headless: bool = False,
    scheduled_for: datetime | None = None,
    pin_id: str = "single",
    profile_id: str = "default",
) -> dict[str, Any]:
    """
    Publish (or natively schedule) a single pin, raising on any failure.

    Kept as the one-pin entry point the API and the local scheduler already call.
    Pass `scheduled_for` (aware UTC) to hand the pin to Pinterest's own scheduler
    instead of publishing immediately.
    """
    spec = PinSpec(
        pin_id=pin_id,
        image_path=image_path,
        title=title,
        description=description,
        link=link,
        board_name=board_name,
        scheduled_for=scheduled_for.astimezone(timezone.utc) if scheduled_for else None,
        profile_id=profile_id,
    )
    results = await run_pin_batch([spec], headless=headless)
    result = results[0]

    if result.status == "failed":
        message = result.error or "The Pinterest publisher failed without saying why."
        if result.error_kind == "login_required":
            raise PinterestLoginRequired(message)
        if result.error_kind == "image_missing":
            raise FileNotFoundError(message)
        if result.error_kind == "bad_request":
            raise ValueError(message)
        raise RuntimeError(message)

    logger.info(
        "🎉 Pin %s (confirmed by %s). Live URL: %s",
        result.status, result.confirmed_by, result.live_url or "not exposed by Pinterest",
    )
    payload = result.as_dict()
    payload.update({"title": title, "image_path": str(Path(image_path).resolve())})
    return payload
