"""
The two Google Flow backends must be safe to *replay*, not just correct on paper.

Two real failures motivate this check, both from the same run:

  * `flow_api: Illegal header name b':authority'` — Playwright captured Chrome's
    HTTP/2 request, whose request line is carried as the pseudo-headers
    `:authority`, `:method`, `:path` and `:scheme`. httpx replays over HTTP/1.1
    and h11 rejects any header name starting with `:`. The capture wrote them to
    disk and the replay's header filter only removed `content-length`, `host`,
    `accept-encoding` and `connection`, so every replay died before it left the
    process.
  * `flow_ui: Page.evaluate: Execution context was destroyed, most likely because
    of a navigation` — Flow is a single-page app that redirects after load, so a
    bare `page.evaluate` can execute in a context that no longer exists.

A third, worse failure motivates section 4: a run that logged `flow_ui produced 4
verified image(s)` and filled a job's gallery with four images from *other* tests,
because the automator decided what was "new" by diffing the DOM of a canvas that
lazily hydrates every past generation.

So this asserts seven things:
  1. `_sanitise_headers` drops pseudo-headers (including bytes-keyed ones) and
     keeps the real ones — exercised against the live capture if present.
  2. The capture on disk contains no pseudo-headers, i.e. the capture script's
     own filter is doing its job.
  3. Every `page.evaluate` in `flow_automator` goes through `_safe_eval`, and
     every `page.goto` through `_goto_settled`.
  3b. A project workspace is *acquired* — configured URL, then the one that worked
     last time, then a polled dashboard, then creation as a last resort — instead
     of being guessed at by one `querySelector` two seconds after load.
  4. Attribution comes from Flow's own generation response, never the DOM: a
     listing endpoint is not mistaken for a generation one, the harvester keeps
     response order, the DOM diff has not returned, and the run cannot submit
     before the prompt is verified and the watcher armed.
  5. The prompt reaches the box as one line, flattened before it is delivered,
     with a newline refused outright — Enter is Flow's send key.
  6. No browser module calls a camelCase Playwright method. `keyboard.insertText`
     is the JavaScript spelling; the Python binding is `insert_text`, and the
     misspelling raised `AttributeError` in a live run, which no
     `except PlaywrightError` could catch. Where playwright is importable the
     names are also checked against the classes.
  7. `browser_utils.insert_text` prefers `keyboard.insert_text`, falls back to the
     DevTools protocol, and refuses to *type* text containing a newline.

`app.config` is stubbed, because this must run without the project's
dependencies installed.
"""

import ast
import base64
import json
import re
import sys
import types
from pathlib import Path

import __future__  # `str | None` annotations must compile on 3.10 when lifted

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# app.config imports pydantic_settings, which need not be installed to check this.
stub = types.ModuleType("app.config")


class _Settings:
    storage_path = ROOT / "data"
    outputs_path = ROOT / "data" / "outputs"
    flow_project_url = ""


stub.settings = _Settings()
sys.modules.setdefault("app.config", stub)

fails: list[str] = []
notes: list[str] = []


# ── 1. header sanitisation ──────────────────────────────────────────────

# Lift _sanitise_headers out by AST so this test cannot drift from the module it
# checks, and so importing httpx is not required.
api_src = (ROOT / "app" / "services" / "flow_direct_api.py").read_text(encoding="utf-8")
tree = ast.parse(api_src)
wanted = {"_sanitise_headers", "_CLIENT_OWNED_HEADERS", "FlowSessionError", "_freshen_request_identity"}
picked = [
    node for node in tree.body
    if (isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in wanted)
    or (isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id in wanted for t in node.targets))
]
missing = wanted - {getattr(n, "name", None) or n.targets[0].id for n in picked}
if missing:
    fails.append(f"flow_direct_api.py no longer defines: {sorted(missing)}")

ns: dict = {"Any": object, "logger": types.SimpleNamespace(
    warning=lambda *a, **k: None, debug=lambda *a, **k: None, info=lambda *a, **k: None)}
ns["random"] = __import__("random")
ns["uuid"] = __import__("uuid")
exec(compile(ast.Module(body=picked, type_ignores=[]), "<flow-api-helpers>", "exec"), ns)
sanitise = ns["_sanitise_headers"]
freshen = ns["_freshen_request_identity"]

PSEUDO = [":authority", ":method", ":path", ":scheme"]

probe = {
    ":authority": "aisandbox-pa.googleapis.com",
    ":method": "POST",
    ":path": "/v1/whatever",
    ":scheme": "https",
    "content-length": "123",
    "Host": "example.com",
    "accept-encoding": "gzip",
    "Connection": "keep-alive",
    "authorization": "Bearer REDACTED",
    "content-type": "application/json",
    b":authority": b"bytes-keyed-capture",
    b"x-bytes-header": b"kept",
    "x-bad\nname": "dropped",
}
clean = sanitise(probe)

for name in list(clean):
    if name.startswith(":"):
        fails.append(f"_sanitise_headers kept pseudo-header {name!r} — httpx will reject it")
