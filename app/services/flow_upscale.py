"""
Pinterest Realism Engine — Google Flow 2K/4K upsampling.

The generation endpoint answers at render resolution (~1024px on the long
edge, less when the canvas is busy). Flow's UI offers *Download (2K)* on every
image: a server-side upsampler at

    POST https://aisandbox-pa.googleapis.com/v1/flow/upsampleImage
    {"mediaId": "<mediaGenerationId>",
     "targetResolution": "UPSAMPLE_IMAGE_RESOLUTION_2K" | "_4K",
     "clientContext": {"sessionId": ";<ms>", "projectId": "...", "tool": "PINHOLE"}}

which returns `{"encodedImage": "<base64 JPEG>"}`. `2K` works on free
accounts; `4K` is gated to paid plans (Google reports the gate as a
reCAPTCHA rejection, so a 403 there means "plan", not "captcha").

Both Flow backends call this module:

  * `flow_automator` reuses the authorization header and clientContext its
    network watcher captured from the generation request, and sends the
    upsample through `page.request` so the profile's cookies ride along.
  * `flow_direct_api` reuses the captured session's headers over httpx.

No playwright or httpx import at module level: the callers hand in an
executor, so this stays importable in the verifier environment, same rule as
`flow_media`.
"""

from __future__ import annotations

import base64
import logging
import time
from typing import Any, Awaitable, Callable

from app.services.flow_media import MIN_IMAGE_BYTES

logger = logging.getLogger("pre.flow_upscale")

#: What the UI's resolution menu maps to on the wire.
RESOLUTION_ENUMS = {
    "2k": "UPSAMPLE_IMAGE_RESOLUTION_2K",
    "4k": "UPSAMPLE_IMAGE_RESOLUTION_4K",
}

UPSCALE_PATH = "/flow/upsampleImage"

#: The upsampler is slower than the renderer; the CLI this is modelled on
#: allows 300 s. 120 s covers the observed range without stalling a job.
UPSCALE_TIMEOUT_MS = 120_000


def new_session_id() -> str:
    """Flow's session id shape: a semicolon followed by epoch milliseconds."""
    return ";" + str(int(time.time() * 1000))


def api_base_from_generation_url(url: str) -> str | None:
    """
    `https://aisandbox-pa.googleapis.com/v1` from a generation request URL.

    The upsample endpoint is sibling to the project-scoped generation path, so
    the base is everything before `/projects/`. Deriving it (rather than
    hardcoding the host) keeps a future Google rename visible in one place.
    """
    if not url or "/projects/" not in url:
        return None
    return url.split("/projects/", 1)[0]


def build_upscale_payload(
    media_id: str,
    resolution: str = "2k",
    project_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """
    The upsample request body.

    No `recaptchaContext` on purpose: the generation request's reCAPTCHA token
    is single-use, and the UI's own upsample call goes out from an already
    authenticated session. If Google starts demanding a token here, the call
    fails with 403 and the caller falls back to the render-resolution bytes —
    which is the documented failure mode, not a crash.
    """
    enum = RESOLUTION_ENUMS.get(resolution.lower(), RESOLUTION_ENUMS["2k"])
    client_context: dict[str, Any] = {
        "sessionId": session_id or new_session_id(),
        "tool": "PINHOLE",
    }
    if project_id:
        client_context["projectId"] = project_id
    return {
        "mediaId": media_id,
        "targetResolution": enum,
        "clientContext": client_context,
    }


#: Keys Google's responses have used for base64 image payloads. The upsample
#: endpoint is undocumented; the CLI this is modelled on reads `encodedImage`,
#: but batchGenerate responses nest the bytes under media objects, so a small
#: search beats assuming one shape.
_ENCODED_KEYS = ("encodedImage", "encoded_image", "imageBytes", "image")


def _find_encoded(node: Any, depth: int = 0) -> str | None:
    """Depth-limited search for a long base64 string under a known key."""
    if depth > 4:
        return None
    if isinstance(node, list):
        for item in node:
            found = _find_encoded(item, depth + 1)
            if found:
                return found
        return None
    if not isinstance(node, dict):
        return None
    for key in _ENCODED_KEYS:
        val = node.get(key)
        if isinstance(val, str) and len(val) > 200:  # an image's base64 is long
            return val
    for val in node.values():
        found = _find_encoded(val, depth + 1)
        if found:
            return found
    return None


def describe_shape(data: Any) -> str:
    """Top-level key list, for 'the endpoint changed shape' log lines."""
    if isinstance(data, dict):
        return ",".join(str(k) for k in list(data.keys())[:8]) or "(empty dict)"
    return type(data).__name__


def decode_upscale_response(data: Any) -> bytes | None:
    """Base64 JPEG bytes out of an upsample response, or None if unusable."""
    if not isinstance(data, dict):
        return None
    encoded = _find_encoded(data)
    if not encoded:
        return None
    payload = encoded.split(";base64,")[-1]
    try:
        decoded = base64.b64decode(payload, validate=False)
    except (ValueError, TypeError):
        return None
    return decoded if len(decoded) >= MIN_IMAGE_BYTES else None


def media_id_candidates(media_id: str) -> list[str]:
    """
    Id forms to offer the upsampler, most-likely first.

    Newer generation responses identify media by AIP resource name
    (`projects/…/flowMedia/<id>` or similar). The documented upsample field
    `mediaId` expects the bare id segment, so that goes first; the full
    resource name stays as the fallback for a server that stored it
    verbatim. One form when there is no path to split.
    """
    bare = media_id.rsplit("/", 1)[-1] if "/" in media_id else media_id
    out: list[str] = []
    for cand in (bare, media_id):
        if cand and cand not in out:
            out.append(cand)
    return out


#: An executor takes (url, payload) and returns the decoded JSON body, raising
#: on transport or HTTP errors. Both backends provide their own.
UpscaleExecutor = Callable[[str, dict[str, Any]], Awaitable[Any]]

#: Optional failure reporter. The backends run in a background process whose
#: stderr is not surfaced to the job console, so failures must also reach the
#: caller through this hook (print) to be diagnosable. Receives one
#: human-readable sentence per failure.
FailureReporter = Callable[[str], None]


async def upscale_to_bytes(
    execute: UpscaleExecutor,
    api_base: str,
    media_id: str,
    *,
    resolution: str = "2k",
    project_id: str | None = None,
    on_failure: FailureReporter | None = None,
) -> bytes | None:
    """
    Upsample one variation and return its bytes, or None on any failure.

    Never raises: a failed upscale must not cost the variation, because the
    render-resolution bytes are a perfectly good fallback. This is the same
    original-image-fallback contract the reference CLI implements.
    """
    url = api_base + UPSCALE_PATH
    payload = build_upscale_payload(media_id, resolution, project_id=project_id)
    try:
        data = await execute(url, payload)
    except Exception as e:  # noqa: BLE001 — fallback, not fatal
        reason = f"upsample of {media_id[:24]}… failed: {e}"
        logger.warning("%s; keeping render resolution.", reason)
        if on_failure:
            on_failure(reason)
        return None
    body = decode_upscale_response(data)
    if body is None:
        reason = (
            f"upsample of {media_id[:24]}… returned no usable image "
            f"(response keys: {describe_shape(data)})"
        )
        logger.warning("%s; keeping render resolution.", reason)
        if on_failure:
            on_failure(reason)
    return body
