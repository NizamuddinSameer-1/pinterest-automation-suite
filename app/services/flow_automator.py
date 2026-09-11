"""
Pinterest Realism Engine — Google Flow browser automator.

Drives the real Flow UI from a persistent, logged-in Chromium profile, then
downloads the images **Flow's own generation response names** at full resolution.

Two hard-won rules shape this file.

*Never read the DOM to decide which images are yours.* The previous version
snapshotted every `img[src*="getMediaUrlRedirect"]` before submitting and treated
anything new afterwards as the job's output. Flow's project canvas is a long,
lazily hydrated list of every past generation, so the baseline undercounts: old
images mount seconds later, the total crosses `baseline + 4`, and the "new" set is
a handful of old test renders. That is how job `908692a5` was credited with a
forklift safety poster, a text card, an espresso machine and a skincare bottle
while the log read "produced 4 verified image(s)". Attribution now comes from the
network response to our own submit (see `app.services.flow_media`), which cannot
describe anything but the request that caused it.

*Never touch the page directly.* Flow is a single-page app that redirects and
re-renders on its own schedule, so every `page.evaluate` goes through `_safe_eval`
and every `page.goto` through `_goto_settled`. A raw evaluate that lands
mid-navigation dies with "Execution context was destroyed", which used to fail an
entire run over a transient the next second would have cleared.

*Never send a keystroke the page can read as a command.* The prompt bar is a
contenteditable where Enter means send, and `keyboard.type` replays every
character as a real key press. The compiled prompt is 13 sections separated by
blank lines, so typing it submitted `PHOTOGRAPHIC INTENT: …` as its own
generation, cleared the box, submitted `SUBJECT: …`, and carried on down the
prompt — twelve unrequested generations from fragments of a brief, and one of the
images the operator was shown was a picture of the word "AVOID:". The run then
failed on its own read-back ("256 of 2040 characters present"), which was the
guard doing its job on damage already done. The prompt is now flattened to one
line by `flatten_prompt` and delivered by `browser_utils.insert_text`, a single
text insertion that produces no key events at all.
"""

import asyncio
import base64
import contextlib
import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright, Error as PlaywrightError

from app.config import settings
from app.services.browser_utils import TextEntryError, insert_text, kill_chrome_for_profile
from app.services.flow_media import (
    MIN_IMAGE_BYTES,
    MediaHarvest,
    captured_generation_path,
    describe_shape,
    endpoint_path,
    harvest_media,
    harvest_variations,
    looks_like_generation_url,
    media_identifier,
)

logger = logging.getLogger("pre.services.flow_automator")

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

PROFILE_DIR = Path("./data/flow_profile").resolve()
FLOW_URL = "https://labs.google/fx/tools/flow"

#: Where a project URL that worked once is remembered, so discovery only has to
#: succeed a single time on this machine. Flow's dashboard is a React app whose
#: project list hydrates after load; a one-shot `querySelector` two seconds after
#: `domcontentloaded` therefore finds nothing on a slow morning and finds a link on
#: a fast one, which is exactly how "it worked yesterday" happens.
PROJECT_MEMO = Path("./data/flow_project.json").resolve()

#: How long to keep polling the dashboard for a project link before giving up on
#: discovery. Generous on purpose: waiting 30 s beats creating a second project.
PROJECT_DISCOVERY_SECONDS = 30.0

#: How long to wait for Flow's client-side router to actually land on
#: /project/<id> after a navigation or a click. The URL changes *after* the
#: request, so checking `page.url` immediately reads the page we just left.
PROJECT_ROUTE_SECONDS = 20.0

#: How long to wait for Flow to answer the generation request. Flow renders four
#: variations in roughly 20–40 s; the ceiling is generous because the alternative
#: to waiting is guessing, and guessing is what produced the forklift.
GENERATION_TIMEOUT_SECONDS = 210

#: If Flow has not even *asked* its backend to render by now, it never will. The
#: submit reached the page but produced no generation call, and sitting out the
#: remaining timeout only delays the report. Generous on purpose (75s) to allow
#: Google Flow's model to register and render without premature aborts.
NO_REQUEST_GIVE_UP_SECONDS = 75.0

#: Playwright errors that mean "the page moved while you were talking to it".
#: These are retryable; anything else is a real scripting or page error and is
#: re-raised so it is not hidden behind a retry loop.
_TRANSIENT_EVAL_ERRORS = (
    "execution context was destroyed",
    "most likely because of a navigation",
    "navigating and changing the content",
    "frame was detached",
    "cannot find context with specified id",
)

#: Candidate selectors for Flow's prompt field, tried in order. The old code
#: clicked the fixed coordinate (640, 750) and typed into whatever had focus — so
#: a moved prompt bar meant the prompt was never entered, and Flow happily
#: re-rendered its previous request instead. Added generic fallbacks for recent Flow UI.
_PROMPT_SELECTORS = (
    'textarea[placeholder]',
    'div[contenteditable="true"]',
    'div[contenteditable]',
    'div[role="textbox"]',
    '[data-placeholder]',
    'textarea',
    'input[placeholder]:not([aria-label*="editable" i]):not([aria-label*="title" i])',
    '[placeholder]:not([aria-label*="editable" i]):not([aria-label*="title" i])',
)

#: Accessible names Flow's submit control has used. Tried before any geometry.
_SUBMIT_SELECTORS = (
    'button[aria-label*="generate" i]',
    'button[aria-label*="create" i]',
    'button[aria-label*="send" i]',
    'button[aria-label*="submit" i]',
    'button[aria-label*="arrow" i]',
    'button[type="submit"]',
)


class FlowGenerationError(RuntimeError):
    """Google Flow generation did not produce verifiable new images."""


def _is_transient_eval_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _TRANSIENT_EVAL_ERRORS)


async def _settle(page, timeout: int = 15000) -> None:
    """
    Wait for the document to be usable again, tolerating a navigation in flight.

    `wait_for_load_state` itself can raise while the SPA is mid-redirect, and a
    timeout here is not fatal — the caller's own retry decides that — so this
    never propagates.
    """
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=timeout)
    except PlaywrightError:
        pass


async def _safe_eval(page, script: str, arg=None, *, attempts: int = 4, what: str = "evaluate"):
    """
    Run `page.evaluate`, retrying when the page navigates underneath it.

    This is the fix for `Page.evaluate: Execution context was destroyed, most
    likely because of a navigation`: Flow finishes loading, then client-side
    routes to the canonical project URL, and any evaluate issued in that window
    is executing in a context that no longer exists. Waiting a fixed number of
    seconds after `goto` does not help, because the redirect is not tied to load.
    """
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            if arg is None:
                return await page.evaluate(script)
            return await page.evaluate(script, arg)
        except PlaywrightError as e:
            if not _is_transient_eval_error(e):
                raise
            last = e
            print(
                f"↻ [FLOW AUTOMATOR] {what}: page navigated mid-evaluate "
                f"(attempt {attempt}/{attempts}), waiting for it to settle..."
            )
            await _settle(page)
            await asyncio.sleep(1.5 * attempt)
    raise FlowGenerationError(
        f"Google Flow kept navigating while reading the page ({what}); gave up after "
        f"{attempts} attempts. Last error: {last}"
    )


async def _goto_settled(page, url: str, timeout: int = 45000, settle: float = 2.0) -> None:
    """`goto` plus a real load wait, instead of `goto` plus a hopeful sleep."""
    await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
    await _settle(page)
    await asyncio.sleep(settle)


async def _debug_shot(page, name: str) -> str | None:
    """
    Save a screenshot for a failure that needs eyes on it. Never raises.

    A submit that does not register leaves no trace in any log — the only useful
    record is what the page looked like at that moment.
    """
    try:
        debug_dir = Path("./data/debug").resolve()
        debug_dir.mkdir(parents=True, exist_ok=True)
        path = debug_dir / f"{name}.png"
        await page.screenshot(path=str(path))
        print(f"📷 [FLOW AUTOMATOR] Screenshot: data/debug/{path.name}")
        return str(path)
    except Exception as e:  # noqa: BLE001 — a missing screenshot must not mask the failure
        print(f"⚠️ [FLOW AUTOMATOR] Could not save the {name} screenshot: {e}")
        return None


async def _close_quietly(ctx) -> None:
    """
    Close the persistent browser context without masking the real error.

    Every failure path calls this before raising: the persistent profile holds the
    Google login, and being killed by the driver on the way out instead of closed
    leaves an unflushed profile plus a Chromium window on the operator's screen,
    which is what the next run's "profile lock" retries were cleaning up after.
    """
    try:
        await ctx.close()
    except Exception as e:  # noqa: BLE001 — teardown must not replace the failure
        print(f"Notice closing Flow browser: {e}")


def _kill_stale_flow_chrome() -> None:
    """
    Kill only the Chromium processes bound to our Flow profile directory.

    The previous implementation ran `taskkill /F /IM chrome.exe`, which also
    closed every personal Chrome window the operator had open.
    """
    kill_chrome_for_profile(PROFILE_DIR)


# ── the project workspace ───────────────────────────────────────────────

#: Everything worth knowing about the Flow home page in one round trip: the
#: projects it names, whether anyone is signed in, and the controls it is
#: offering. Read repeatedly while the page hydrates, so it must be cheap and
#: must never throw on a half-built DOM.
_JS_PROJECT_STATE = """
() => {
    const abs = (href) => { try { return new URL(href, location.href).href; } catch (e) { return null; } };
    const linked = Array.from(document.querySelectorAll('a[href]'))
        .map(a => abs(a.getAttribute('href')))
        .filter(h => h && h.indexOf('/project/') !== -1);
    // A project can be named in the document without ever being an <a href>:
    // Flow's dashboard cards are divs with click handlers, and the ids arrive in
    // the Next.js payload. Reading them out of the markup finds those too.
    const embedded = (document.documentElement.innerHTML
        .match(/\\/fx\\/tools\\/flow\\/project\\/[0-9a-zA-Z_-]{16,}/g) || [])
        .map(path => 'https://labs.google' + path);
    const text = (document.body ? document.body.innerText : '') || '';
    const labels = Array.from(document.querySelectorAll('button, a, [role="button"]'))
        .map(el => ((el.getAttribute('aria-label') || '') + ' ' + (el.innerText || ''))
            .replace(/\\s+/g, ' ').trim())
        .filter(t => t && t.length < 60)
        .slice(0, 30);
    return {
        url: location.href,
        title: document.title,
        projects: Array.from(new Set(linked.concat(embedded))).slice(0, 10),
        signed_in: !!document.querySelector(
            'a[href*="SignOutOptions"], img[alt*="ccount" i], [aria-label*="Google Account" i]'),
        sign_in_offered: /\\bsign in\\b|\\bsign into\\b|\\blog in\\b/i.test(text),
        new_project_offered: /new project|create project|blank project/i.test(text),
        labels: labels,
    };
}
"""