for name in ("content-length", "host", "accept-encoding", "connection"):
    if any(k.lower() == name for k in clean):
        fails.append(f"_sanitise_headers kept client-owned header {name!r}")
if "authorization" not in clean or "content-type" not in clean:
    fails.append("_sanitise_headers dropped a header the request needs (authorization/content-type)")
if "x-bytes-header" not in clean:
    fails.append("_sanitise_headers did not normalise a bytes-keyed header to str")
if any("\n" in k or "\r" in k for k in clean):
    fails.append("_sanitise_headers kept a header name containing a newline")
if not all(isinstance(k, str) and isinstance(v, str) for k, v in clean.items()):
    fails.append("_sanitise_headers returned non-str keys or values")

try:
    sanitise(["not", "a", "dict"])
    fails.append("_sanitise_headers accepted a non-dict instead of raising FlowSessionError")
except ns["FlowSessionError"]:
    pass


# ── 2. the capture on disk ──────────────────────────────────────────────

capture = ROOT / "data" / "captured_flow_session.json"
if not capture.is_file():
    notes.append("no data/captured_flow_session.json — capture contents not checked")
else:
    try:
        data = json.loads(capture.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        fails.append(f"captured_flow_session.json is unreadable: {e}")
        data = {}
    headers = data.get("headers", {})
    # Key names only — this file holds a bearer token and a reCAPTCHA token.
    on_disk_pseudo = sorted(k for k in headers if str(k).startswith(":"))
    if on_disk_pseudo:
        notes.append(
            f"capture still holds {len(on_disk_pseudo)} pseudo-header(s) {on_disk_pseudo} — "
            "harmless now that the replay strips them, but re-capturing removes them at source"
        )
    if headers and not any(str(k).lower() == "authorization" for k in headers):
        notes.append("capture has no authorization header — the replay will be rejected")
    if "captured_at" not in data:
        notes.append("capture predates the captured_at field; age falls back to file mtime")

    # The prompt must actually be reachable by the replacer, or every replay
    # regenerates the captured prompt no matter what the compiler produced.
    payload = data.get("json_payload")
    if payload is not None:
        flat = json.dumps(payload)
        if '"text"' not in flat and '"prompt"' not in flat:
            fails.append(
                "captured payload has no 'text' or 'prompt' key, so "
                "_replace_prompt_recursively cannot inject the compiled prompt"
            )
        # Freshening must change the pinned identity fields.
        if '"seed"' in flat or '"batchId"' in flat:
            before, after = flat, json.dumps(freshen(payload))
            if before == after:
                fails.append(
                    "_freshen_request_identity left seed/batchId untouched — every replay "
                    "would reuse the captured seed and batch id"
                )


# ── 3. navigation-tolerant page access ─────────────────────────────────

auto_src = (ROOT / "app" / "services" / "flow_automator.py").read_text(encoding="utf-8")
auto_tree = ast.parse(auto_src)


def _without_docstrings(src: str) -> str:
    """
    Source with docstrings and `#` comments removed.

    Needed because the fixes deliberately quote the code they replaced: the
    docstrings of `_is_project_url` and `_open_project` both name the one-shot
    `querySelector` and the loose `"project" not in page.url` check, and a naive
    substring search reports the very bug the docstring is documenting.
    """
    drop: set[int] = set()
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", [])
        if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            drop.update(range(body[0].lineno, (body[0].end_lineno or body[0].lineno) + 1))
    kept = ("" if i + 1 in drop else line for i, line in enumerate(src.splitlines()))
    return "\n".join(re.sub(r"^\s*#.*$", "", line) for line in kept)


auto_code = _without_docstrings(auto_src)


def _direct_page_calls(tree: ast.AST, attr: str) -> dict[str, int]:
    """Count `page.<attr>(...)` calls per enclosing function."""
    found: dict[str, int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        hits = sum(
            1 for sub in ast.walk(node)
            if isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and sub.func.attr == attr
            and isinstance(sub.func.value, ast.Name)
            and sub.func.value.id == "page"
        )
        if hits:
            found[node.name] = hits
    return found


# page.evaluate belongs to _safe_eval alone; page.goto to _goto_settled alone.
# Anywhere else is a call that can be destroyed by an SPA redirect mid-flight.
for attr, owner in (("evaluate", "_safe_eval"), ("goto", "_goto_settled")):
    callers = _direct_page_calls(auto_tree, attr)
    strays = {fn: n for fn, n in callers.items() if fn != owner}
    if strays:
        fails.append(
            f"page.{attr} called directly outside {owner}: {strays} — route it through the "
            f"helper, or a navigation mid-call kills the whole run "
            f"('Execution context was destroyed')"
        )
    if owner not in callers:
        fails.append(f"{owner} no longer calls page.{attr} itself")

for helper in ("_safe_eval", "_goto_settled", "_close_quietly", "_is_transient_eval_error"):
    if f"def {helper}" not in auto_src:
        fails.append(f"flow_automator.py no longer defines {helper}")

# _safe_eval must actually recover, not merely exist. Lifted and run against a
# fake page that dies the way Flow died — twice with a destroyed context, then
# fine — plus one that raises a genuine scripting error, which must NOT be retried
# into silence.
auto_wanted = {"_safe_eval", "_settle", "_is_transient_eval_error",
               "_TRANSIENT_EVAL_ERRORS", "FlowGenerationError"}
auto_picked = [
    node for node in auto_tree.body
    if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name in auto_wanted)
    or (isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id in auto_wanted for t in node.targets))
]


