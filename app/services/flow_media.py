"""
Pinterest Realism Engine — what counts as "media Google Flow just generated".

Both Flow backends face the same question and used to answer it differently:

  * `flow_direct_api` replays the captured `batchGenerateImages` request and reads
    the images out of the JSON response — authoritative, because the response can
    only describe the request that produced it.
  * `flow_automator` drove the UI and then *diffed the DOM*: it recorded every
    `img[src*="getMediaUrlRedirect"]` before submitting and treated anything new
    afterwards as this job's output.

The DOM diff is what put a warehouse forklift safety poster, a text card, an
espresso machine and a skincare bottle into job `908692a5`'s gallery while the log
said "produced 4 verified image(s)". Flow's project canvas is a long, lazily
hydrated list of *every* past generation. The baseline snapshot therefore
undercounts: images that already existed mount a few seconds later, the total
crosses `baseline + 4`, and the "new" set is a handful of old test renders. The
code even had a guard for exactly this failure and the guard passed, because from
the DOM's point of view those images genuinely had just appeared.

So attribution moved to the network: whatever Flow's generation endpoint returns
in response to *our* submit is ours, and nothing else is. This module holds the
part both backends share — recognising that endpoint and harvesting media out of
its payload — so the two can never drift apart again.

Deliberately free of `httpx` and `playwright` imports: the automator must not pull
in the replay backend's HTTP client, and the verifier runs this logic with neither
installed.
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

logger = logging.getLogger("pre.flow_media")

SESSION_FILE = Path("./data/captured_flow_session.json")

#: A response URL is a *generation* call if its path carries one of these. Flow's
#: image endpoint is `.../flowMedia:batchGenerateImages`, but the family has been
#: renamed before (`runImageFx`, `generateImage`), so this matches the verb rather
#: than one exact path.
_GENERATION_URL_MARKERS = (
    "generate",      # batchGenerateImages, generateImage, :generate
    "imagefx",       # runImageFx and friends
    "texttoimage",
)

#: …and is *not* a generation call if its path carries one of these, however many
#: generation-ish words it also contains. This is the important half: a listing or
#: project-hydration response describes media that already existed, and treating
#: one as output is precisely the bug this module exists to prevent.
_LISTING_URL_MARKERS = (
    "list",          # listMedia, ListProjectMedia
    "history",
    "feed",
    "search",
    "batchget",
    "getproject",
    "fetchproject",
    "loadproject",
    "recent",
    "library",
)

#: Keys whose string value is base64 image bytes.
_INLINE_IMAGE_KEYS = ("encodedimage", "bytesbase64encoded", "data", "imagebytes", "image")

#: Keys whose string value is a URL the image can be downloaded from.
_MEDIA_URL_KEYS = ("imageuri", "url", "mediaurl", "fifeurl", "servingurl", "downloaduri")

#: Base64 prefixes for the formats Flow returns (JPEG, PNG, WebP).
_B64_IMAGE_PREFIXES = ("/9j/", "iVBORw0KGgo", "UklGR")

#: Below this, a "download" is an error page, a spinner GIF or a truncated body.
MIN_IMAGE_BYTES = 5_000


@dataclass
class MediaHarvest:
    """Media found in one Flow payload."""

    inline: list[bytes] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.inline) + len(self.urls)

    def __bool__(self) -> bool:
        return self.total > 0


@dataclass
class VariationRecord:
    """
    One generated image exactly as Flow's response described it.

    `media_id` is the `mediaGenerationId` — the handle Flow's server-side
    2K/4K upsampler (`/v1/flow/upsampleImage`) takes, so a variation can be
    re-fetched at print resolution instead of the render-resolution bytes the
    generation response itself carries. Records keep response order: record *n*
    is variation *n*.
    """

    media_id: str | None = None
    inline: bytes | None = None
    url: str | None = None


def endpoint_path(url: str) -> str:
    """
    `host/path` for a URL, with the query string dropped.

    Used for logging. Flow's media URLs carry signed query parameters, and the
    generation endpoint is reached with an `authorization` header — neither belongs
    in a log line, and the path alone is what identifies the endpoint.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<unparseable url>"
    return f"{parts.netloc}{parts.path}" or url[:80]


