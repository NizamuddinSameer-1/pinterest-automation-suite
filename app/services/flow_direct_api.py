"""
Pinterest Realism Engine — Direct Google Flow / ImageFX request replay.

Replays the intercepted Google Flow request (`data/captured_flow_session.json`)
over HTTP with a new prompt, extracting the generated images without driving the
UI. This is **not** an official or documented Google API: it is a captured
browser request re-sent from Python, and it inherits every limit of the
credentials inside that capture —

  * `authorization` is a Google OAuth access token, good for about an hour;
  * `clientContext.recaptchaContext.token` is a reCAPTCHA Enterprise token,
    short-lived and effectively single-use.

Neither can be refreshed without a browser, so this backend is an opportunistic
speed-up for the minutes after a capture, not a dependable path. `flow_automator`
(Playwright against the real UI) authenticates from a persistent profile and is
therefore the primary backend in `AUTO_ORDER`.

Nothing calls this directly: `app.services.generation.generate_variations` owns
backend selection, on-disk verification and the fallback order.
"""

from __future__ import annotations

import json
import logging
import random
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.services.flow_media import MIN_IMAGE_BYTES, describe_shape, harvest_media, harvest_variations

logger = logging.getLogger("pre.flow_direct_api")

SESSION_FILE = Path("./data/captured_flow_session.json").resolve()

#: Headers the HTTP client must own, not the capture. `content-length` and `host`
#: are recomputed for the new body/connection; `accept-encoding` and `connection`
#: describe transport httpx negotiates itself.
_CLIENT_OWNED_HEADERS = frozenset({"content-length", "host", "accept-encoding", "connection"})

#: How long a capture is worth replaying. The captured payload carries a
#: `clientContext.recaptchaContext.token`, which reCAPTCHA Enterprise issues as a
#: short-lived, effectively single-use credential, and the `authorization` header
#: is a Google OAuth access token (~1 hour). Neither can be refreshed from here,
#: so a capture is a *one-shot* artefact rather than a stored login. Replaying an
#: old one costs a 90-second round trip and comes back as an opaque rejection, so
#: it is refused up front instead.
CAPTURE_MAX_AGE_SECONDS = 15 * 60


class FlowSessionError(RuntimeError):
    """The captured Flow session is missing, malformed or no longer accepted."""


def _sanitise_headers(headers: Any) -> dict[str, str]:
    """
    Turn captured browser headers into headers `httpx` will accept.

    Playwright records the request as Chrome sent it — over HTTP/2, which carries
    the request line as the pseudo-headers `:authority`, `:method`, `:path` and
    `:scheme`. Those are not real header fields: h11 rejects any name starting
    with `:`, which is where `Illegal header name b':authority'` came from. The
    information in them is already in the URL, so they are dropped rather than
    translated.
    """
    if not isinstance(headers, dict):
        raise FlowSessionError(
            f"Captured session 'headers' is {type(headers).__name__}, expected an object."
        )

    clean: dict[str, str] = {}
    dropped_pseudo: list[str] = []
    for raw_key, raw_value in headers.items():
        # A capture written by a different tool may hold bytes keys/values; the
        # error text `b':authority'` is exactly what a bytes name looks like once
        # h11 reports it, so normalise before deciding what to keep.
        key = raw_key.decode("latin-1") if isinstance(raw_key, bytes) else str(raw_key)
        value = raw_value.decode("latin-1") if isinstance(raw_value, bytes) else str(raw_value)
        key = key.strip()

        if key.startswith(":"):
            dropped_pseudo.append(key)
            continue
        if key.lower() in _CLIENT_OWNED_HEADERS:
            continue
        if not key or "\n" in key or "\r" in key:
            # Never forward a name that could split the request line.
            logger.warning("Dropping malformed captured header name %r", key)
            continue
        clean[key] = value.replace("\n", " ").replace("\r", " ")

    if dropped_pseudo:
        logger.debug("Dropped %d HTTP/2 pseudo-header(s): %s",
                     len(dropped_pseudo), ", ".join(sorted(dropped_pseudo)))
    return clean


def capture_age_seconds() -> float | None:
    """
    Seconds since the session was captured, or None if there is no capture.

    Prefers the `captured_at` the capture script writes; falls back to the file's
    modification time so captures taken before that field existed still report an
    age instead of pretending to be fresh.
    """
    if not SESSION_FILE.exists():
        return None
    try:
        data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        captured_at = data.get("captured_at")
        if isinstance(captured_at, (int, float)):
            return max(0.0, time.time() - float(captured_at))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    try:
        return max(0.0, time.time() - SESSION_FILE.stat().st_mtime)
    except OSError:
        return None