class _FakePlaywrightError(Exception):
    pass


class _FakePage:
    """Fails `n_failures` times with `message`, then returns `value`."""

    def __init__(self, message, n_failures, value="ok", exc=_FakePlaywrightError):
        self.message, self.left, self.value, self.exc = message, n_failures, value, exc
        self.calls = 0

    async def evaluate(self, script, arg=None):
        self.calls += 1
        if self.left > 0:
            self.left -= 1
            raise self.exc(self.message)
        return self.value

    async def wait_for_load_state(self, state, timeout=0):
        return None


_asyncio = __import__("asyncio")


async def _no_sleep(_seconds):
    """The retry backoff is real seconds; this check does not need to spend them."""
    return None


auto_ns: dict = {
    "asyncio": types.SimpleNamespace(sleep=_no_sleep),
    "PlaywrightError": _FakePlaywrightError,
    "print": lambda *a, **k: None,
}
exec(compile(ast.Module(body=auto_picked, type_ignores=[]), "<flow-ui-helpers>", "exec"), auto_ns)
safe_eval = auto_ns["_safe_eval"]
_run = _asyncio.run

DESTROYED = "Page.evaluate: Execution context was destroyed, most likely because of a navigation"

recovering = _FakePage(DESTROYED, 2)
try:
    got = _run(safe_eval(recovering, "() => 1", what="probe"))
    if got != "ok" or recovering.calls != 3:
        fails.append(
            f"_safe_eval did not recover from a destroyed context "
            f"(returned {got!r} after {recovering.calls} call(s))"
        )
except Exception as e:  # noqa: BLE001
    fails.append(f"_safe_eval raised instead of retrying a destroyed context: {e}")

hopeless = _FakePage(DESTROYED, 99)
try:
    _run(safe_eval(hopeless, "() => 1", attempts=2, what="probe"))
    fails.append("_safe_eval returned a value for a page that never settled")
except auto_ns["FlowGenerationError"]:
    pass
except Exception as e:  # noqa: BLE001
    fails.append(f"_safe_eval raised {type(e).__name__} instead of FlowGenerationError: {e}")

real_bug = _FakePage("ReferenceError: qeurySelector is not defined", 99)
try:
    _run(safe_eval(real_bug, "() => 1", attempts=3, what="probe"))
    fails.append("_safe_eval swallowed a real page error")
except _FakePlaywrightError:
    if real_bug.calls != 1:
        fails.append(
            f"_safe_eval retried a non-transient error {real_bug.calls} times — a genuine "
            "scripting bug would be hidden behind the retry loop"
        )
except Exception as e:  # noqa: BLE001
    fails.append(f"_safe_eval converted a real page error into {type(e).__name__}: {e}")

safe_eval_uses = len(re.findall(r"await _safe_eval\(", auto_src))
if safe_eval_uses < 5:
    fails.append(
        f"only {safe_eval_uses} _safe_eval call(s) found; the automator reads the page in more "
        "places than that, so one was likely reverted to a raw evaluate"
    )

if "execution context was destroyed" not in auto_src.lower():
    fails.append("_TRANSIENT_EVAL_ERRORS no longer covers 'execution context was destroyed'")

# Every failure path must hand the browser back, or the next run fights a lock.
raises_after_launch = len(re.findall(r"raise FlowGenerationError\(", auto_src))
closes = len(re.findall(r"await _close_quietly\(ctx\)", auto_src))
if closes < 3:
    fails.append(
        f"only {closes} _close_quietly(ctx) call(s) for {raises_after_launch} FlowGenerationError "
        "raise site(s) — a failure path that skips it leaves Chromium holding the profile"
    )

# Every failure path must hand the browser back, or the next run fights a lock.
gen_src = (ROOT / "app" / "services" / "generation.py").read_text(encoding="utf-8")
if "AUTO_ORDER: tuple[str, ...] = (FLOW_UI, FLOW_API)" not in gen_src:
    fails.append(
        "AUTO_ORDER is not (FLOW_UI, FLOW_API). The captured replay cannot be primary: its "
        "reCAPTCHA token is effectively single-use, so `auto` would spend its first attempt "
        "on a request that can only be rejected."
    )