def looks_like_generation_url(url: str) -> bool:
    """
    Whether `url` is Flow asking for *new* images rather than describing old ones.

    The listing check runs second and wins on purpose: `ListGeneratedMedia` would
    otherwise match on "generate" and hand the automator the whole project canvas,
    which is the original bug wearing a different hat.
    """
    if not url:
        return False
    path = urlsplit(url).path.lower() if "://" in url else url.split("?")[0].lower()
    if any(marker in path for marker in _LISTING_URL_MARKERS):
        return False
    return any(marker in path for marker in _GENERATION_URL_MARKERS)


def captured_generation_path() -> str | None:
    """
    The generation endpoint path recorded in `data/captured_flow_session.json`, if
    a capture exists.

    Reads exactly one field, `url`, and returns only its path. The rest of that
    file is an OAuth token and a reCAPTCHA token and is never touched. This gives
    the automator the operator's *real* endpoint as a cross-check, so a future
    Google rename is caught by evidence instead of by my marker list.
    """
    try:
        data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    url = data.get("url")
    if not isinstance(url, str) or not url:
        return None
    try:
        path = urlsplit(url).path
    except ValueError:
        return None
    return path or None


def _decode_inline(value: str) -> bytes | None:
    """Decode a base64 image string, or None if it is not one."""
    payload = value.split(";base64,")[-1]
    if not (value.startswith("data:") or any(payload.startswith(p) for p in _B64_IMAGE_PREFIXES)):
        return None
    try:
        decoded = base64.b64decode(payload, validate=False)
    except (ValueError, TypeError):
        return None
    return decoded if len(decoded) >= MIN_IMAGE_BYTES else None


def harvest_media(data: Any, into: MediaHarvest | None = None) -> MediaHarvest:
    """
    Collect inline image bytes and image URLs from a Flow JSON payload.

    Flow answers `batchGenerateImages` with a `media` list whose entries carry the
    bytes inline *or* only a `getMediaUrlRedirect` link. The URL case used to fall
    through to "No image data found", which reads like a generation failure when it
    is really a second fetch nobody made — so URLs are collected here and the
    caller downloads them with credentials still in scope.

    Order is preserved: entry *n* of the response stays variation *n*.
    """
    harvest = into if into is not None else MediaHarvest()

    if isinstance(data, dict):
        for key, value in data.items():
            key_lower = str(key).lower()
            if isinstance(value, str):
                if key_lower in _INLINE_IMAGE_KEYS or len(value) > 2000:
                    decoded = _decode_inline(value)
                    if decoded is not None:
                        harvest.inline.append(decoded)
                        continue
                if value.startswith("http") and (
                    "getMediaUrlRedirect" in value or key_lower in _MEDIA_URL_KEYS
                ):
                    if value not in harvest.urls:
                        harvest.urls.append(value)
            elif isinstance(value, (dict, list)):
                harvest_media(value, harvest)
    elif isinstance(data, list):
        for item in data:
            harvest_media(item, harvest)

    return harvest


def _unwrap_media_id(value: Any) -> str | None:
    """
    Normalise the three shapes Flow has used for a media id.

    Seen in the wild: a plain string under `mediaGenerationId`, a wrapper dict
    `{"mediaGenerationId": "..."}` (the uploadImage response), and the
    `generatedImage` dict itself carrying the string field.
    """
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        inner = value.get("mediaGenerationId")
        if isinstance(inner, str) and inner:
            return inner
    return None