#: Accessible names Flow's "make me a workspace" control has used.
_NEW_PROJECT_PATTERNS = (
    "New project", "New Project", "Create project", "Blank project", "Start new project",
)


def _is_project_url(url: str | None) -> bool:
    """
    True for a workspace URL, false for the dashboard.

    The old check was `"project" not in page.url`, which the dashboard itself can
    satisfy — it is the page that lists *projects*. Only `/project/<id>` is a
    workspace with a prompt bar in it.
    """
    return "/project/" in (url or "")


def _remembered_project_url() -> str | None:
    """The workspace that opened cleanly last time, if one did."""
    try:
        data = json.loads(PROJECT_MEMO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    url = str(data.get("project_url") or "")
    return url if _is_project_url(url) else None


def _remember_project_url(url: str) -> None:
    """
    Cache a workspace that worked, so discovery only has to succeed once.

    Never fatal: an unwritable data directory must not fail a generation that has
    already found its project.
    """
    try:
        PROJECT_MEMO.parent.mkdir(parents=True, exist_ok=True)
        PROJECT_MEMO.write_text(
            json.dumps(
                {
                    "project_url": url,
                    "remembered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "note": "Written by flow_automator after a project opened cleanly. "
                            "Delete this file to force re-discovery.",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError as e:  # noqa: BLE001 — a cache miss is not a generation failure
        print(f"⚠️ [FLOW AUTOMATOR] Could not remember the project URL: {e}")


def _forget_project_url() -> None:
    """Drop the cache when the remembered project no longer opens (renamed, deleted)."""
    with contextlib.suppress(OSError):
        PROJECT_MEMO.unlink(missing_ok=True)


async def _project_state(page) -> dict:
    """Read `_JS_PROJECT_STATE`, tolerating a navigation mid-read."""
    state = await _safe_eval(page, _JS_PROJECT_STATE, what="read the Flow dashboard")
    return state if isinstance(state, dict) else {}


async def _wait_for_project_route(page, seconds: float = PROJECT_ROUTE_SECONDS) -> bool:
    """
    Wait for Flow's router to land inside a project.

    `goto` resolves on `domcontentloaded`, and Flow then routes client-side to the
    canonical workspace URL. Reading `page.url` immediately after the goto reads
    the address of a page that is already on its way somewhere else — which is why
    a single post-goto check reported "landed on .../tools/flow" for a navigation
    that was, a second later, inside the project.
    """
    deadline = asyncio.get_event_loop().time() + seconds
    while asyncio.get_event_loop().time() < deadline:
        if _is_project_url(page.url):
            return True
        await asyncio.sleep(0.5)
    return _is_project_url(page.url)


async def _discover_project(
    page, seconds: float = PROJECT_DISCOVERY_SECONDS
) -> tuple[list[str], dict]:
    """
    Poll the dashboard until it names a project, or the budget runs out.

    Polling is the whole fix. The dashboard's project list is fetched after the
    document loads, so the answer to "does this account have a project?" is "not
    yet" for the first few seconds — and the previous code asked exactly once.

    Returns every workspace URL the page named, most promising first, because a
    project can be listed and still refuse to open (deleted, or another account's).
    """
    deadline = asyncio.get_event_loop().time() + seconds
    state: dict = {}
    while True:
        state = await _project_state(page)
        if _is_project_url(state.get("url")):
            return [str(state["url"])], state
        named = [p for p in (state.get("projects") or []) if _is_project_url(p)]
        if named:
            return named, state
        if asyncio.get_event_loop().time() >= deadline:
            return [], state
        await asyncio.sleep(1.5)


async def _click_new_project(page) -> bool:
    """
    Last resort: ask Flow for a workspace, and confirm one opened.

    Deliberately after discovery, never before. A dashboard that is merely slow
    must not cause a second project to pile up beside the first — the operator has
    already complained about test images accumulating in one workspace, and a run
    that quietly makes a new one every time is worse.
    """
    for pattern in _NEW_PROJECT_PATTERNS:
        for selector in (
            f'button:has-text("{pattern}")',
            f'a:has-text("{pattern}")',
            f'[role="button"]:has-text("{pattern}")',
        ):
            loc = page.locator(selector).first
            try:
                if await loc.count() == 0:
                    continue
                await loc.scroll_into_view_if_needed(timeout=3000)
                await loc.click(timeout=5000)
            except PlaywrightError:
                continue
            print(f"🆕 [FLOW AUTOMATOR] Clicked {pattern!r} to create a workspace.")
            if await _wait_for_project_route(page):
                return True
    return False


async def _open_project(page, job_id: str) -> str:
    """
    Get the browser into a Flow project workspace using the Flow Router pool.

    Rotates across the pool of configured Google Flow projects to prevent
    any single canvas from bloating with too many images.
    """
    tried: list[str] = []

    # 1. Flow Project Router pool (round-robin / load-balanced across 10+ projects)
    try:
        from app.services.flow_router import get_all_project_candidates, record_project_verified
        candidates = get_all_project_candidates(job_id=job_id)
    except Exception as e:
        logger.warning("Could not load flow_router pool: %s", e)
        candidates = [settings.flow_project_url] if settings.flow_project_url else []

    for idx, candidate in enumerate(candidates, 1):
        if not candidate:
            continue
        proj_uuid = candidate.rstrip("/").split("/")[-1]
        tried.append(f"Router Project #{idx} ({proj_uuid})")
        print(f"📂 [FLOW AUTOMATOR] Opening Flow Router project #{idx}/{len(candidates)}: {candidate}...")
        with contextlib.suppress(PlaywrightError):
            await _goto_settled(page, candidate, timeout=45000, settle=2.0)
            if await _wait_for_project_route(page):
                print(f"✅ [FLOW AUTOMATOR] Active Workspace: {page.url}")
                with contextlib.suppress(Exception):
                    record_project_verified(page.url, job_id=job_id)
                return page.url
        print(f"⚠️ [FLOW AUTOMATOR] Project #{idx} ({proj_uuid}) did not open cleanly. Rotating to next project...")

    # 2. Fallback: remember last working URL
    rem = _remembered_project_url()
    if rem and rem not in candidates:
        tried.append(f"remembered ({rem})")
        print(f"📂 [FLOW AUTOMATOR] Opening remembered workspace: {rem}...")
        with contextlib.suppress(PlaywrightError):
            await _goto_settled(page, rem, timeout=45000, settle=2.0)
            if await _wait_for_project_route(page):
                return page.url
        _forget_project_url()

    await _goto_settled(page, FLOW_URL, timeout=45000)
    # Flow often restores the last workspace by itself; six seconds is enough to
    # see that happen, and skips the dashboard read entirely when it does.
    if await _wait_for_project_route(page, seconds=6.0):
        _remember_project_url(page.url)
        return page.url

    found, state = await _discover_project(page)
    tried.append(f"dashboard discovery ({PROJECT_DISCOVERY_SECONDS:.0f}s poll, "
                 f"{len(found)} named)")
    # More than one candidate is tried because a listed project can still refuse to
    # open — deleted, or belonging to another signed-in account.
    for candidate in found[:3]:
        print(f"📂 [FLOW AUTOMATOR] The dashboard named {candidate}; opening it...")
        with contextlib.suppress(PlaywrightError):
            await _goto_settled(page, candidate, timeout=45000)
            if await _wait_for_project_route(page):
                _remember_project_url(page.url)
                print(f"💡 [FLOW AUTOMATOR] Put FLOW_PROJECT_URL={page.url} in .env "
                      "to skip this search entirely.")
                return page.url

    # Signed out is a different problem with a different fix, and it used to be
    # reported as "create one project in Flow" — advice the operator cannot follow
    # in a browser profile that is not logged in.
    if not state.get("signed_in") and state.get("sign_in_offered"):
        await _debug_shot(page, f"flow_signed_out_{job_id[:8]}")
        raise FlowGenerationError(
            "The Google Flow browser profile is signed out, so it has no projects to open. "
            "Sign in once in that profile — run `python scripts/login_google_flow.py`, go to "
            f"{FLOW_URL}, finish the Google login, open a project, then close the window — "
            f"and run the job again. Page title: {(state.get('title') or '?')!r} at "
            f"{state.get('url') or page.url}"
        )

    if await _click_new_project(page):
        _remember_project_url(page.url)
        print(f"💡 [FLOW AUTOMATOR] Put FLOW_PROJECT_URL={page.url} in .env "
              "to skip this search entirely.")
        return page.url
    tried.append("clicking a New project control")

    shot = await _debug_shot(page, f"flow_no_project_{job_id[:8]}")
    raise FlowGenerationError(
        "Could not open a Google Flow project workspace. Tried: " + "; ".join(tried) + ". "
        f"Landed on {page.url} — title {(state.get('title') or '?')!r}, "
        f"signed_in={bool(state.get('signed_in'))}, "
        f"projects named by the page: {len(state.get('projects') or [])}, "
        f"controls seen: {', '.join((state.get('labels') or [])[:8]) or 'none'}. "
        "Fix: open Flow in that Chromium profile, open or create one project, and put its "
        "URL in FLOW_PROJECT_URL in .env."
        + (f" Screenshot: {shot}" if shot else "")
    )


class _GenerationWatcher:
    """
    Listens for Flow's answer to *our* submit and harvests the media it names.

    This is the whole attribution mechanism. It is armed immediately before the
    submit click, so nothing the page fetched while loading the project canvas can
    be mistaken for output, and it only reads bodies from URLs that look like a
    generation call — a listing or hydration response describes media that already
    existed, and crediting one to the job is the original bug.

    Response handlers must not block Playwright's event loop, so `_on_response`
    only schedules the body read; `drain()` waits for those tasks before the
    caller inspects the result.
    """

    def __init__(self, page) -> None:
        self._page = page
        self._pending: set[asyncio.Task] = set()
        #: The endpoint path recorded by the 1-Time Session Capture, if there is
        #: one. It is the operator's *real* endpoint, so it is trusted even if a
        #: Google rename makes the generic markers miss.
        self._capture_path = captured_generation_path()
        self.armed = False
        self.harvest = MediaHarvest()
        #: Key-only outlines of every generation response, for the error message.
        self.shapes: list[str] = []
        #: Diagnostics: which endpoints answered, so a marker that stops matching
        #: is visible from one failed run instead of needing a re-investigation.
        self.generation_paths: list[str] = []
        self.json_paths: list[str] = []
        #: Paths of requests that *left the browser* after arming. Response-level
        #: diagnostics cannot tell "we never submitted" from "we submitted and Flow
        #: answered on an endpoint we do not recognise" — this can.
        self.request_paths: list[str] = []
        self.generation_requests: list[str] = []
        self.notes: list[str] = []
        #: Per-variation records (mediaGenerationId + bytes/URL), for the 2K
        #: upsample call. Filled alongside `harvest` in `_read`.
        self.variations: list = []
        #: Auth context captured from the generation *request*: the upsample
        #: endpoint is sibling to it and accepts the same credentials. Never
        #: logged — the authorization header is a live OAuth token.
        self.request_headers: dict = {}
        self.project_id: str | None = None
        self.api_base: str | None = None

    # ── wiring ─────────────────────────────────────────────────────────
    def attach(self) -> None:
        self._page.on("response", self._on_response)
        self._page.on("request", self._on_request)

    def detach(self) -> None:
        with contextlib.suppress(Exception):
            self._page.remove_listener("response", self._on_response)
        with contextlib.suppress(Exception):
            self._page.remove_listener("request", self._on_request)

    def arm(self) -> None:
        """Start accepting responses. Called just before the submit click."""
        self.armed = True

    def _on_request(self, request) -> None:
        """Record what we asked Flow for. Cheap: headers only, never a body."""
        if not self.armed:
            return
        try:
            if (getattr(request, "method", "") or "").upper() != "POST":
                return
            url = getattr(request, "url", "") or ""
        except Exception:  # noqa: BLE001 — diagnostics must never break the run
            return
        path = endpoint_path(url)
        if path not in self.request_paths and len(self.request_paths) < 40:
            self.request_paths.append(path)
        if self._is_generation(url):
            if path not in self.generation_requests:
                self.generation_requests.append(path)
                print(f"📨 [FLOW AUTOMATOR] Generation request sent to {path}.")
            if not self.request_headers:
                self._capture_request_auth(request, url)

    def _capture_request_auth(self, request, url: str) -> None:
        """
        Stash the generation request's auth so the 2K upsample call can reuse it.

        `request.headers` is a sync property and `request.post_data` the JSON
        body; both are read here, in the request event, because the request
        object is not guaranteed to outlive the handler. Anything learned here
        is used only in-memory and never written to logs or disk.
        """
        try:
            headers = {str(k).lower(): str(v) for k, v in (request.headers or {}).items()}
        except Exception:  # noqa: BLE001 — diagnostics must never break the run
            return
        if not headers.get("authorization"):
            return
        from app.services.flow_upscale import api_base_from_generation_url

        project_id = None
        try:
            post = request.post_data
            if post:
                payload = json.loads(post)
                ctx = payload.get("clientContext") or {}
                if isinstance(ctx, dict):
                    project_id = ctx.get("projectId") or None
        except Exception:  # noqa: BLE001 — missing projectId only weakens the upsample call
            project_id = None
        self.request_headers = headers
        self.project_id = project_id
        self.api_base = api_base_from_generation_url(url)

    async def drain(self, timeout: float = 20.0) -> None:
        """Let in-flight body reads finish before the result is judged."""
        if not self._pending:
            return
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(
                asyncio.gather(*list(self._pending), return_exceptions=True), timeout
            )

    # ── classification ─────────────────────────────────────────────────
    def _is_generation(self, url: str) -> bool:
        if looks_like_generation_url(url):
            return True
        return bool(self._capture_path and self._capture_path in url)

    def _on_response(self, response) -> None:
        if not self.armed:
            return
        url = getattr(response, "url", "") or ""
        path = endpoint_path(url)

        # Headers are already in memory; bodies are not. Note JSON endpoints
        # cheaply so a failure can say what Flow *did* answer.
        try:
            content_type = (response.headers or {}).get("content-type", "")
        except Exception:  # noqa: BLE001 — diagnostics must never break the run
            content_type = ""
        if "json" in content_type.lower() and path not in self.json_paths:
            if len(self.json_paths) < 40:
                self.json_paths.append(path)

        # Directly catch image responses from Flow's content CDN
        if "flow-content.google/image" in url:
            # Only a fresh 200 can be this run's render: a 304 revalidation or
            # an error page belongs to a canvas card that already existed.
            if getattr(response, "status", 0) != 200:
                return
            ident = media_identifier(url)
            existing_ids = {media_identifier(u) for u in self.harvest.urls}
            if ident not in existing_ids:
                self.harvest.urls.append(url)
                print(f"📡 [FLOW AUTOMATOR] Captured generated image directly from CDN: {url[:70]}...")
            return

        if not self._is_generation(url):
            return
        if path not in self.generation_paths:
            self.generation_paths.append(path)

        task = asyncio.create_task(self._read(response, path))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _read(self, response, path: str) -> None:
        status = getattr(response, "status", 0)
        if status >= 400:
            self.notes.append(f"{path} answered HTTP {status}")
            return
        payload = None
        raw_text = None
        try:
            payload = await response.json()
        except Exception as e:
            # Batchexecute responses use )]}' anti-XSSI header or raw text
            try:
                raw_text = await response.text()
            except Exception as e_text:
                self.notes.append(f"{path}: body was not JSON or readable text ({type(e).__name__}, {type(e_text).__name__})")
                return

        before = self.harvest.total
        if payload is not None:
            harvest_media(payload, self.harvest)
            try:
                self.variations.extend(harvest_variations(payload))
            except Exception:
                self.variations = self.variations or []
            self.shapes.append(describe_shape(payload))
        elif raw_text:
            harvest_media(raw_text, self.harvest)
            self.shapes.append(f"raw_text[{len(raw_text)} chars]")

        gained = self.harvest.total - before
        if gained:
            print(
                f"📡 [FLOW AUTOMATOR] {path} → HTTP {status}, "
                f"{gained} media reference(s) attributable to this submit."
            )


# ── talking to the prompt bar ───────────────────────────────────────────

_JS_READ_FOCUSED = """
    () => {
        const el = document.activeElement;
        if (!el) return null;
        const value = (el.value !== undefined && el.value !== null) ? el.value : (el.innerText || "");
        return { tag: el.tagName, text: String(value) };
    }
"""

_JS_FIND_SUBMIT = """
    () => {
        const field = document.activeElement;
        const rect = (field && field.getBoundingClientRect) ? field.getBoundingClientRect() : null;
        // Material Symbols render their ligature name as text, so a button's
        // innerText is often the icon name. That is how a run clicked the
        // "image" (add reference) button and waited 210s for a generation that
        // was never requested.
        const SEND = ['arrow_forward', 'arrow_upward', 'send', 'north', 'play_arrow',
                      'generate', 'create', 'auto_awesome', 'subdirectory_arrow_left'];
        const NOT_SEND = ['image', 'add', 'add_photo_alternate', 'attach_file', 'attachment',
                          'mic', 'settings', 'tune', 'more_vert', 'more_horiz', 'close',
                          'delete', 'upload', 'photo', 'photo_library', 'video_library',
                          'movie', 'help', 'account_circle', 'menu', 'expand_more',
                          'expand_less', 'arrow_drop_down', 'keyboard_arrow_down',
                          'history', 'download', 'edit', 'search', 'share', 'star'];
        const describe = (el) => {
            const aria = String(el.getAttribute('aria-label') || '').trim();
            const text = String(el.innerText || '').trim().split('\\n')[0];
            return { aria, icon: text, key: (aria || text).toLowerCase() };
        };
        let pool = Array.from(document.querySelectorAll('button, [role="button"]'))
            .map(el => ({ el, r: el.getBoundingClientRect(), d: describe(el) }))
            .filter(({ el, r }) => r.width > 8 && r.height > 8 && !el.disabled
                                   && r.bottom > 0 && r.top < innerHeight);
        if (!pool.length) return { candidates: [], considered: 0 };
        const considered = pool.length;
        if (rect) {
            const near = pool.filter(({ r }) =>
                r.top >= rect.top - 60 && r.bottom <= rect.bottom + 120 && r.left >= rect.left - 30);
            if (near.length) pool = near;
        }
        const score = ({ d, r }) => {
            const key = d.key.replace(/[^a-z_ ]/g, '');
            let s = 0;
            if (SEND.some(w => key.includes(w))) s += 100;
            if (NOT_SEND.some(w => key === w || key.startsWith(w + ' '))) s -= 80;
            if (!d.aria && !d.icon) s += 5;          // bare icon-only send arrows exist
            s += Math.min(r.right / 100, 20);        // the send control sits right-most
            return s;
        };
        pool.sort((a, b) => score(b) - score(a));
        return {
            considered,
            candidates: pool.slice(0, 4).map(({ el, r, d }) => ({
                x: r.left + r.width / 2,
                y: r.top + r.height / 2,
                label: (d.aria || d.icon || 'unlabelled').slice(0, 40),
                score: score({ d, r }),
            })),
        };
    }
"""

#: Anything Flow puts on screen that explains a refusal (prompt too long, policy,
#: quota). Scraped only when a run has already failed.
_JS_PAGE_ALERTS = """
    () => {
        const out = [];
        const push = (t) => {
            const s = String(t || '').replace(/\\s+/g, ' ').trim();
            if (s && s.length < 200 && !out.includes(s)) out.push(s);
        };
        document.querySelectorAll('[role="alert"], [role="status"], [aria-live]').forEach(
            el => push(el.innerText));
        const body = document.body ? document.body.innerText : '';
        body.split('\\n').forEach(line => {
            if (/too long|not allowed|policy|violat|limit|quota|try again|error|failed|unable/i
                .test(line)) push(line);
        });
        return out.slice(0, 8);
    }
"""


def _norm(text: str) -> str:
    """Collapse whitespace and case, so a soft-wrapped read-back still compares."""
    return " ".join(str(text).split()).lower()


#: What separates two compiled sections once the prompt is flattened to one line.
SECTION_SEPARATOR = " | "


def flatten_prompt(prompt: str) -> str:
    """
    Collapse the compiled prompt onto ONE line for Flow's prompt bar.

    This is the fix for the failure that looked like "the prompt did not land in
    Google Flow's prompt field (256 of 2040 characters present)".

    Flow's prompt bar is a contenteditable where **Enter means send**. The compiled
    prompt is 13 sections separated by blank lines, and `keyboard.type` sends every
    `\\n` as a real Enter key press — so typing the prompt submitted
    `PHOTOGRAPHIC INTENT: …` as its own generation, cleared the box, submitted
    `SUBJECT: …`, and so on. What survived in the field was only the text after the
    final newline, which is why the read-back saw 256 characters of a 2040-character
    prompt, and why the project canvas filled up with renders of prompt fragments —
    one of the images the operator was shown was a picture of the words "AVOID:".

    Newlines carry no meaning to the image model that a separator cannot carry, so
    they are removed rather than escaped. The result is guaranteed newline-free;
    `_enter_prompt` refuses to send anything that is not.
    """
    sections = (" ".join(part.split()) for part in str(prompt).split("\n\n"))
    return SECTION_SEPARATOR.join(part for part in sections if part)


async def _find_prompt_box(page):
    """
    Locate Flow's prompt field, or return `(None, "")`.

    Selector-based, because the old fixed-coordinate click at (640, 750) typed into
    whatever happened to have focus. When the layout shifted, the prompt went
    nowhere and Flow re-rendered its *previous* request — a run that looks
    successful and produces images for someone else's brief. Now waits up to 25s
    for the bar to hydrate, because Flow's React hydrates the prompt bar after
    domcontentloaded (seen in b9b472cb failure).
    """
    # Poll for up to 25s — Flow's dashboard hydrates project list + prompt bar after load
    # User reports bar is below fold and invisible at 850px height, so scroll to bottom
    # and accept enabled-but-not-visible candidates after scrolling into view.
    deadline = asyncio.get_event_loop().time() + 25.0
    last_error = ""
    # Ensure we start at bottom where Flow pins the prompt bar
    with contextlib.suppress(PlaywrightError):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(0.5)
    while asyncio.get_event_loop().time() < deadline:
        for selector in _PROMPT_SELECTORS:
            locator = page.locator(selector)
            try:
                found = await locator.count()
            except PlaywrightError as e:
                last_error = str(e)
                continue
            for index in range(min(found, 6)):
                candidate = locator.nth(index)
                try:
                    # Scroll each candidate into view — bar is fixed at bottom and 850px viewport hides it
                    with contextlib.suppress(PlaywrightError):
                        await candidate.scroll_into_view_if_needed(timeout=2000)
                    # Accept enabled candidates even if is_visible is still false due to sticky footer
                    if await candidate.is_enabled():
                        # Double-check it has some size (not display:none)
                        box = await candidate.bounding_box()
                        if box and box["width"] > 100 and box["height"] > 15:
                            # Skip editable text inputs from header / project title
                            aria = (await candidate.get_attribute("aria-label") or "").lower()
                            if "editable" in aria or "title" in aria:
                                continue
                            return candidate, f"{selector} [{index}]"
                except PlaywrightError as e:
                    last_error = str(e)
                    continue
        await asyncio.sleep(1.0)
        # Nudge scroll — some Flow layouts hide the bar off-viewport until scrolled
        with contextlib.suppress(PlaywrightError):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.3)
            await page.mouse.wheel(0, -150)
    print(f"⚠️ [FLOW AUTOMATOR] Prompt field not found after 25s (last: {last_error}) — dumping candidates")
    # Final debug: list what *is* on the page
    try:
        debug = await _safe_eval(page, """() => {
            const els = Array.from(document.querySelectorAll('textarea, [contenteditable], [role="textbox"], input'));
            return els.slice(0,8).map(e => `${e.tagName}[${(e.getAttribute('placeholder')||e.getAttribute('role')||e.contentEditable||'').slice(0,30)}] visible=${!!e.offsetParent}`);
        }""", what="list prompt candidates")
        print(f"   candidates: {debug}")
    except Exception:
        pass
    return None, ""


async def _read_prompt_field(page, box) -> str:
    """
    Read back what is actually in the prompt field.

    `document.activeElement` is tried first because Flow's editor sometimes moves
    focus into an inner node, and that inner node is what holds the text. If the
    focused element turns out to be empty (focus moved to a toolbar button, say)
    the located element is read directly, so a read-back failure never masquerades
    as an empty prompt field.
    """
    focused = await _safe_eval(page, _JS_READ_FOCUSED, what="read back the prompt field")
    text = str((focused or {}).get("text") or "")
    if text.strip():
        return text
    try:
        return str(await box.evaluate(
            "el => (el.value !== undefined && el.value !== null) ? el.value : (el.innerText || '')"
        ) or "")
    except PlaywrightError:
        return text


async def _paste_reference_image(page, box, image_path: Path) -> bool:
    """
    Paste the reference image DIRECTLY into the prompt box (the easy way).

    Flow's prompt bar accepts an image paste: the image uploads and then
    automatically appears as a thumbnail chip inside the prompt box.
    Note: Chrome's navigator.clipboard.write ONLY supports image/png MIME type.
    We convert any image (JPG/WebP/PNG) to PNG in memory before writing to clipboard.
    After pasting, waits a full 35 seconds for Google Flow's backend to
    process, upload, and embed the image chip before the text prompt is entered.
    """
    image_file = Path(image_path).resolve()
    if not image_file.exists():
        print(f"⚠️ [FLOW AUTOMATOR] Reference image not found: {image_file}")
        return False

    # Ensure clipboard permissions for image paste
    try:
        ctx = page.context
        await ctx.grant_permissions(["clipboard-read", "clipboard-write"])
    except Exception:
        pass

    # Read image and convert to PNG in-memory (Chrome Clipboard API strictly requires image/png)
    try:
        from PIL import Image
        import io

        im = Image.open(image_file).convert("RGB")
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        png_bytes = buf.getvalue()
        b64 = base64.b64encode(png_bytes).decode("utf-8")
        mime = "image/png"
    except Exception as e:
        print(f"⚠️ [FLOW AUTOMATOR] Could not prepare reference image for clipboard: {e}")
        return False

    # Scroll prompt box into view and focus it
    try:
        await box.scroll_into_view_if_needed()
        await box.click()
        await asyncio.sleep(0.4)
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Backspace")
        await asyncio.sleep(0.3)
    except PlaywrightError:
        pass

    # Write PNG image blob to clipboard via ClipboardItem, then Ctrl+V
    pasted = False
    for attempt in range(3):
        try:
            await page.evaluate(
                """async ([b64, mime]) => {
                    const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
                    const blob = new Blob([bytes], {type: mime});
                    const item = new ClipboardItem({[mime]: blob});
                    await navigator.clipboard.write([item]);
                    return true;
                }""",
                [b64, mime],
            )
            await box.click()
            await asyncio.sleep(0.3)
            await page.keyboard.press("Control+V")
            print(f"📎 [FLOW AUTOMATOR] Pasted reference image {image_file.name} (converted to PNG: {len(png_bytes)//1024} KB) into prompt box (attempt {attempt+1})...")
            pasted = True
            break
        except Exception as e:
            print(f"⚠️ [FLOW AUTOMATOR] Clipboard write attempt {attempt+1} failed: {e}")
            await asyncio.sleep(0.8)

    # Wait full 40 seconds for Google Flow backend to fully ingest & embed image chip
    total_wait = 40
    print(f"⏳ [FLOW AUTOMATOR] Reference image pasted! Waiting {total_wait} seconds for Google Flow to process & embed the image chip...")
    for elapsed in range(5, total_wait + 1, 5):
        await asyncio.sleep(5)
        print(f"⏳ [FLOW AUTOMATOR] Image upload processing: {elapsed}/{total_wait} seconds...")

    print(f"✅ [FLOW AUTOMATOR] Image upload wait ({total_wait}s) complete. Ready to enter prompt text.")
    return True


async def _enter_prompt(page, prompt: str, reference_image: Path | None = None):
    """
    Put `prompt` (and optionally `reference_image`) into Flow's prompt field and prove it arrived.

    Image+prompt workflow:
      1. Paste the reference image FIRST into the prompt box (Ctrl+V).
      2. Wait 40s for Google Flow to process and embed the image chip.
      3. Focus the prompt box and PASTE prompt text via clipboard (Ctrl+V) WITHOUT erasing the chip.
      4. Verify prompt arrived in the box.

    Returns `(box, flat)` — the field the text went into and the one-line prompt.
    """
    box, where = await _find_prompt_box(page)
    if box is None:
        raise FlowGenerationError(
            "Could not find Google Flow's prompt field on the page "
            f"(tried {', '.join(_PROMPT_SELECTORS)}). Nothing was submitted."
        )
    print(f"⌨️ [FLOW AUTOMATOR] Prompt field: {where}")

    # ── STEP 1: Paste reference image FIRST if provided ──────────────────
    if reference_image and Path(reference_image).exists():
        print(f"🖼️ [FLOW AUTOMATOR] Step 1: Pasting reference image {Path(reference_image).name} first...")
        await _paste_reference_image(page, box, Path(reference_image))
    else:
        print("ℹ️ [FLOW AUTOMATOR] No reference image specified or file not found; generating text-only.")

    flat = flatten_prompt(prompt)
    if "\n" in flat or "\r" in flat:
        raise FlowGenerationError(
            "Refusing to send a prompt containing a newline to Flow's prompt bar: "
            "Enter is its send key, so the prompt would submit itself in pieces."
        )
    if not flat:
        raise FlowGenerationError("The compiled prompt is empty; nothing was submitted.")

    # ── STEP 2: Focus prompt box for text ────────────────────────────────
    await box.click()
    await asyncio.sleep(0.4)

    # If NO image was pasted, clear previous text.
    # If image WAS pasted, do NOT press Ctrl+A/Backspace to avoid deleting the image chip!
    if not reference_image or not Path(reference_image).exists():
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Backspace")
        await asyncio.sleep(0.2)

    # ── STEP 3: PASTE prompt text via clipboard (Ctrl+V) ─────────────────
    pasted_prompt = False
    try:
        await page.evaluate(
            """async (text) => {
                await navigator.clipboard.writeText(text);
                return true;
            }""",
            flat,
        )
        await box.click()
        await asyncio.sleep(0.3)
        await page.keyboard.press("Control+V")
        await asyncio.sleep(0.8)
        print("📋 [FLOW AUTOMATOR] Step 2: Prompt pasted via clipboard (Ctrl+V) into prompt box.")
        pasted_prompt = True
    except Exception as e:
        print(f"⚠️ [FLOW AUTOMATOR] Clipboard writeText failed ({e}); using insert_text fallback...")
        how = await insert_text(page, flat)
        print(f"⌨️ [FLOW AUTOMATOR] Step 2: Prompt delivered via {how}.")
        await asyncio.sleep(0.8)

    entered = _norm(await _read_prompt_field(page, box))
    wanted = _norm(flat)
    opening = wanted[:80]

    if not entered or (opening and opening not in entered):
        raise FlowGenerationError(
            "The prompt did not land in Google Flow's prompt field "
            f"({len(entered)} of {len(wanted)} characters present). Submitting now "
            "would re-run whatever Flow had in the box, so nothing was submitted."
        )
    if len(entered) < len(wanted) * 0.8:
        print(
            f"⚠️ [FLOW AUTOMATOR] Prompt field holds {len(entered)} of {len(wanted)} "
            "characters — Flow may cap prompt length."
        )
    else:
        print(f"✅ [FLOW AUTOMATOR] Prompt in the box: {len(entered)} characters, one line.")
    return box, flat


#: How long to wait for proof that a submit actually took. Flow's own generation
#: POST leaves the browser within a second or two of a real submit; the *response*
#: can take minutes, so waiting for the response to decide is what turned a missed
#: click into a silent 210 s stall.
SUBMIT_CONFIRM_SECONDS = 12.0


async def _submit_landed(page, box, watcher, wanted_len: int, seconds: float) -> str | None:
    """
    Wait for evidence that Flow accepted a submit. Returns the evidence, or None.

    Two independent signals, either of which is proof:

    * a generation request left the browser (`watcher.generation_requests`) — the
      request, not the response, because the response is the render;
    * the prompt bar emptied, which Flow does when it accepts a prompt.

    If neither appears the submit did **not** take, and re-trying a different
    control is safe precisely because the prompt is still sitting in the box.
    """
    deadline = asyncio.get_event_loop().time() + seconds
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.6)
        if watcher.generation_requests:
            return f"generation request to {watcher.generation_requests[0]}"
        if watcher.harvest.total:
            return "media already named by Flow"
        current = _norm(await _read_prompt_field(page, box))
        if len(current) < max(20, int(wanted_len * 0.3)):
            return "prompt bar cleared"
    return None


async def _submit_prompt(page, box, watcher, wanted_len: int) -> str:
    """
    Get Flow to accept the prompt, and prove it did. Returns what worked.

    **Enter first, deliberately.** Flow's prompt bar sends on Enter — that is not a
    guess, it is what an earlier bug proved by submitting a 13-section prompt in
    thirteen pieces. One deliberate Enter is therefore more reliable than any
    button hunt, and it cannot land on the wrong control.

    The button hunt is the fallback, and it is now *scored*: Material Symbols
    render their ligature name as text, so the previous "right-most button in the
    prompt bar" rule clicked a button whose label was `image` — Flow's add-reference
    control — and the run then waited out its whole timeout for a generation nobody
    had requested.

    Every strategy is followed by `_submit_landed`; an unconfirmed strategy is not
    treated as a submit, which is what makes trying the next one safe.
    """
    attempted: list[str] = []

    async def confirm(label: str) -> str | None:
        evidence = await _submit_landed(page, box, watcher, wanted_len, SUBMIT_CONFIRM_SECONDS)
        if evidence:
            return f"{label} (confirmed by {evidence})"
        attempted.append(label)
        print(f"⚠️ [FLOW AUTOMATOR] {label} did not register; the prompt is still in the box.")
        return None

    # 1. Enter, in the field we just verified.
    with contextlib.suppress(PlaywrightError):
        await box.click()
        await asyncio.sleep(0.2)
        await page.keyboard.press("Enter")
        landed = await confirm("Enter in the prompt field")
        if landed:
            return landed

    # 2. Ctrl+Enter / Meta+Enter, used by editors that treat Enter as newline.
    for combo in ("Control+Enter", "Meta+Enter"):
        with contextlib.suppress(PlaywrightError):
            await box.click()
            await asyncio.sleep(0.2)
            await page.keyboard.press(combo)
            landed = await confirm(combo)
            if landed:
                return landed

    # 3. Named controls, then scored geometry.
    for selector in _SUBMIT_SELECTORS:
        locator = page.locator(selector)
        try:
            found = await locator.count()
        except PlaywrightError:
            continue
        for index in range(min(found, 4)):
            candidate = locator.nth(index)
            try:
                if not (await candidate.is_visible() and await candidate.is_enabled()):
                    continue
                await candidate.click()
            except PlaywrightError:
                continue
            landed = await confirm(f"{selector} [{index}]")
            if landed:
                return landed

    found = await _safe_eval(page, _JS_FIND_SUBMIT, what="locate submit button") or {}
    for candidate in (found.get("candidates") or []):
        label = f"button {candidate.get('label')!r} at " \
                f"({candidate['x']:.0f}, {candidate['y']:.0f})"
        with contextlib.suppress(PlaywrightError):
            await page.mouse.click(candidate["x"], candidate["y"])
            landed = await confirm(label)
            if landed:
                return landed

    alerts = await _safe_eval(page, _JS_PAGE_ALERTS, what="read page alerts") or []
    await _debug_shot(page, "flow_submit_unconfirmed")
    raise FlowGenerationError(
        "Google Flow never registered a submit. Tried: "
        + ("; ".join(attempted) if attempted else "no usable control")
        + f". Buttons considered: {found.get('considered', 0)}."
        + (f" Page said: {' / '.join(alerts[:3])}." if alerts else "")
        + " Nothing was generated, and the prompt is still in the box — see "
          "data/debug/flow_submit_unconfirmed.png."
    )


# ── downloading what the response named ─────────────────────────────────


async def _fetch_media(page, url: str) -> bytes | None:
    """
    Download one media URL using the browser's credentials or direct CDN fetch.

    `page.request` shares the context's cookie jar, so this is an authenticated
    full-resolution fetch. For flow-content.google signed Cloud CDN URLs, direct
    HTTPS fetch with browser User-Agent is also used as a reliable fallback.
    """
    import re

    # Unescape any residual JSON/RPC escaping in query strings (e.g. \u0026 -> &)
    url = url.rstrip('\\"\'')
    url = url.replace(r'\u0026', '&').replace('\\u0026', '&').replace('&amp;', '&')
    url = url.replace(r'\u003d', '=').replace('\\u003d', '=')
    url = url.replace(r'\u003f', '?').replace('\\u003f', '?')

    # Upgrade /asb/ preview URLs to full resolution =s0
    if "/asb/" in url and "=s" in url:
        url = re.sub(r"=s\d+.*$", "=s0", url)

    # 1. Primary authenticated fetch via Playwright's page.request (shares context cookie jar)
    try:
        response = await page.request.get(url)
        if response.status == 200:
            body = await response.body()
            if len(body) >= MIN_IMAGE_BYTES:
                return body
            print(f"  Notice: media URL returned {len(body)} bytes, below {MIN_IMAGE_BYTES}.")
        else:
            print(f"  Notice: media URL returned HTTP {response.status}: {url[:80]}...")
    except Exception as e:  # noqa: BLE001 — the in-page fetch is the real fallback
        print(f"  Notice on authenticated fetch: {e}")

    # 2. Direct fetch fallback for any HTTP(S) URLs (including /asb/ CDN renders)
    if url.startswith("http"):
        try:
            import urllib.request
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"}
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                if resp.status == 200:
                    data = resp.read()
                    if len(data) >= MIN_IMAGE_BYTES:
                        return data
        except Exception as e:
            print(f"  Notice on urllib media fetch: {e}")

    # 3. In-page fetch using DOM fetch()
    try:
        encoded = await _safe_eval(page, """
            async (url) => {
                try {
                    const resp = await fetch(url);
                    if (!resp.ok) return null;
                    const bytes = new Uint8Array(await resp.arrayBuffer());
                    let binary = '';
                    for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
                    return btoa(binary);
                } catch {
                    return null;
                }
            }
        """, url, what="in-page media fetch")
    except (PlaywrightError, FlowGenerationError) as e:
        print(f"  Notice on in-page fetch: {e}")
        encoded = None

    if encoded:
        try:
            body = base64.b64decode(encoded)
            if len(body) >= MIN_IMAGE_BYTES:
                return body
        except (ValueError, TypeError):
            pass

    return None


async def _get_canvas_media_urls(page) -> list[str]:
    """
    Get all generated image URLs currently mounted on the Flow canvas.
    Excludes data: URIs, SVG icons, and avatars. Normalizes /asb/ URLs with =s0.
    """
    try:
        urls = await _safe_eval(page, """
            () => {
                const imgs = Array.from(document.querySelectorAll('img'));
                const results = [];
                for (const img of imgs) {
                    const src = img.src || img.currentSrc || '';
                    if (!src || src.startsWith('data:') || src.includes('avatar') || src.includes('googleusercontent.com/a/')) {
                        continue;
                    }
                    if (src.includes('/asb/') || src.includes('getMediaUrlRedirect') || src.includes('flow-content.google')) {
                        results.push(src);
                    }
                }
                return results;
            }
        """, what="get canvas media urls") or []
        normalized = []
        import re
        for u in urls:
            u_clean = re.sub(r'=s\d+.*$', '=s0', u) if '/asb/' in u else u
            if u_clean not in normalized:
                normalized.append(u_clean)
        return normalized
    except Exception as e:
        logger.warning("Could not read canvas media URLs: %s", e)
        return []


async def _save_harvest(
    page,
    harvest: MediaHarvest,
    output_dir: Path,
    job_id: str,
    count: int,
    *,
    variations: list | None = None,
    canvas_urls: list[str] | None = None,
    canvas_baseline_ids: set[str] | None = None,
    upscaler: Any = None,
    filename_prefix: str = "flow_var_",
) -> tuple[list[str], list[str]]:
    """
    Write up to `count` images from `harvest` and live canvas to `data/outputs/<job_id>/`.

    Returns `(saved_relative_paths, problems)`.

    Prioritizes verified canvas cards (which mount in Flow's DOM as uncompressed full-res
    renders), then structured variation records, then raw harvest URLs. If any source
    fails (e.g. 403 on internal CDN URLs), it continues to alternative sources and performs
    live canvas recovery so all variations are saved.

    `filename_prefix` names the files `<prefix><index>.jpg`. The single-prompt path keeps
    the historical `flow_var_` default; the multi-shot runner passes `shot_<n>_<archetype>_`
    so a four-shot set lands as four distinguishable files instead of overwriting one.
    """
    saved: list[str] = []
    problems: list[str] = []

    sources: list[tuple[str, Any]] = []
    seen_ids: set[str] = set()

    # 1. Prioritize canvas URLs — these are verified rendered on Flow's canvas after submit (200 OK, ~940 KB full-res)
    if canvas_urls:
        for u in canvas_urls:
            ident = media_identifier(u)
            if ident not in seen_ids:
                sources.append(("canvas", u))
                seen_ids.add(ident)

    # 2. Structured variation records (support 2K/4K upsampler if media_id present)
    if variations:
        for rec in variations:
            ident = media_identifier(rec.url) if rec.url else (rec.media_id or "")
            if not ident or ident not in seen_ids:
                sources.append(("record", rec))
                if ident:
                    seen_ids.add(ident)

    # 3. Inline blobs
    for blob in harvest.inline:
        sources.append(("inline", blob))

    # 4. Network harvest URLs — minus anything that was already on the canvas
    # when we submitted. The CDN direct-catch in `_on_response` fires for
    # every flow-content response after arming, including an old canvas card
    # the SPA re-rendered (or revalidated) after submit; the baseline ids are
    # the truth about what pre-existed, so those can never be this job's output.
    for url in harvest.urls:
        ident = media_identifier(url)
        if canvas_baseline_ids and ident in canvas_baseline_ids:
            print(f"  ⏭️ [FLOW AUTOMATOR] Skipping pre-existing canvas image in network harvest ({ident[:24]}...)")
            continue
        if ident not in seen_ids:
            sources.append(("url", url))
            seen_ids.add(ident)

    for kind, item in sources:
        if len(saved) >= count:
            break
        index = len(saved) + 1
        via = kind
        if kind == "record":
            rec = item
            body = None
            if upscaler is not None and not rec.media_id:
                print(f"⚠️ [FLOW AUTOMATOR] Variation #{index}: no mediaGenerationId was parsed "
                      "from the response — cannot request a 2K upsample, using render resolution.")
            if upscaler is not None and rec.media_id:
                body = await upscaler(rec.media_id)
                if body:
                    via = "2K upsample"
            if body is None:
                if rec.inline:
                    body, via = rec.inline, "inline"
                elif rec.url:
                    body, via = await _fetch_media(page, rec.url), "url"
        else:
            body = item if kind == "inline" else await _fetch_media(page, item)
        if not body:
            problems.append(f"variation #{index}: {kind} source could not be retrieved")
            continue
        out_path = output_dir / f"{filename_prefix}{index}.jpg"
        out_path.write_bytes(body)
        try:
            from app.services.anti_ai_processor import postprocess_image
            postprocess_image(out_path, skip_colab=True)
        except Exception as e:
            logger.warning("Anti-AI post-processing error on %s: %s", out_path, e)

        saved.append(f"data/outputs/{job_id}/{out_path.name}")
        print(f"  💾 Variation #{index} (watermark removed & color graded): {out_path.name} ({out_path.stat().st_size // 1024} KB, {via})")

    # 5. Live canvas recovery fallback if fewer than count were saved
    if len(saved) < count and canvas_baseline_ids is not None:
        print(f"🔍 [FLOW AUTOMATOR] Saved {len(saved)} of {count} so far. Checking canvas for remaining variations...")
        for attempt in range(5):
            if len(saved) >= count:
                break
            if attempt > 0:
                await asyncio.sleep(2.0)
            try:
                fresh_canvas = await _get_canvas_media_urls(page)
                fresh_new = [u for u in fresh_canvas if media_identifier(u) not in canvas_baseline_ids]
                for u in fresh_new:
                    if len(saved) >= count:
                        break
                    ident = media_identifier(u)
                    if ident not in seen_ids:
                        seen_ids.add(ident)
                        body = await _fetch_media(page, u)
                        if body:
                            index = len(saved) + 1
                            out_path = output_dir / f"{filename_prefix}{index}.jpg"
                            out_path.write_bytes(body)
                            try:
                                from app.services.anti_ai_processor import postprocess_image
                                postprocess_image(out_path, skip_colab=True)
                            except Exception as e:
                                logger.warning("Anti-AI post-processing error on %s: %s", out_path, e)
                            saved.append(f"data/outputs/{job_id}/{out_path.name}")
                            print(f"  💾 Variation #{index} (from canvas recovery): {out_path.name} ({out_path.stat().st_size // 1024} KB, canvas recovery)")
            except Exception as e:
                logger.warning("Canvas recovery error on attempt %d: %s", attempt + 1, e)

    return saved, problems


# ── the run ─────────────────────────────────────────────────────────────


async def _resolve_reference_image(
    job_id: str, reference_image: str | Path | None
) -> Path | None:
    """
    The style reference to paste into Flow, or None for a text-only run.

    Resolution order — explicit argument, `ref_image_path.txt` beside the outputs,
    the job package's `REFERENCE_STYLE.*`, then the job's row in the DB.
    """
    ref_image_path: Path | None = (
        Path(reference_image).resolve()
        if reference_image and Path(reference_image).exists()
        else None
    )
    output_dir = Path(f"./data/outputs/{job_id}").resolve()
    if not ref_image_path or not ref_image_path.exists():
        ref_file = output_dir / "ref_image_path.txt"
        if ref_file.exists():
            cand = Path(ref_file.read_text(encoding="utf-8").strip()).resolve()
            if cand.exists():
                ref_image_path = cand
    if not ref_image_path or not ref_image_path.exists():
        # Try data/jobs/<job_id>/REFERENCE_STYLE.*
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            cand = Path(f"./data/jobs/{job_id}/REFERENCE_STYLE{ext}").resolve()
            if cand.exists():
                ref_image_path = cand
                break
    if (not ref_image_path or not ref_image_path.exists()) and job_id:
        # Try DB: load job's reference image path
        try:
            from app.database import async_session as _sess
            from app.models.models import Job, Reference

            async with _sess() as db:
                j = await db.get(Job, job_id)
                if j and j.reference_id:
                    r = await db.get(Reference, j.reference_id)
                    if r and r.image_path and Path(r.image_path).exists():
                        ref_image_path = Path(r.image_path).resolve()
        except Exception as e:
            logger.warning("Could not query reference image for job %s from DB: %s", job_id, e)

    if ref_image_path and ref_image_path.exists():
        print(f"🖼️ [FLOW AUTOMATOR] Reference image for job {job_id}: {ref_image_path} ({ref_image_path.stat().st_size//1024} KB)")
        return ref_image_path
    print(f"ℹ️ [FLOW AUTOMATOR] No reference image found for job {job_id} — running prompt-only (fallback)")
    return None


async def _launch_flow_context(p):
    """
    Launch the persistent, logged-in Flow Chromium profile. The caller closes it.

    Three attempts, because a stale profile lock from a killed run is the single
    most common launch failure and clearing the locks usually fixes it.
    """
    ctx = None
    for attempt in range(3):
        # Clean stale Chromium profile locks
        for lock in ["SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"]:
            lock_file = PROFILE_DIR / lock
            if lock_file.exists():
                try:
                    lock_file.unlink()
                except Exception:
                    pass

        try:
            ctx = await p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=False,
                no_viewport=True,
                args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
            )
            break
        except Exception as e:
            print(f"⚠️ [FLOW AUTOMATOR] Launch attempt {attempt + 1} failed: {e}. Cleaning...")
            _kill_stale_flow_chrome()
            await asyncio.sleep(2)

    if not ctx:
        raise RuntimeError("Failed to launch Google Flow browser after 3 attempts due to profile lock.")
    return ctx


async def _acquire_flow_page(ctx, job_id: str):
    """
    The Flow profile's first page, sitting on this job's project workspace.

    Configuration first (settings.flow_project_url / FLOW_PROJECT_URL in .env), then
    the workspace that worked last time, then discovery, then creation — see
    `_open_project`. Every failure path hands the browser back before raising, or the
    next run spends its first two attempts clearing a profile lock.
    """
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    try:
        project_url = await _open_project(page, job_id)
    except (FlowGenerationError, PlaywrightError):
        await _close_quietly(ctx)
        raise
    print(f"📂 [FLOW AUTOMATOR] Workspace: {project_url}")
    return page, project_url


async def generate_flow_batch(prompt: str, job_id: str, count: int = 4, reference_image: str | Path | None = None) -> list[str]:
    """Alias entrypoint for Google Flow batch generation."""
    return await generate_flow_batch_automated(job_id=job_id, prompt=prompt, count=count, reference_image=reference_image)


def _attribution_diagnostics(watcher: _GenerationWatcher) -> str:
    """
    Everything a failed attribution needs, and no payload values.

    The request/response split matters more than it looks. If Flow never received a
    generation request, the problem is the submit — a wasted 210 s wait, not a
    rename. If the request went out and nothing recognisable answered, Google may
    have renamed the endpoint. The old message could not tell those apart.
    """
    lines = []
    if watcher.generation_requests:
        lines.append("generation request(s) sent: " + ", ".join(watcher.generation_requests))
    else:
        lines.append(
            "NO generation request left the browser — Flow was never asked to generate. "
            "POSTs seen after arming: " + (", ".join(watcher.request_paths[:12]) or "none")
        )
    if watcher.generation_paths:
        lines.append("generation endpoint(s) that answered: " + ", ".join(watcher.generation_paths))
    else:
        lines.append(
            "no response matched a generation endpoint. JSON endpoints that did answer: "
            + (", ".join(watcher.json_paths[:12]) or "none")
        )
    if watcher.shapes:
        lines.append("response shape: " + watcher.shapes[0])
    if watcher.notes:
        lines.append("notes: " + "; ".join(watcher.notes[:6]))
    return " | ".join(lines)


@dataclass
class _WaitOutcome:
    """What one submit produced, plus the timing the caller reports on failure."""

    canvas_new_urls: list[str]
    first_media_at: float | None
    total_found: int
    elapsed: float


async def _wait_for_generation(
    page,
    watcher: _GenerationWatcher,
    count: int,
    canvas_baseline_ids: set[str],
    clicked: str,
) -> _WaitOutcome:
    """
    Wait for Flow to answer ONE submit, then hand back what it named.

    Extracted from the single-prompt path so the multi-shot runner can run it once
    per shot. It polls two independent sources — the watcher's network harvest and
    newly mounted canvas cards — because either can be the only one to see a render.

    Four exit conditions, all deliberate:

    * all `count` variations are on the canvas — nothing left to wait for;
    * the network named all `count` — then a short grace period for the cards to
      mount, because the download prefers canvas bytes;
    * Flow answered with fewer than `count` — a 35s grace window, then work with
      what it actually sent rather than burning the full timeout;
    * no generation request left the browser and the submit was not confirmed by
      the prompt bar clearing — stop early and let the caller raise a diagnostic
      that can tell "never submitted" from "unrecognised endpoint".

    The canvas is not polled for the first 10s: Flow renders take at least 15-20s,
    so anything mounting sooner is a pre-existing card hydrating late.
    """
    deadline = asyncio.get_event_loop().time() + GENERATION_TIMEOUT_SECONDS
    started_at = asyncio.get_event_loop().time()
    first_media_at: float | None = None
    all_network_at: float | None = None
    canvas_new_urls: list[str] = []
    tick = 0
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(1.5)
        tick += 1
        now = asyncio.get_event_loop().time()
        elapsed_s = now - started_at

        # Dual-layer check: poll canvas for newly appeared generated images.
        # Google Flow renders take at least 15-20s. We do NOT poll canvas in the
        # first 10s to guarantee no late-hydrating existing cards are captured as "new".
        if elapsed_s >= 10:
            current_canvas = await _get_canvas_media_urls(page)
            new_on_canvas = [u for u in current_canvas if media_identifier(u) not in canvas_baseline_ids]
            for u in new_on_canvas:
                ident = media_identifier(u)
                existing_ids = {media_identifier(existing) for existing in canvas_new_urls}
                if ident not in existing_ids:
                    canvas_new_urls.append(u)
                    print(f"🖼️ [FLOW AUTOMATOR] Captured newly generated canvas variation: {u[:70]}...")

        total_found = max(watcher.harvest.total, len(canvas_new_urls))
        if total_found and first_media_at is None:
            first_media_at = now

        # If all requested variations are confirmed on the canvas, proceed immediately!
        if len(canvas_new_urls) >= count:
            print(f"✅ [FLOW AUTOMATOR] All {count} requested variations verified on canvas!")
            break

        # If network captured all requested variations, wait up to 15s for the canvas cards to finish mounting
        if watcher.harvest.total >= count:
            if all_network_at is None:
                all_network_at = now
                print(f"📡 [FLOW AUTOMATOR] All {count} network responses received ({len(canvas_new_urls)}/{count} on canvas). Waiting for cards to mount...")
            if len(canvas_new_urls) >= count or (now - all_network_at > 15):
                break

        # Flow answered, but with fewer than requested. Give the remaining
        # responses a grace window, then work with what it actually sent
        # rather than waiting out the full timeout.
        if first_media_at is not None and now - first_media_at > 35:
            print(f"ℹ️ [FLOW AUTOMATOR] Flow named {total_found} of {count} "
                  "media in the grace window; proceeding with those.")
            break
        # No generation request at all after a generous window means the submit
        # was accepted by the page but Flow never asked its backend to render.
        # Only give up if neither request was sent nor submit was confirmed by prompt clear.
        if (not watcher.generation_requests and not total_found
                and "confirmed by prompt bar cleared" not in clicked
                and now - started_at > NO_REQUEST_GIVE_UP_SECONDS):
            print("⚠️ [FLOW AUTOMATOR] No generation request left the browser in "
                  f"{NO_REQUEST_GIVE_UP_SECONDS:.0f}s — not waiting out the timeout.")
            break

        if tick % 7 == 0:
            progress = await _safe_eval(page, """
                () => {
                    const text = document.body ? document.body.innerText : '';
                    const match = text.match(/(\\d{1,3})\\s?%/);
                    return match ? match[1] : null;
                }
            """, what="poll render progress")
            elapsed = int(GENERATION_TIMEOUT_SECONDS - (deadline - now))
            print(f"⏳ [FLOW AUTOMATOR] {elapsed}s elapsed"
                  + (f", Flow reports {progress}%" if progress else "")
                  + f", {total_found} media named so far ({len(canvas_new_urls)} on canvas)...")

    return _WaitOutcome(
        canvas_new_urls=canvas_new_urls,
        first_media_at=first_media_at,
        total_found=max(watcher.harvest.total, len(canvas_new_urls)),
        elapsed=asyncio.get_event_loop().time() - started_at,
    )


def _build_upscaler(page, watcher: _GenerationWatcher):
    """
    A callable turning a mediaGenerationId into print-resolution bytes, or None.

    The upsample endpoint is sibling to the generation endpoint and accepts the same
    OAuth header, which the watcher captured from the generation request.
    `page.request` adds the profile's cookies. Any failure falls back to the
    render-resolution bytes — an upsample must never cost a variation.
    """
    resolution = (getattr(settings, "flow_upscale_resolution", "2k") or "none").strip().lower()
    if resolution not in ("2k", "4k") or not watcher.variations:
        return None
    if not (watcher.request_headers and watcher.api_base):
        print("ℹ️ [FLOW AUTOMATOR] Upsampling requested but the generation request's "
              "auth was not captured; using render-resolution bytes.")
        return None

    from app.services.flow_upscale import (
        UPSCALE_TIMEOUT_MS,
        media_id_candidates,
        upscale_to_bytes,
    )

    auth = watcher.request_headers.get("authorization", "")
    api_base = watcher.api_base
    project_id = watcher.project_id

    async def _execute(url: str, payload: dict) -> Any:
        resp = await page.request.post(
            url,
            data=payload,
            headers={"authorization": auth, "content-type": "application/json"},
            timeout=UPSCALE_TIMEOUT_MS,
        )
        if resp.status != 200:
            snippet = ""
            with contextlib.suppress(Exception):
                snippet = (await resp.text())[:300]
            raise RuntimeError(f"HTTP {resp.status}: {snippet or '(no body)'}")
        return await resp.json()

    async def upscaler(media_id: str) -> bytes | None:
        candidates = media_id_candidates(media_id)
        for attempt, candidate in enumerate(candidates, 1):
            body = await upscale_to_bytes(
                _execute, api_base, candidate,
                resolution=resolution, project_id=project_id,
                on_failure=lambda m: print(f"⚠️ [FLOW AUTOMATOR] {m}"),
            )
            if body is not None:
                if candidate != media_id:
                    print("✅ [FLOW AUTOMATOR] Upsampler accepted the bare id segment.")
                return body
            if attempt < len(candidates):
                print("⏳ [FLOW AUTOMATOR] Retrying upsample with the alternate id form...")
                await asyncio.sleep(6)
        return None

    print(f"🔼 [FLOW AUTOMATOR] 2K upsampling enabled ({resolution.upper()}) — "
          "requesting print-resolution bytes from Flow's upsampler.")
    return upscaler


@dataclass
class ShotRequest:
    """One prompt to submit on its own, plus what the shot is for."""

    archetype: str
    prompt: str
    label: str = ""
    aspect_ratio: str | None = None


@dataclass
class ShotResult:
    """What one shot produced. `error` is set only when nothing was saved."""

    archetype: str
    label: str
    saved: list[str]
    error: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.saved)