# ── 3b. the project workspace is acquired, not guessed at once ─────────
# The failure: `flow_ui: failed — Could not open a Google Flow project workspace
# ... Landed on: https://labs.google/fx/tools/flow`, on a system that had generated
# successfully the same day. The automator ran ONE
# `querySelector('a[href*="/flow/project/"]')` two seconds after
# `domcontentloaded`. Flow fetches its project list after load and renders cards as
# divs with click handlers, so that question was asked too early, of an element
# Flow need not create. Acquisition must therefore poll, must remember what worked,
# and must tell a signed-out profile apart from an empty account.
for needed, why in (
    ("async def _open_project", "project acquisition must be one function, not inline steps"),
    ("async def _discover_project", "the dashboard must be polled while it hydrates"),
    ("async def _wait_for_project_route", "the SPA routes after goto; page.url is read too early"),
    ("def _remember_project_url", "a workspace that worked must be cached, not re-discovered"),
    ("def _is_project_url", "'project' in url also matches the dashboard that lists projects"),
    ("_JS_PROJECT_STATE", "one read must yield projects, sign-in state and the controls seen"),
):
    if needed not in auto_src:
        fails.append(f"flow_automator.py has no {needed} — {why}")

if 'querySelector(\'a[href*="/flow/project/"]\')' in auto_code:
    fails.append("the one-shot project-link querySelector is back; a hydrating dashboard defeats it")
if '"project" not in page.url' in auto_code:
    fails.append(
        "the loose project check is back: the Flow dashboard URL contains 'project' too, "
        "so a dashboard could pass for a workspace"
    )

open_src = auto_code[auto_code.find("async def _open_project("):]
open_src = open_src[:open_src.find("\n\nclass ", 10) if "\n\nclass " in open_src else len(open_src)]
open_src = open_src[:open_src.find("\n# ── ", 10) if "\n# ── " in open_src else len(open_src)]
order = [open_src.find("settings.flow_project_url"), open_src.find("_remembered_project_url()"),
         open_src.find("_discover_project("), open_src.find("_click_new_project(")]
if -1 in order:
    fails.append(f"_open_project is missing one of its four routes (offsets {order})")
elif order != sorted(order):
    fails.append(
        f"_open_project tries its routes out of order (offsets {order}); creating a project "
        "before discovery finishes piles a new workspace up beside the operator's every run"
    )
if "signed_in" not in open_src or "login_google_flow" not in open_src:
    fails.append(
        "_open_project cannot report a signed-out profile — the old message told the operator "
        "to create a project in a browser that is not logged in"
    )
if "_debug_shot" not in open_src:
    fails.append("a workspace that never opened must leave a screenshot; nothing else records it")


# ── 4. attribution comes from the network, not the DOM ─────────────────

# The bug this section exists for: `flow_ui` reported "produced 4 verified
# image(s)" for job 908692a5 and the gallery showed a forklift safety poster, a
# text card, an espresso machine and a skincare bottle. The automator had
# snapshotted the project canvas before submitting and treated anything new as
# output — but Flow's canvas lazily hydrates every past generation, so old images
# mounted after the snapshot and passed a guard that was, from the DOM's point of
# view, telling the truth.

media_src = (ROOT / "app" / "services" / "flow_media.py").read_text(encoding="utf-8")
media_tree = ast.parse(media_src)
media_wanted = {
    "MediaHarvest", "harvest_media", "looks_like_generation_url", "describe_shape",
    "endpoint_path", "_decode_inline", "_GENERATION_URL_MARKERS", "_LISTING_URL_MARKERS",
    "_INLINE_IMAGE_KEYS", "_MEDIA_URL_KEYS", "_B64_IMAGE_PREFIXES", "MIN_IMAGE_BYTES",
}
media_picked = [
    node for node in media_tree.body
    if (isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in media_wanted)
    or (isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id in media_wanted for t in node.targets))
    or (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        and node.target.id in media_wanted)
]
media_missing = media_wanted - {
    getattr(n, "name", None)
    or (n.target.id if isinstance(n, ast.AnnAssign) else n.targets[0].id)
    for n in media_picked
}
if media_missing:
    fails.append(f"flow_media.py no longer defines: {sorted(media_missing)}")

media_ns: dict = {
    "Any": object, "base64": __import__("base64"), "urlsplit": __import__("urllib.parse", fromlist=["urlsplit"]).urlsplit,
    "dataclass": __import__("dataclasses").dataclass, "field": __import__("dataclasses").field,
    "logger": types.SimpleNamespace(warning=lambda *a, **k: None, debug=lambda *a, **k: None),
}
exec(compile(ast.Module(body=media_picked, type_ignores=[]), "<flow-media>", "exec"), media_ns)
is_generation = media_ns["looks_like_generation_url"]
harvest_media = media_ns["harvest_media"]
describe_shape = media_ns["describe_shape"]