def _replace_prompt_recursively(data: Any, new_prompt: str) -> Any:
    """Recursively search and replace prompt strings in arbitrary JSON payloads."""
    if isinstance(data, dict):
        new_dict = {}
        for k, v in data.items():
            k_lower = k.lower()
            if k_lower in ["prompt", "text"] and isinstance(v, str):
                new_dict[k] = new_prompt
            elif k_lower in ["prompts"] and isinstance(v, list):
                new_dict[k] = [new_prompt] if len(v) == 1 else [new_prompt] + v[1:]
            elif isinstance(v, (dict, list)):
                new_dict[k] = _replace_prompt_recursively(v, new_prompt)
            else:
                new_dict[k] = v
        return new_dict
    elif isinstance(data, list):
        return [_replace_prompt_recursively(item, new_prompt) for item in data]
    return data


def _freshen_request_identity(data: Any) -> Any:
    """
    Give each replay its own batch id and seed.

    The capture pins both: every replay reused one `mediaGenerationContext.batchId`
    and one `requests[].seed`, so the same prompt always came back as the same
    image and every job filed itself under the batch of whichever generation was
    captured. Only these two fields are touched — the rest of the payload is the
    server's contract and is left exactly as recorded.
    """
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if k == "batchId" and isinstance(v, str):
                out[k] = str(uuid.uuid4())
            elif k == "seed" and isinstance(v, int) and not isinstance(v, bool):
                out[k] = random.randint(1, 999_999)
            elif isinstance(v, (dict, list)):
                out[k] = _freshen_request_identity(v)
            else:
                out[k] = v
        return out
    if isinstance(data, list):
        return [_freshen_request_identity(item) for item in data]
    return data