async def generate_flow_shots_automated(
    job_id: str,
    shots: list[ShotRequest],
    reference_image: str | Path | None = None,
    *,
    count_per_shot: int = 1,
) -> list[ShotResult]:
    """
    Generate a multi-shot set: one serial submission per shot, one browser session.

    Why not one submission with `count=len(shots)`? Flow's `count` returns N
    stochastic samples of the SAME prompt string — the sampler converges on one
    reading and jitters around it, which is exactly the "four slightly different
    camera angles of one scene" problem. There is no diversity control in Flow's
    image API; composition, camera angle and lighting are settable only through
    prompt text. So N genuinely distinct photographs need N prompts and N submits.

    The shots are serialised deliberately. Flow's project canvas is a single shared
    surface, and two concurrent submits would race on the same baseline snapshot —
    attribution would become ambiguous exactly where the single-prompt path went to
    great lengths to make it unambiguous.

    A fresh `_GenerationWatcher` is created per shot, so shot 2's harvest can never
    contain shot 1's media. A shot that fails is recorded and the run continues: one
    moderation rejection should not cost the other three shots.

    Files land as `data/outputs/<job_id>/shot_<n>_<archetype>_<k>.jpg`.

    Returns one `ShotResult` per requested shot, in the order given.
    """
    if not shots:
        raise ValueError("refusing to drive Google Flow with no shots")
    for shot in shots:
        if not shot.prompt or not shot.prompt.strip():
            raise ValueError(f"shot {shot.archetype!r} has an empty prompt")

    output_dir = Path(f"./data/outputs/{job_id}").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    ref_image_path = await _resolve_reference_image(job_id, reference_image)

    print(f"\n⚡ [FLOW AUTOMATOR] Multi-shot run for Job {job_id}: {len(shots)} shot(s) "
          f"({', '.join(s.archetype for s in shots)}), {count_per_shot} image(s) each.")
    print("ℹ️ [FLOW AUTOMATOR] Each shot is its own submission — Flow's `count` returns N "
          "samples of ONE prompt, so distinct shots require distinct submits.")

    results: list[ShotResult] = []

    async with async_playwright() as p:
        ctx = await _launch_flow_context(p)
        page, project_url = await _acquire_flow_page(ctx, job_id)

        for n, shot in enumerate(shots, 1):
            print(f"\n─── shot {n}/{len(shots)} — {shot.archetype} "
                  f"({shot.label or 'unnamed'}) " + "─" * 18)
            print(f"📝 Prompt: {shot.prompt[:120]}...")

            # A fresh watcher per shot: attribution state must not carry over.
            watcher = _GenerationWatcher(page)
            watcher.attach()

            try:
                try:
                    box, flat = await _enter_prompt(
                        page, shot.prompt, reference_image=ref_image_path
                    )
                except (FlowGenerationError, PlaywrightError) as e:
                    watcher.detach()
                    results.append(ShotResult(shot.archetype, shot.label, [], f"prompt entry failed: {e}"))
                    continue

                # Baseline the canvas right before this shot's submit, so cards from
                # earlier shots in this same run are never mistaken for this one's.
                canvas_baseline_ids = {
                    media_identifier(u) for u in await _get_canvas_media_urls(page)
                }
                print(f"ℹ️ [FLOW AUTOMATOR] Baseline: {len(canvas_baseline_ids)} existing media id(s) on canvas.")

                watcher.arm()
                try:
                    clicked = await _submit_prompt(page, box, watcher, len(_norm(flat)))
                except (FlowGenerationError, PlaywrightError) as e:
                    watcher.detach()
                    results.append(ShotResult(shot.archetype, shot.label, [], f"submit failed: {e}"))
                    continue
                print(f"⚡ [FLOW AUTOMATOR] Submitted via {clicked}")

                outcome = await _wait_for_generation(
                    page, watcher, count_per_shot, canvas_baseline_ids, clicked
                )
                await watcher.drain()
                watcher.detach()

                if not outcome.total_found:
                    results.append(ShotResult(
                        shot.archetype, shot.label, [],
                        f"Flow returned no media in {int(outcome.elapsed)}s. "
                        f"Diagnostics — {_attribution_diagnostics(watcher)}",
                    ))
                    continue

                saved, problems = await _save_harvest(
                    page, watcher.harvest, output_dir, job_id, count_per_shot,
                    variations=watcher.variations or None,
                    canvas_urls=outcome.canvas_new_urls or None,
                    canvas_baseline_ids=canvas_baseline_ids,
                    upscaler=_build_upscaler(page, watcher),
                    filename_prefix=f"shot_{n}_{shot.archetype}_",
                )
                results.append(ShotResult(
                    shot.archetype, shot.label, saved,
                    None if saved else ("; ".join(problems) or "nothing could be saved"),
                ))
            except Exception as e:  # noqa: BLE001 — one bad shot must not abandon the set
                watcher.detach()
                logger.exception("Shot %s failed for job %s", shot.archetype, job_id)
                results.append(
                    ShotResult(shot.archetype, shot.label, [], f"{type(e).__name__}: {e}")
                )

        await _close_quietly(ctx)

    produced = [r for r in results if r.ok]
    print(f"\n🎉 [FLOW AUTOMATOR] Multi-shot run finished for Job {job_id}: "
          f"{len(produced)}/{len(shots)} shot(s) produced images "
          f"({sum(len(r.saved) for r in results)} file(s) total).")
    for r in results:
        if r.ok:
            print(f"  ✅ {r.archetype:12} {', '.join(Path(s).name for s in r.saved)}")
        else:
            print(f"  ❌ {r.archetype:12} {r.error}")

    return results