GEN_URLS = [
    "https://aisandbox-pa.googleapis.com/v1/flowMedia:batchGenerateImages",
    "https://aisandbox-pa.googleapis.com/v1/whatever:generateImage?alt=json",
    "https://labs.google/fx/api/trpc/media.runImageFx",
]
NOT_GEN_URLS = [
    # The important half: a listing endpoint names media that already existed, so
    # matching one would re-create the original bug through a different door.
    "https://aisandbox-pa.googleapis.com/v1/projects/p/media:list",
    "https://aisandbox-pa.googleapis.com/v1/ListGeneratedMedia",
    "https://aisandbox-pa.googleapis.com/v1/project:loadProject",
    "https://aisandbox-pa.googleapis.com/v1/media:batchGet",
    "https://lh3.googleusercontent.com/abc123?getMediaUrlRedirect=1&token=x",
    "",
]
for url in GEN_URLS:
    if not is_generation(url):
        fails.append(f"looks_like_generation_url rejected a real generation endpoint: {url}")
for url in NOT_GEN_URLS:
    if is_generation(url):
        fails.append(
            f"looks_like_generation_url accepted {url!r} — a listing response would be "
            "credited to the job, which is the canvas bug again"
        )

# Harvest: inline bytes and media URLs, in the order Flow listed them.
big_jpeg_b64 = base64.b64encode(b"\xff\xd8\xff" + b"j" * 9000).decode()
if not big_jpeg_b64.startswith("/9j/"):
    fails.append("test fixture is not recognisable as JPEG base64; check _B64_IMAGE_PREFIXES")
payload = {
    "media": [
        {"generatedImage": {"encodedImage": big_jpeg_b64, "seed": 12},
         "mediaId": "one"},
        {"generatedImage": {"imageUri": "https://x/getMediaUrlRedirect?id=2"}},
        {"generatedImage": {"fifeUrl": "https://x/getMediaUrlRedirect?id=3"}},
        {"generatedImage": {"fifeUrl": "https://x/getMediaUrlRedirect?id=3"}},  # duplicate
    ],
    "clientContext": {"recaptchaContext": {"token": "SECRET-TOKEN-VALUE"}},
}
got = harvest_media(payload)
if len(got.inline) != 1:
    fails.append(f"harvest_media found {len(got.inline)} inline image(s), expected 1")
if got.urls != ["https://x/getMediaUrlRedirect?id=2", "https://x/getMediaUrlRedirect?id=3"]:
    fails.append(f"harvest_media lost order or kept a duplicate URL: {got.urls}")
if got.total != 3:
    fails.append(f"harvest_media total is {got.total}, expected 3")
if not harvest_media({"media": []}).total == 0:
    fails.append("harvest_media invented media for an empty response")

# A tiny base64 blob is an icon or a spinner, not a generated image.
if harvest_media({"encodedImage": base64.b64encode(b"\xff\xd8\xff" + b"j" * 50).decode()}).total:
    fails.append(f"harvest_media accepted a blob under {media_ns['MIN_IMAGE_BYTES']} bytes")

# The shape outline is used in error messages; it must never carry a token.
outline = describe_shape(payload)
if "SECRET-TOKEN-VALUE" in outline or big_jpeg_b64[:20] in outline:
    fails.append("describe_shape leaked a payload value into an error message")
if "recaptchaContext" not in outline:
    fails.append(f"describe_shape lost the response structure: {outline}")

# The DOM diff must not come back.
for banned, why in (
    ("initial_srcs", "the pre-submit canvas snapshot that mis-attributed old images"),
    ("target_total", "the canvas-count target that let hydration satisfy the wait"),
):
    if banned in auto_src:
        fails.append(f"flow_automator.py references {banned!r} again — {why}")

if "page.mouse.click(640" in auto_src or "916, y: 793" in auto_src:
    fails.append(
        "flow_automator still clicks a hardcoded coordinate to reach the prompt bar; a "
        "moved layout means the prompt is typed nowhere and Flow re-runs its last request"
    )

for needed, why in (
    ("_GenerationWatcher", "attribution now comes from Flow's generation response"),
    ("watcher.arm()", "the watcher must be armed for exactly this submit"),
    ("_enter_prompt", "the prompt must be typed through a located field"),
    ("_JS_READ_FOCUSED", "the prompt must be read back before submitting"),
    ("_save_harvest", "only harvested media may be written to disk"),
):
    if needed not in auto_src:
        fails.append(f"flow_automator.py no longer has {needed} — {why}")

# Order matters: prompt in the box, then arm, then click.
order = [auto_src.find("await _enter_prompt("), auto_src.find("watcher.arm()"),
         auto_src.find("await _submit_prompt(")]
if -1 in order or order != sorted(order):
    fails.append(
        f"the run does not go _enter_prompt -> watcher.arm -> _submit_prompt (offsets {order}); "
        "arming late loses the response, arming early can pick up page-load media"
    )

# _save_harvest must number files by what it actually saved, so a failed download
# leaves no gap and never silently shifts a variation onto another image.
save_wanted = {"_save_harvest"}
save_picked = [n for n in auto_tree.body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in save_wanted]
if not save_picked:
    fails.append("flow_automator.py no longer defines _save_harvest")