def _find_media_id(node: Any, depth: int = 0) -> str | None:
    """
    First `mediaGenerationId` anywhere in ONE media entry's subtree.

    Live responses have placed the id inside `generatedImage`, beside `image`
    on the media entry, and (17:05 job 7a2fd355) somewhere the two explicit
    checks above never reached — so instead of naming levels, search the
    whole entry. Safe against id-swapping because `visit` calls this per
    entry and never descends into a harvested entry's children.
    """
    if depth > 6:
        return None
    if isinstance(node, dict):
        found = _unwrap_media_id(node.get("mediaGenerationId"))
        if found:
            return found
        for value in node.values():
            if isinstance(value, (dict, list)):
                found = _find_media_id(value, depth + 1)
                if found:
                    return found
        return None
    if isinstance(node, list):
        for item in node:
            found = _find_media_id(item, depth + 1)
            if found:
                return found
    return None


def _entry_name(node: dict, gen: dict) -> str | None:
    """
    The media entry's resource `name` — the id form newer responses use.

    Job 82956521's key outline proved Flow renamed the field: media entries
    carry `{name, workflowId, image: {generatedImage, dimensions}}` and no
    `mediaGenerationId` anywhere. `name` is an AIP resource name (often
    `projects/…/flowMedia/<id>`); the upsample caller derives the bare id
    segment itself (`flow_upscale.media_id_candidates`).
    """
    for cand in (node.get("name"), gen.get("name")):
        if isinstance(cand, str) and cand.strip():
            return cand.strip()
    return None


def harvest_variations(data: Any) -> list[VariationRecord]:
    """
    Walk a `batchGenerateImages` response for per-variation records.

    Flow answers with a `media` list whose entries wrap `image.generatedImage`:
    that dict carries the `mediaGenerationId` plus either inline bytes or a
    fife/redirect URL. The flat `harvest_media` cannot pair an id with its
    bytes — it concatenates everything it finds — so this structured pass
    exists for the upsample call, which needs one id per variation.
    """
    records: list[VariationRecord] = []
    seen_ids: set[str] = set()

    def _generated_image_dict(node: dict) -> dict | None:
        image = node.get("image")
        if isinstance(image, dict) and isinstance(image.get("generatedImage"), dict):
            return image["generatedImage"]
        if _unwrap_media_id(node.get("mediaGenerationId")):
            return node
        return None

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            gen = _generated_image_dict(node)
            if gen is not None:
                # The image's own id (inside gen) is the right one; the
                # subtree search covers every other level the id has been
                # seen at (media entry, image dict) without swapping ids
                # between variations, because each entry is searched alone.
                # Final fallback: the entry's resource `name`, which is the
                # ONLY id newer responses send (job 82956521's key outline).
                media_id = (
                    _unwrap_media_id(gen.get("mediaGenerationId"))
                    or _find_media_id(node)
                    or _entry_name(node, gen)
                )
                if media_id and media_id in seen_ids:
                    return
                if media_id:
                    seen_ids.add(media_id)
                harvest = harvest_media(gen)
                records.append(
                    VariationRecord(
                        media_id=media_id,
                        inline=harvest.inline[0] if harvest.inline else None,
                        url=harvest.urls[0] if harvest.urls else None,
                    )
                )
                return  # already harvested this subtree; do not double-count
            for value in node.values():
                if isinstance(value, (dict, list)):
                    visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(data)
    return records


def describe_shape(data: Any, depth: int = 0) -> str:
    """
    A key-only outline of a payload, for error messages.

    Values are never included: these payloads hold tokens. Knowing the response was
    `{operation: {name: str, done: bool}}` instead of `{media: [...]}` is what makes
    a failure diagnosable, and no value is needed to see that.
    """
    if depth > 3:
        return "…"
    if isinstance(data, dict):
        inner = ", ".join(
            f"{k}: {describe_shape(v, depth + 1)}" for k, v in list(data.items())[:12]
        )
        suffix = ", …" if len(data) > 12 else ""
        return "{" + inner + suffix + "}"
    if isinstance(data, list):
        return f"[{len(data)} × {describe_shape(data[0], depth + 1)}]" if data else "[]"
    return type(data).__name__