async def generate_flow_batch_automated(job_id: str, prompt: str, count: int = 4, reference_image: str | Path | None = None) -> list[str]:
    """
    Generate `count` variations in Google Flow and download exactly those.

    Images are attributed by intercepting Flow's own generation response, so what
    lands in `data/outputs/<job_id>/` can only be media this submit produced. When
    that response cannot be found the run fails and says what it saw instead —
    there is no DOM-diff fallback, because a DOM diff is what credited an earlier
    job with four unrelated images off the project canvas.

    `reference_image` — if provided, pasted FIRST into the prompt box before the
    text prompt (the easy way — Flow uploads it and shows a chip inside the box).
    Resolved from job's reference if not passed explicitly.
    """
    if not prompt or not prompt.strip():
        raise ValueError("refusing to drive Google Flow with an empty prompt")

    output_dir = Path(f"./data/outputs/{job_id}").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    ref_image_path = await _resolve_reference_image(job_id, reference_image)

    print(f"\n⚡ [FLOW AUTOMATOR] Starting automated generation for Job {job_id}...")
    print(f"📝 Prompt: {prompt[:120]}...")

    async with async_playwright() as p:
        ctx = await _launch_flow_context(p)

        # Step 1: Open the Flow project workspace.
        page, project_url = await _acquire_flow_page(ctx, job_id)

        watcher = _GenerationWatcher(page)
        watcher.attach()

        try:
            box, flat = await _enter_prompt(page, prompt, reference_image=ref_image_path)
        except (FlowGenerationError, PlaywrightError):
            watcher.detach()
            await _close_quietly(ctx)
            raise

        # Dual-layer baseline: snapshot all existing media images on the canvas
        # RIGHT BEFORE submit, after prompt entry and any reference image upload
        # (40+ seconds). This guarantees all existing cards in this project workspace
        # are captured in the baseline and will NEVER be mistaken for new variations.
        canvas_baseline_urls = set(await _get_canvas_media_urls(page))
        canvas_baseline_ids = {media_identifier(u) for u in canvas_baseline_urls}
        print(f"ℹ️ [FLOW AUTOMATOR] Project canvas currently shows {len(canvas_baseline_urls)} existing media image(s) ({len(canvas_baseline_ids)} unique IDs, baseline snapshot before submit).")

        # Arm *after* the prompt is in the box and *before* the submit, so the only
        # requests and responses considered are answers to this submit.
        watcher.arm()
        try:
            clicked = await _submit_prompt(page, box, watcher, len(_norm(flat)))
        except (FlowGenerationError, PlaywrightError):
            watcher.detach()
            await _close_quietly(ctx)
            raise
        print(f"⚡ [FLOW AUTOMATOR] Submitted via {clicked}")

        # Step 5: wait for Flow to answer via network responses or newly mounted canvas cards.
        outcome = await _wait_for_generation(page, watcher, count, canvas_baseline_ids, clicked)
        canvas_new_urls = outcome.canvas_new_urls

        await watcher.drain()
        watcher.detach()

        total_found = outcome.total_found
        if not total_found:
            alerts = await _safe_eval(page, _JS_PAGE_ALERTS, what="read page alerts") or []
            await _debug_shot(page, f"flow_no_media_{job_id[:8]}")
            await _close_quietly(ctx)
            waited = int(outcome.elapsed)
            raise FlowGenerationError(
                f"Google Flow did not return any generated media (waited {waited}s of "
                f"{GENERATION_TIMEOUT_SECONDS}s). Nothing was downloaded, so no pre-existing "
                "canvas image could be mistaken for this job's output. Submitted via "
                f"{clicked}. Diagnostics — {_attribution_diagnostics(watcher)}"
                + (f" | page said: {' / '.join(alerts[:3])}" if alerts else "")
                + f" | screenshot: data/debug/flow_no_media_{job_id[:8]}.png"
            )

        print(f"📦 [FLOW AUTOMATOR] Flow named {total_found} media "
              f"({len(canvas_new_urls)} on canvas, {len(watcher.harvest.inline)} inline, {len(watcher.harvest.urls)} network URL, "
              f"{sum(1 for r in watcher.variations if r.media_id)} of {len(watcher.variations)} "
              f"variation records carry a media id). Downloading at full resolution...")
        if watcher.variations and not any(r.media_id for r in watcher.variations):
            outline = " | ".join(dict.fromkeys(watcher.shapes))[:600] or "(no shapes captured)"
            print(f"⚠️ [FLOW AUTOMATOR] No mediaGenerationId found in the generation response(s). "
                  f"Key outline: {outline}")

        # 2K upsampling: the upsample endpoint is sibling to the generation
        # endpoint and accepts the same OAuth header, which the watcher captured
        # from the generation request. `page.request` adds the profile's cookies.
        # Any failure falls back to the render-resolution bytes — an upsample
        # must never cost a variation.
        upscaler = _build_upscaler(page, watcher)

        image_paths, problems = await _save_harvest(
            page, watcher.harvest, output_dir, job_id, count,
            variations=watcher.variations or None,
            canvas_urls=canvas_new_urls or None,
            canvas_baseline_ids=canvas_baseline_ids,
            upscaler=upscaler,
        )

        if not image_paths:
            await _close_quietly(ctx)
            raise FlowGenerationError(
                f"No variations could be saved for job {job_id}. "
                + ("; ".join(problems) if problems else
                   f"Flow named only {watcher.harvest.total} media.")
            )

        if len(image_paths) < count:
            print(f"⚠️ [FLOW AUTOMATOR] Flow produced a partial batch: saved {len(image_paths)} of {count} requested variations.")

        await _close_quietly(ctx)

    print(f"🎉 [FLOW AUTOMATOR] Successfully produced {len(image_paths)} variations for Job {job_id}!")
    return image_paths