else:
    tmp_out = Path(__import__("tempfile").mkdtemp()) / "job"
    tmp_out.mkdir(parents=True, exist_ok=True)

    async def _fake_fetch(_page, url):
        return None if url.endswith("BAD") else b"\xff\xd8\xff" + b"u" * 9000

    save_ns: dict = {
        "Any": object, "Path": Path, "MediaHarvest": media_ns["MediaHarvest"],
        "MIN_IMAGE_BYTES": media_ns["MIN_IMAGE_BYTES"], "_fetch_media": _fake_fetch,
        "print": lambda *a, **k: None,
    }
    exec(compile(ast.Module(body=save_picked, type_ignores=[]), "<flow-save>", "exec"), save_ns)
    h = media_ns["MediaHarvest"](
        inline=[b"\xff\xd8\xff" + b"i" * 9000],
        urls=["https://x/BAD", "https://x/ok2", "https://x/ok3", "https://x/ok4"],
    )
    saved, problems = _run(save_ns["_save_harvest"](None, h, tmp_out, "jobX", 4))
    want = [f"data/outputs/jobX/flow_var_{i}.jpg" for i in (1, 2, 3, 4)]
    if saved != want:
        fails.append(f"_save_harvest numbered files {saved}, expected {want}")
    if len(problems) != 1:
        fails.append(f"_save_harvest reported {len(problems)} problem(s) for one dead URL")
    if len(list(tmp_out.glob('*.jpg'))) != 4:
        fails.append("_save_harvest did not write one file per saved variation")
    over = _run(save_ns["_save_harvest"](None, h, tmp_out, "jobX", 2))[0]
    if len(over) != 2:
        fails.append(f"_save_harvest ignored the requested count: saved {len(over)} for count=2")


# ── 5. the prompt reaches the box as ONE line, with no key events ───────
# The worst failure of the three, because it looked like a validation error while
# it was actually generating: `keyboard.type` replays every character as a real key
# press, and Flow's prompt bar sends on Enter. A 13-section prompt therefore
# submitted itself section by section — twelve unrequested generations from
# fragments of a brief, one of them a picture of the word "AVOID:" — and the run
# then failed its own read-back with "256 of 2040 characters present".
flat_wanted = {"flatten_prompt", "SECTION_SEPARATOR"}
flat_picked = [
    n for n in auto_tree.body
    if isinstance(n, (ast.FunctionDef, ast.Assign, ast.AnnAssign))
    and (getattr(n, "name", None) in flat_wanted
         or any(getattr(t, "id", None) in flat_wanted for t in getattr(n, "targets", [])))
]
if not any(getattr(n, "name", None) == "flatten_prompt" for n in flat_picked):
    fails.append("flow_automator.py no longer defines flatten_prompt")
else:
    flat_ns: dict = {}
    exec(compile(ast.Module(body=flat_picked, type_ignores=[]), "<flow-flat>", "exec"), flat_ns)
    flatten = flat_ns["flatten_prompt"]

    thirteen = "\n\n".join([
        "PHOTOGRAPHIC INTENT:\nA person photographing what they just bought.",
        "SUBJECT:\nPress-On Nails in Chrome Cherry — a set of press-on nails.",
        "AVOID:\nStudio product photography, catalog styling.",
    ])
    one_line = flatten(thirteen)
    if "\n" in one_line or "\r" in one_line:
        fails.append("flatten_prompt left a newline in the prompt — Flow reads Enter as send")
    for fragment in ("PHOTOGRAPHIC INTENT:", "Chrome Cherry", "Studio product photography"):
        if fragment not in one_line:
            fails.append(f"flatten_prompt dropped {fragment!r} from the prompt")
    if one_line.count(flat_ns["SECTION_SEPARATOR"].strip()) != 2:
        fails.append(f"flatten_prompt did not keep the section boundaries: {one_line!r}")
    if flatten("a\n\n\n\nb") != f"a{flat_ns['SECTION_SEPARATOR']}b":
        fails.append(f"flatten_prompt mishandles blank runs: {flatten('a' + chr(10) * 4 + 'b')!r}")
    if flatten("   ") != "":
        fails.append("flatten_prompt should render a whitespace-only prompt as empty")

# The delivery mechanism itself.
if "insert_text(page, flat)" not in auto_src:
    fails.append(
        "flow_automator no longer delivers the prompt through browser_utils.insert_text; "
        "keyboard.type sends each newline as Enter, which is Flow's send key"
    )
if "keyboard.type(prompt" in auto_src or "keyboard.type(prompt_text" in auto_src:
    fails.append("flow_automator types the raw multi-line prompt again — every newline submits")

enter_src = auto_src[auto_src.find("async def _enter_prompt("):]
enter_src = enter_src[:enter_src.find("\nasync def ", 10)]
for needed, why in (
    ("flatten_prompt(prompt)", "the prompt must be flattened before it is inserted"),
    ('"\\n" in flat', "a newline must be refused outright, not merely avoided"),
):
    if needed not in enter_src:
        fails.append(f"_enter_prompt is missing {needed} — {why}")
