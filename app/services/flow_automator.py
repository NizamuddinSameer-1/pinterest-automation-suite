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
#: remaining timeout only delays the report.
NO_REQUEST_GIVE_UP_SECONDS = 45.0

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
        try:
            payload = await response.json()
        except Exception as e:  # noqa: BLE001 — a non-JSON body is a note, not a crash
            self.notes.append(f"{path}: body was not JSON ({type(e).__name__})")
            return

        before = self.harvest.total
        harvest_media(payload, self.harvest)
        gained = self.harvest.total - before
        try:
            self.variations.extend(harvest_variations(payload))
        except Exception:  # noqa: BLE001 — flat harvest still stands; upscale just skips
            self.variations = self.variations or []
        self.shapes.append(describe_shape(payload))
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
    Download one media URL using the browser's own credentials.

    `page.request` shares the context's cookie jar, so this is an authenticated
    full-resolution fetch — not an element screenshot, which is what an earlier
    version fell back to and which made failed renders indistinguishable from
    successful ones.
    """
    try:
        response = await page.request.get(url)
        if response.status == 200:
            body = await response.body()
            if len(body) >= MIN_IMAGE_BYTES:
                return body
            print(f"  Notice: media URL returned {len(body)} bytes, below {MIN_IMAGE_BYTES}.")
        else:
            print(f"  Notice: media URL returned HTTP {response.status}.")
    except Exception as e:  # noqa: BLE001 — the in-page fetch is the real fallback
        print(f"  Notice on authenticated fetch: {e}")

    try:
        encoded = await _safe_eval(page, """
            async (url) => {
                const resp = await fetch(url, { credentials: 'include' });
                if (!resp.ok) return null;
                const bytes = new Uint8Array(await resp.arrayBuffer());
                let binary = '';
                for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
                return btoa(binary);
            }
        """, url, what="in-page media fetch")
    except (PlaywrightError, FlowGenerationError) as e:
        print(f"  Notice on in-page fetch: {e}")
        return None
    if not encoded:
        return None
    try:
        body = base64.b64decode(encoded)
    except (ValueError, TypeError):
        return None
    return body if len(body) >= MIN_IMAGE_BYTES else None


async def _save_harvest(
    page,
    harvest: MediaHarvest,
    output_dir: Path,
    job_id: str,
    count: int,
    *,
    variations: list | None = None,
    upscaler: Any = None,
) -> tuple[list[str], list[str]]:
    """
    Write up to `count` images from `harvest` to `data/outputs/<job_id>/`.

    Returns `(saved_relative_paths, problems)`.

    Two source shapes, in preference order:

    * `variations` — structured records pairing each variation's
      `mediaGenerationId` with its bytes/URL. When an `upscaler` is provided the
      record's id goes to Flow's server-side 2K upsampler first; on any failure
      the record's render-resolution bytes are used (original-image fallback).
    * the flat `harvest` — inline bytes first (they need no second request),
      then URLs, order-preserved, so variation *n* on disk is variation *n* in
      the response.
    """
    saved: list[str] = []
    problems: list[str] = []

    if variations:
        sources: list[tuple[str, Any]] = [("record", rec) for rec in variations]
    else:
        sources = [("inline", blob) for blob in harvest.inline]
        sources += [("url", url) for url in harvest.urls]

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
        out_path = output_dir / f"flow_var_{index}.jpg"
        out_path.write_bytes(body)
        try:
            from app.services.anti_ai_processor import postprocess_image
            postprocess_image(out_path, skip_colab=True)
        except Exception as e:
            logger.warning("Anti-AI post-processing error on %s: %s", out_path, e)

        saved.append(f"data/outputs/{job_id}/{out_path.name}")
        print(f"  💾 Variation #{index} (watermark removed & color graded): {out_path.name} ({out_path.stat().st_size // 1024} KB, {via})")

    return saved, problems


# ── the run ─────────────────────────────────────────────────────────────


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

    # Resolve reference image if not explicitly passed — try ref_image_path.txt, job package, then DB
    ref_image_path: Path | None = Path(reference_image).resolve() if reference_image and Path(reference_image).exists() else None
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
    else:
        # No reference image found — will do text-only
        ref_image_path = None
        print(f"ℹ️ [FLOW AUTOMATOR] No reference image found for job {job_id} — running prompt-only (fallback)")

    print(f"\n⚡ [FLOW AUTOMATOR] Starting automated generation for Job {job_id}...")
    print(f"📝 Prompt: {prompt[:120]}...")

    async with async_playwright() as p:
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

        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        # Step 1: Open the Flow project workspace. Configuration first
        # (settings.flow_project_url / FLOW_PROJECT_URL in .env), then the workspace
        # that worked last time, then discovery, then creation — see `_open_project`.
        # Every failure path here hands the browser back before raising, or the next
        # run spends its first two attempts clearing a profile lock.
        try:
            project_url = await _open_project(page, job_id)
        except (FlowGenerationError, PlaywrightError):
            await _close_quietly(ctx)
            raise
        print(f"📂 [FLOW AUTOMATOR] Workspace: {project_url}")

        # Informational only. This count is never used to decide ownership — the
        # canvas holds every past generation, and reading it for attribution is
        # exactly the bug this rewrite removes.
        canvas_before = await _safe_eval(page, """
            () => document.querySelectorAll('img[src*="getMediaUrlRedirect"]').length
        """, what="count canvas images")
        print(f"ℹ️ [FLOW AUTOMATOR] Project canvas currently shows {canvas_before} image(s) "
              "(not used for attribution).")

        watcher = _GenerationWatcher(page)
        watcher.attach()

        try:
            box, flat = await _enter_prompt(page, prompt, reference_image=ref_image_path)
        except (FlowGenerationError, PlaywrightError):
            watcher.detach()
            await _close_quietly(ctx)
            raise

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

        # Step 5: wait for Flow to answer, not for the canvas to look right.
        deadline = asyncio.get_event_loop().time() + GENERATION_TIMEOUT_SECONDS
        started_at = asyncio.get_event_loop().time()
        first_media_at: float | None = None
        tick = 0
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(1.5)
            tick += 1
            now = asyncio.get_event_loop().time()

            if watcher.harvest.total and first_media_at is None:
                first_media_at = now
            if watcher.harvest.total >= count:
                break
            # Flow answered, but with fewer than requested. Give the remaining
            # responses a grace window, then work with what it actually sent
            # rather than waiting out the full timeout.
            if first_media_at is not None and now - first_media_at > 25:
                print(f"ℹ️ [FLOW AUTOMATOR] Flow named {watcher.harvest.total} of {count} "
                      "media in the grace window; proceeding with those.")
                break
            # No generation request at all after a generous window means the submit
            # was accepted by the page but Flow never asked its backend to render.
            # Waiting out the remaining ~2.5 minutes cannot change that.
            if (not watcher.generation_requests and not watcher.harvest.total
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
                      + f", {watcher.harvest.total} media named so far...")

        await watcher.drain()
        watcher.detach()

        if not watcher.harvest.total:
            alerts = await _safe_eval(page, _JS_PAGE_ALERTS, what="read page alerts") or []
            await _debug_shot(page, f"flow_no_media_{job_id[:8]}")
            await _close_quietly(ctx)
            waited = int(asyncio.get_event_loop().time() - started_at)
            raise FlowGenerationError(
                f"Google Flow did not return any generated media (waited {waited}s of "
                f"{GENERATION_TIMEOUT_SECONDS}s). Nothing was downloaded, so no pre-existing "
                "canvas image could be mistaken for this job's output. Submitted via "
                f"{clicked}. Diagnostics — {_attribution_diagnostics(watcher)}"
                + (f" | page said: {' / '.join(alerts[:3])}" if alerts else "")
                + f" | screenshot: data/debug/flow_no_media_{job_id[:8]}.png"
            )

        print(f"📦 [FLOW AUTOMATOR] Flow named {watcher.harvest.total} media "
              f"({len(watcher.harvest.inline)} inline, {len(watcher.harvest.urls)} URL, "
              f"{sum(1 for r in watcher.variations if r.media_id)} of {len(watcher.variations)} "
              f"variation records carry a media id). Downloading at full resolution...")
        if watcher.variations and not any(r.media_id for r in watcher.variations):
            # Keys only — these payloads hold tokens and signed URLs. The
            # outline exists so the NEXT run shows exactly where Flow put
            # the mediaGenerationId (or that it never sent one).
            outline = " | ".join(dict.fromkeys(watcher.shapes))[:600] or "(no shapes captured)"
            print(f"⚠️ [FLOW AUTOMATOR] No mediaGenerationId found in the generation response(s). "
                  f"Key outline: {outline}")

        # 2K upsampling: the upsample endpoint is sibling to the generation
        # endpoint and accepts the same OAuth header, which the watcher captured
        # from the generation request. `page.request` adds the profile's cookies.
        # Any failure falls back to the render-resolution bytes — an upsample
        # must never cost a variation.
        upscaler = None
        resolution = (getattr(settings, "flow_upscale_resolution", "2k") or "none").strip().lower()
        if resolution in ("2k", "4k") and watcher.variations:
            if watcher.request_headers and watcher.api_base:
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

                async def upscaler(media_id: str) -> bytes | None:  # noqa: F811 — intentional shadow
                    # Try each id form (bare segment, then full resource
                    # name): newer responses identify media by resource
                    # name, and which form the upsampler stores is not
                    # documented. A short wait between forms also covers the
                    # on-demand upsampler racing generation completion.
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
            else:
                print("ℹ️ [FLOW AUTOMATOR] Upsampling requested but the generation request's "
                      "auth was not captured; using render-resolution bytes.")

        image_paths, problems = await _save_harvest(
            page, watcher.harvest, output_dir, job_id, count,
            variations=watcher.variations or None,
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