async def generate_images_via_direct_flow_api(
    prompt: str,
    job_id: str,
    count: int = 4,
) -> list[str]:
    """
    Directly replays the captured Google Flow API request with the given prompt.

    Returns storage-relative image paths (`data/outputs/<job_id>/flow_api_N.jpg`).

    Raises:
        FlowSessionError: the capture is missing, malformed, older than
            `CAPTURE_MAX_AGE_SECONDS`, or Flow answered with something that is not
            a usable JSON payload. `generation._run_flow_api` turns this into
            `GenerationUnavailable`, so under `auto` the browser backend takes over.
        RuntimeError: Flow answered but no image could be extracted or downloaded.
    """
    if not prompt or not prompt.strip():
        raise ValueError("refusing to call Google Flow with an empty prompt")

    output_dir = settings.outputs_path / job_id
    output_dir.mkdir(parents=True, exist_ok=True)

    if not SESSION_FILE.exists():
        raise FlowSessionError(
            "captured_flow_session.json not found. Run the 1-Time Session Capture first."
        )

    try:
        session_data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise FlowSessionError(f"captured_flow_session.json is unreadable: {e}") from e

    url = session_data.get("url")
    headers = session_data.get("headers", {})
    json_payload = session_data.get("json_payload")

    if not url or not json_payload:
        raise FlowSessionError("Captured session file is missing URL or payload structure.")

    # Refuse a stale capture before spending a 90-second request on it. Under
    # `auto` this becomes a GenerationUnavailable, so the browser backend picks
    # the job up immediately instead of after a timeout.
    age = capture_age_seconds()
    if age is not None and age > CAPTURE_MAX_AGE_SECONDS:
        raise FlowSessionError(
            f"The captured Flow session is {age / 60:.0f} minutes old (limit "
            f"{CAPTURE_MAX_AGE_SECONDS // 60}). Its reCAPTCHA token is single-use and its "
            "OAuth token expires after about an hour, so replaying it would be rejected. "
            "Re-run the 1-Time Session Capture, or use the flow_ui backend, which "
            "authenticates from the browser profile and does not expire."
        )

    filtered_headers = _sanitise_headers(headers)

    # Inject new prompt into captured payload, then give the replay its own
    # identity so it is not a byte-for-byte re-send of the captured generation.
    updated_payload = _freshen_request_identity(
        _replace_prompt_recursively(json_payload, prompt)
    )

    logger.info("Dispatching direct API call to Google Flow (%s)...", url[:60])

    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(
            url,
            headers=filtered_headers,
            json=updated_payload,
        )

        if response.status_code in (401, 403):
            raise FlowSessionError(
                f"Google Flow rejected the captured session (HTTP {response.status_code}). "
                "Run the 1-Time Session Capture again to refresh it."
            )

        if response.status_code != 200:
            raise RuntimeError(
                f"Google Flow API returned status {response.status_code}: {response.text[:300]}"
            )

        try:
            res_json = response.json()
        except ValueError as e:
            # An expired session often returns the sign-in page as HTML with
            # HTTP 200. Treat that as an expired capture, not a generation bug.
            snippet = response.text[:200].replace("\n", " ")
            raise FlowSessionError(
                "Google Flow answered HTTP 200 with a non-JSON body — the captured "
                f"session has most likely expired. First 200 chars: {snippet!r}"
            ) from e

        # Extract images. Inline bytes are preferred; a URL-only response is
        # downloaded here, while the credentials are still in scope. The harvester
        # is shared with `flow_automator`, which reads the same payload off the
        # network instead of replaying it.
        harvest = harvest_media(res_json)
        variations = harvest_variations(res_json)
        image_bytes_list: list[bytes] = []

        # 2K upsampling: the captured session's OAuth header is replayed against
        # the upsample endpoint (sibling to generation). The reCAPTCHA token in
        # the capture is single-use and is deliberately not re-sent — a 403 here
        # just means "plan/captcha gate" and falls back to render resolution.
        resolution = (getattr(settings, "flow_upscale_resolution", "2k") or "none").strip().lower()
        upscale_base = None
        if resolution in ("2k", "4k") and variations:
            from app.services.flow_upscale import api_base_from_generation_url, media_id_candidates, upscale_to_bytes

            upscale_base = api_base_from_generation_url(url)
            ctx = json_payload.get("clientContext") or {}
            project_id = ctx.get("projectId") if isinstance(ctx, dict) else None

            async def _execute(up_url: str, payload: dict) -> Any:
                up_res = await client.post(up_url, headers=filtered_headers, json=payload, timeout=120.0)
                if up_res.status_code != 200:
                    raise RuntimeError(f"HTTP {up_res.status_code}: {up_res.text[:300] or '(no body)'}")
                return up_res.json()

            async def _upscale(media_id: str) -> bytes | None:
                if not upscale_base:
                    return None
                for candidate in media_id_candidates(media_id):
                    body = await upscale_to_bytes(
                        _execute, upscale_base, candidate,
                        resolution=resolution, project_id=project_id,
                        on_failure=lambda m: print(f"⚠️ [FLOW DIRECT] {m}"),
                    )
                    if body is not None:
                        return body
                return None
        else:
            _upscale = None  # type: ignore[assignment]

        if variations:
            for rec in variations[:count]:
                body = None
                if _upscale and rec.media_id:
                    body = await _upscale(rec.media_id)
                    if body:
                        logger.info("Variation upsampled to %s via Flow upsampler.", resolution.upper())
                if body is None:
                    body = rec.inline
                if body is None and rec.url:
                    try:
                        media_res = await client.get(rec.url, headers=filtered_headers)
                        if media_res.status_code == 200 and len(media_res.content) >= MIN_IMAGE_BYTES:
                            body = media_res.content
                    except httpx.HTTPError as e:
                        logger.warning("Could not download Flow media URL: %s", e)
                if body is not None:
                    image_bytes_list.append(body)
        else:
            image_bytes_list = list(harvest.inline)
            image_urls: list[str] = list(harvest.urls)
            for media_url in image_urls[: max(0, count - len(image_bytes_list))]:
                try:
                    media_res = await client.get(media_url, headers=filtered_headers)
                except httpx.HTTPError as e:
                    logger.warning("Could not download Flow media URL: %s", e)
                    continue
                if media_res.status_code == 200 and len(media_res.content) >= MIN_IMAGE_BYTES:
                    image_bytes_list.append(media_res.content)
                else:
                    logger.warning(
                        "Flow media URL returned HTTP %s (%d bytes) — not stored.",
                        media_res.status_code, len(media_res.content),
                    )

    if not image_bytes_list:
        # Report the shape, not the content: this response carries tokens.
        raise RuntimeError(
            "Google Flow answered HTTP 200 but no image data could be extracted"
            + (f" ({len(harvest.urls)} media URL(s) were found but none downloaded)"
               if harvest.urls else "")
            + f". Response shape: {describe_shape(res_json)}"
        )

    generated_paths: list[str] = []
    for idx, img_bytes in enumerate(image_bytes_list[:count], 1):
        out_file = output_dir / f"flow_api_{idx}.jpg"
        out_file.write_bytes(img_bytes)
        try:
            from app.services.anti_ai_processor import postprocess_image
            postprocess_image(out_file, skip_colab=True)
        except Exception as e:
            logger.warning("Anti-AI post-processing error on %s: %s", out_file, e)

        # Storage-relative, matching what the browser automator returns, so the
        # caller never has to guess which producer wrote a given row.
        generated_paths.append(f"data/outputs/{job_id}/{out_file.name}")

    if len(generated_paths) < count:
        # Reported, not raised: unlike the UI automator these images can only have
        # come from this call, so a short batch is still honest output.
        logger.warning(
            "Google Flow returned %d image(s) for job %s, %d were requested.",
            len(generated_paths), job_id, count,
        )
    logger.info("Generated %d image(s) via direct Google Flow API.", len(generated_paths))
    return generated_paths