if enter_src.find("flat = flatten_prompt(prompt)") > enter_src.find("insert_text(page, flat)"):
    fails.append("_enter_prompt inserts before it flattens")

# ── 6. Playwright method names are the ones Playwright actually has ──────
# `await page.keyboard.insertText(flat)` shipped and failed a live run with
# "'Keyboard' object has no attribute 'insertText'". Playwright's Python bindings
# rename every JS method to snake_case, and an AttributeError is not a
# PlaywrightError, so the fallback never caught it. Two guards: no camelCase call
# survives review, and — when playwright is installed — the names are checked
# against the classes themselves.
PLAYWRIGHT_MODULES = (
    ROOT / "app" / "services" / "flow_automator.py",
    ROOT / "app" / "services" / "pinterest_publisher.py",
    ROOT / "app" / "services" / "browser_utils.py",
)
CAMEL_OK = {"getLogger", "basicConfig"}  # stdlib logging, not Playwright
_camel = re.compile(r"^[a-z][a-z0-9_]*[A-Z]")
for module_path in PLAYWRIGHT_MODULES:
    for node in ast.walk(ast.parse(module_path.read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        attr = node.func.attr
        if _camel.match(attr) and attr not in CAMEL_OK:
            fails.append(
                f"{module_path.name}:{node.lineno} calls .{attr}() — Playwright's Python API "
                f"is snake_case; camelCase raises AttributeError at run time"
            )

try:
    from playwright.async_api import Keyboard, Locator, Page  # type: ignore
except Exception as e:  # playwright is not installed in every checkout
    notes.append(f"Playwright not importable here ({type(e).__name__}); "
                 "method names checked by the camelCase ban only")
else:
    for cls, method in (
        (Keyboard, "insert_text"), (Keyboard, "type"), (Keyboard, "press"),
        (Page, "evaluate"), (Page, "goto"), (Page, "locator"), (Page, "screenshot"),
        (Locator, "click"), (Locator, "count"), (Locator, "fill"),
        (Locator, "set_input_files"), (Locator, "scroll_into_view_if_needed"),
    ):
        if not hasattr(cls, method):
            fails.append(f"playwright {cls.__name__} has no {method}() — the automator calls it")

# ── 7. insert_text: one insertion, and it refuses to type a newline ──────
sys.path.insert(0, str(ROOT))
import logging as _logging  # noqa: E402

_logging.getLogger("pre.browser_utils").setLevel(_logging.CRITICAL)  # the fallbacks log on purpose
from app.services.browser_utils import TextEntryError  # noqa: E402
from app.services.browser_utils import insert_text as _insert_text  # noqa: E402


class _FakeKeyboard:
    def __init__(self, with_insert: bool):
        self.typed: list[str] = []
        self.inserted: list[str] = []
        self.key_events = 0
        if with_insert:
            self.insert_text = self._insert

    async def _insert(self, text):
        self.inserted.append(text)

    async def type(self, text, delay=0):
        self.typed.append(text)
        self.key_events += len(text)


class _FakeSession:
    def __init__(self, sent):
        self.sent = sent

    async def send(self, method, params):
        self.sent.append((method, params))


class _FakeContext:
    def __init__(self, cdp: bool, sent):
        self._cdp, self._sent = cdp, sent

    async def new_cdp_session(self, page):
        if not self._cdp:
            raise RuntimeError("no CDP here")
        return _FakeSession(self._sent)


class _FakePage:
    def __init__(self, with_insert=True, cdp=True):
        self.keyboard = _FakeKeyboard(with_insert)
        self.sent: list = []
        self.context = _FakeContext(cdp, self.sent)


page1 = _FakePage(with_insert=True)
if _run(_insert_text(page1, "a | b")) != "keyboard.insert_text":
    fails.append("insert_text did not prefer keyboard.insert_text when it exists")
if page1.keyboard.key_events:
    fails.append("insert_text generated key events — Flow reads Enter as send")

page2 = _FakePage(with_insert=False, cdp=True)
if _run(_insert_text(page2, "a | b")) != "CDP Input.insertText":
    fails.append("insert_text did not fall back to the DevTools protocol")
if page2.sent != [("Input.insertText", {"text": "a | b"})]:
    fails.append(f"insert_text sent the wrong CDP payload: {page2.sent}")

page3 = _FakePage(with_insert=False, cdp=False)
if _run(_insert_text(page3, "a | b")) != "keyboard.type":
    fails.append("insert_text has no last-resort typing path")
try:
    _run(_insert_text(_FakePage(with_insert=False, cdp=False), "line1\nline2"))
    fails.append("insert_text typed a newline — that keystroke submits the form")
except TextEntryError:
    pass

# ── 8. a submit is confirmed, never assumed ─────────────────────────────
# The third failure of the same family: `_submit_prompt` clicked the right-most
# button in the prompt bar's band, which was Flow's add-reference control — its
# innerText is the Material Symbols ligature `image`, logged as 'image\nAVOID:'.
# Nothing was submitted, no generation request left the browser, and the run sat
# out its full 210 s timeout before reporting "0 media named".
submit_src = auto_src[auto_src.find("async def _submit_prompt("):]
submit_src = submit_src[:submit_src.find("\n# ── ", 10)]
if submit_src.find('keyboard.press("Enter")') > submit_src.find("_SUBMIT_SELECTORS"):
    fails.append(
        "_submit_prompt hunts for a button before it presses Enter — Enter is Flow's "
        "send key and cannot land on the wrong control"
    )
for needed, why in (
    ("_submit_landed", "every strategy must be confirmed before it counts as a submit"),
    ("_JS_PAGE_ALERTS", "a failed submit must report what the page said"),
    ("_debug_shot", "a failed submit must leave a screenshot"),
):
    if needed not in submit_src:
        fails.append(f"_submit_prompt no longer uses {needed} — {why}")
for ligature in ("'image'", "'add_photo_alternate'", "'attach_file'"):
    if ligature not in auto_src:
        fails.append(f"the submit scorer no longer excludes the {ligature} icon button")
if "NO_REQUEST_GIVE_UP_SECONDS" not in auto_src:
    fails.append("the wait loop no longer gives up early when no generation request was sent")

land_wanted = {"_submit_landed"}
land_picked = [n for n in auto_tree.body
               if isinstance(n, ast.AsyncFunctionDef) and n.name in land_wanted]
if not land_picked:
    fails.append("flow_automator.py no longer defines _submit_landed")
else:
    class _FakeWatcher:
        def __init__(self):
            self.generation_requests: list[str] = []

            class _H:
                total = 0
            self.harvest = _H()

    class _Clock:
        """Advances 0.6 s per sleep, so the loop's own deadline ends the test."""
        def __init__(self):
            self.t = 0.0

        def time(self):
            return self.t

    land_ns: dict = {"_norm": lambda s: " ".join(str(s).split()).lower()}
    _clock = _Clock()

    class _Loop:
        @staticmethod
        def time():
            return _clock.t

    async def _sleep(seconds):
        _clock.t += seconds

    land_ns["asyncio"] = types.SimpleNamespace(
        sleep=_sleep, get_event_loop=lambda: _Loop())
    _reads: list[str] = []
    land_ns["_read_prompt_field"] = lambda page, box: _pop_read()

    async def _pop_read_impl():
        return _reads.pop(0) if _reads else "x" * 500

    def _pop_read():
        return _pop_read_impl()

    exec(compile(ast.Module(body=land_picked, type_ignores=[]), "<flow-land>", "exec",
                 __future__.annotations.compiler_flag), land_ns)
    landed = land_ns["_submit_landed"]

    # Nothing happens: not a submit.
    if _run(landed(None, None, _FakeWatcher(), 500, 3.0)) is not None:
        fails.append("_submit_landed called a submit confirmed while nothing changed")

    # A generation request went out: that is proof.
    w = _FakeWatcher()
    w.generation_requests.append("/v1/flowMedia:batchGenerateImages")
    evidence = _run(landed(None, None, w, 500, 3.0))
    if not evidence or "batchGenerateImages" not in evidence:
        fails.append(f"_submit_landed ignored the generation request: {evidence!r}")

    # The prompt bar emptied: also proof.
    _reads.extend(["", "", ""])
    if _run(landed(None, None, _FakeWatcher(), 500, 3.0)) != "prompt bar cleared":
        fails.append("_submit_landed did not treat a cleared prompt bar as a submit")

# ── report ──────────────────────────────────────────────────────────────

if fails:
    print("FAIL — Flow backends")
    for f in fails:
        print(f"  • {f}")
    for n in notes:
        print(f"  · note: {n}")
    sys.exit(1)

print("PASS — Flow backends")
print(f"  header sanitiser: dropped {len(PSEUDO)} pseudo-headers, kept {len(clean)} real header(s)")
print(f"  flow_automator: page.evaluate confined to _safe_eval ({safe_eval_uses} call sites), "
      f"page.goto to _goto_settled, {closes} guarded teardown(s)")
print("  _safe_eval: recovers from a destroyed context, gives up honestly, "
      "does not retry real page errors")
print("  project workspace: configured URL -> remembered URL -> polled dashboard -> "
      "new project, with a signed-out profile reported as such")
print(f"  attribution: {len(GEN_URLS)} generation endpoint(s) matched, {len(NOT_GEN_URLS)} "
      "listing/media URL(s) refused, response order preserved, no DOM diff")
print("  _save_harvest: numbers variations by what was saved; a dead URL leaves no gap")
print("  prompt entry: flattened to one line, delivered by browser_utils.insert_text — "
      "no keystroke Flow can read as send")
print("  Playwright names: no camelCase call in the 3 browser module(s); insert_text "
      "prefers keyboard.insert_text, then CDP, and refuses to type a newline")
print("  AUTO_ORDER = (flow_ui, flow_api) — browser automation primary")
for n in notes:
    print(f"  · note: {n}")
