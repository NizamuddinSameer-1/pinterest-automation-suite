"""
Pinterest Realism Engine — the single image-generation entry point.

Before this module there were three generation paths, each with its own idea of
what a result looked like:

  * `flow_direct_api.generate_images_via_direct_flow_api` — replays the captured
    Google Flow request over HTTP. Fast and browser-free, but the capture's
    reCAPTCHA and OAuth tokens age out within minutes, so it is a speed-up rather
    than a dependable path. Was never called from `app/api/` at all.
  * `flow_automator.generate_flow_batch` — drives the Flow UI with Playwright.
    Slow and brittle, but works from a logged-in profile with no capture step.
  * `image_gen.generate_image_automated` — pollinations.ai. Takes a *condensed*
    prompt, so it cannot honour the full 13-section brief. Test backend only.

They returned different path shapes (absolute vs `data/`-relative), different
counts, and nobody recorded which one produced a given image — so an output in
the database could not be traced back to the system that made it.

Everything now goes through `generate_variations`, which:

  1. picks a backend (`auto` = browser automation first, captured replay second),
  2. never silently substitutes a different backend when one was named explicitly,
  3. verifies every returned file exists on disk and is big enough to be an image,
  4. normalises paths to `data/outputs/<job_id>/<name>`,
  5. reports `produced_by` and the full `attempts` trail.

`GenerationFailed` carries the attempt trail, so a failure says which backends
were tried and why each one declined — the point being that no caller can mistake
"nothing was generated" for success.
"""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath

from app.config import settings

logger = logging.getLogger("pre.generation")

# Task 9 — Visual Commerce Engine wiring: Commerce DNA + concepts are generated
# in app/api/generation.py::_prepare_brief (after reference_analysis) and stored
# on Job.commerce_dna_json / Job.concepts_json before scene_director. This module
# remains backend-agnostic; see app/pipeline/commerce_strategist.py.

# Backend identifiers. These are part of the HTTP surface (`?backend=`), so keep
# them stable.
FLOW_API = "flow_api"
FLOW_UI = "flow_ui"
POLLINATIONS = "pollinations"
AUTO = "auto"

#: Order tried when the caller asks for `auto`. Browser automation comes first:
#: it signs in from the persistent `data/flow_profile`, so it works today and
#: tomorrow. The direct replay is second because the capture it depends on is a
#: one-shot artefact — it carries a reCAPTCHA Enterprise token (short-lived,
#: effectively single-use) and an OAuth access token (~1 hour), neither of which
#: can be refreshed without a browser. It was primary until a run showed both
#: backends failing; as an opportunistic speed-up in the minutes after a capture
#: it is useful, as the default it just delays the path that actually works.
#: `pollinations` is deliberately absent — it only ever receives a condensed
#: prompt, so falling back to it silently would quietly downgrade the brief.
AUTO_ORDER: tuple[str, ...] = (FLOW_UI, FLOW_API)

#: A JPEG/PNG that Flow or pollinations actually rendered is tens of KB. Anything
#: this small is an error page, a truncated download or a zero-byte placeholder.
MIN_IMAGE_BYTES = 5_000

FLOW_SESSION_FILE = Path("./data/captured_flow_session.json")
FLOW_PROFILE_DIR = Path("./data/flow_profile")


class GenerationUnavailable(RuntimeError):
    """A backend cannot run at all (no session, no browser, not installed)."""


class GenerationFailed(RuntimeError):
    """No backend produced verifiable images."""

    def __init__(self, message: str, attempts: list[str] | None = None) -> None:
        self.attempts = attempts or []
        if self.attempts:
            message = f"{message} Attempts: " + " | ".join(self.attempts)
        super().__init__(message)


@dataclass
class GenerationResult:
    """What a generation run actually produced."""

    image_paths: list[str]
    produced_by: str
    requested_count: int
    attempts: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.image_paths)

    @property
    def is_partial(self) -> bool:
        return self.count < self.requested_count


def store_relative(path: str | Path) -> str:
    """
    Convert any producer's path into the storage-relative POSIX form the database
    holds (`data/outputs/<job_id>/<name>`).

    The two Flow backends disagreed here: the automator returned
    `data/outputs/<job>/flow_var_1.jpg` while the direct API returned an absolute
    path. Consumers then guessed, and `run_flow_bg` guessed *wrong* — it rewrote
    any non-`data/` path to `flow_var_<idx>.jpg`, a filename the direct API never
    writes, so the database pointed at files that did not exist.
    """
    raw = str(path).strip()
    posix = PureWindowsPath(raw).as_posix() if "\\" in raw else raw
    if posix.startswith("data/"):
        return posix

    p = Path(posix)
    storage = Path(settings.storage_path).resolve()
    if p.is_absolute():
        try:
            return "data/" + p.resolve().relative_to(storage).as_posix()
        except (ValueError, OSError):
            # Outside the storage root: keep the absolute path rather than
            # inventing a relative one that resolves somewhere else.
            return p.as_posix()
    return posix


def _verify_produced(paths: list[str], backend: str) -> tuple[list[str], list[str]]:
    """
    Keep only paths that exist on disk and are plausibly images.

    A backend claiming success while its file is missing or 0 bytes is the exact
    failure mode this project spent two phases removing, so the claim is checked
    here rather than trusted.
    """
    kept: list[str] = []
    rejected: list[str] = []
    for raw in paths:
        rel = store_relative(raw)
        candidate = Path(rel)
        if not candidate.is_absolute():
            candidate = Path(".").resolve() / rel
        try:
            if not candidate.is_file():
                rejected.append(f"{rel} (missing on disk)")
                continue
            size = candidate.stat().st_size
        except OSError as e:
            rejected.append(f"{rel} ({e})")
            continue
        if size < MIN_IMAGE_BYTES:
            rejected.append(f"{rel} ({size} bytes, below {MIN_IMAGE_BYTES})")
            continue
        kept.append(rel)
    if rejected:
        logger.warning("%s: discarded %d unusable output(s): %s",
                       backend, len(rejected), "; ".join(rejected))
    return kept, rejected


def _playwright_installed() -> bool:
    return importlib.util.find_spec("playwright") is not None


def _httpx_installed() -> bool:
    """
    `flow_direct_api` imports httpx at module level, so a missing httpx makes the
    replay backend unimportable. Checked the same way playwright is, so listing
    backends never depends on an optional dependency being present.
    """
    return importlib.util.find_spec("httpx") is not None


# ── backends ────────────────────────────────────────────────────────────


async def _run_flow_api(prompt: str, job_id: str, count: int) -> list[str]:
    if not FLOW_SESSION_FILE.exists():
        raise GenerationUnavailable(
            "no captured Google Flow session (data/captured_flow_session.json). "
            "Run the 1-Time Session Capture to enable the direct API path."
        )
    if not _httpx_installed():
        raise GenerationUnavailable(
            "httpx is not installed, so the captured request cannot be replayed "
            "(pip install -r requirements.txt)"
        )
    from app.services.flow_direct_api import FlowSessionError, generate_images_via_direct_flow_api

    try:
        return await generate_images_via_direct_flow_api(prompt=prompt, job_id=job_id, count=count)
    except FlowSessionError as e:
        # An expired or malformed capture is an availability problem, not a
        # generation bug: under `auto` it should hand over to the browser path,
        # which authenticates from the profile instead of the captured token.
        raise GenerationUnavailable(str(e)) from e


async def _run_flow_ui(prompt: str, job_id: str, count: int, reference_image: str | Path | None = None) -> list[str]:
    if not _playwright_installed():
        raise GenerationUnavailable(
            "playwright is not installed in this environment "
            "(pip install -r requirements.txt && python -m playwright install chromium)"
        )
    if not FLOW_PROFILE_DIR.exists():
        raise GenerationUnavailable(
            "no logged-in Google Flow browser profile (data/flow_profile). "
            "Run the one-time Flow login first."
        )
    # Imported lazily: flow_automator imports playwright at module level, and the
    # API must still boot (and the direct-API path still work) without it.
    from app.services.flow_automator import generate_flow_batch

    return await generate_flow_batch(
        prompt=prompt,
        job_id=job_id,
        count=count,
        reference_image=reference_image,
    )


async def _run_pollinations(
    prompt: str,
    job_id: str,
    count: int,
    prompts: list[str] | None = None,
) -> list[str]:
    from app.services.image_gen import generate_image_automated

    prompt_list = prompts if prompts else [prompt] * max(1, count)
    if count > 1:
        logger.info(
            "pollinations backend: generating %d images across %d concept prompt(s)",
            count, len(prompt_list),
        )
    paths: list[str] = []
    errors: list[str] = []
    for i in range(max(1, count)):
        p = prompt_list[i % len(prompt_list)]
        try:
            paths.append(str(await generate_image_automated(prompt=p, job_id=job_id)))
        except Exception as e:  # noqa: BLE001 — recorded, then re-raised if nothing worked
            errors.append(str(e))
    if not paths:
        raise GenerationFailed("pollinations produced no images.", errors)
    return paths


_RUNNERS = {
    FLOW_API: _run_flow_api,
    FLOW_UI: _run_flow_ui,
    POLLINATIONS: _run_pollinations,
}

_LABELS = {
    FLOW_API: "Google Flow — captured-request replay (expires ~15 min after capture)",
    FLOW_UI: "Google Flow — browser automation (primary)",
    POLLINATIONS: "pollinations.ai (condensed prompt, test only)",
}


def describe_backends() -> list[dict[str, object]]:
    """
    Report what can actually run right now, for the UI to show before the
    operator clicks Generate.

    Listed in `AUTO_ORDER` first so the panel reads in the order they are tried,
    and `primary` marks the head of that order rather than being hardcoded — the
    two disagreed once already, which told the operator the replay was primary
    after it had been demoted.
    """
    session_ready = FLOW_SESSION_FILE.exists()
    profile_ready = FLOW_PROFILE_DIR.exists()
    pw = _playwright_installed()

    # A capture that exists but has aged out cannot generate, so it is reported
    # as unavailable: showing it as available is what let a run spend its first
    # attempt on a request that could only be rejected.
    capture_detail = "Needs a 1-Time Session Capture."
    capture_usable = False
    if not session_ready:
        pass
    elif not _httpx_installed():
        capture_detail = "httpx is not installed, so the capture cannot be replayed."
    else:
        # Imported here, not at module scope: flow_direct_api pulls in httpx, and
        # listing backends must not fail because an optional dependency is absent.
        from app.services.flow_direct_api import CAPTURE_MAX_AGE_SECONDS, capture_age_seconds

        age = capture_age_seconds()
        if age is None:
            capture_detail = "Captured session present (age unknown)."
            capture_usable = True
        elif age > CAPTURE_MAX_AGE_SECONDS:
            capture_detail = (
                f"Capture is {age / 60:.0f} min old (usable for "
                f"{CAPTURE_MAX_AGE_SECONDS // 60} min) — its reCAPTCHA and OAuth tokens "
                "have expired. Re-capture, or use browser automation."
            )
        else:
            capture_detail = f"Captured {age / 60:.0f} min ago — still replayable."
            capture_usable = True

    backends = {
        FLOW_UI: {
            "id": FLOW_UI,
            "label": _LABELS[FLOW_UI],
            "available": pw and profile_ready,
            "detail": (
                "Logged-in Flow profile present; does not expire."
                if pw and profile_ready
                else ("playwright is not installed." if not pw else "No data/flow_profile yet — log into Flow once.")
            ),
        },
        FLOW_API: {
            "id": FLOW_API,
            "label": _LABELS[FLOW_API],
            "available": capture_usable,
            "detail": capture_detail,
        },
        POLLINATIONS: {
            "id": POLLINATIONS,
            "label": _LABELS[POLLINATIONS],
            "available": True,
            "detail": "Only used when named explicitly; receives a condensed prompt.",
        },
    }

    ordered = [backends[name] for name in AUTO_ORDER]
    ordered += [b for name, b in backends.items() if name not in AUTO_ORDER]
    for index, entry in enumerate(ordered):
        entry["primary"] = index == 0 and entry["id"] in AUTO_ORDER
    return ordered


async def generate_variations(
    prompt: str,
    job_id: str,
    count: int = 4,
    backend: str = AUTO,
    reference_image: str | Path | None = None,
    prompts: list[str] | None = None,
) -> GenerationResult:
    """
    Generate `count` variations for `job_id` and return verified image paths.

    Args:
        prompt: the compiled prompt. Must be non-empty — generating from a blank
            prompt produces a random image that looks like a successful run.
        backend: `auto`, or one of `flow_api` / `flow_ui` / `pollinations`.
            A named backend is never substituted: if it fails, the call fails.
        reference_image: optional path to style reference image to paste into Flow.
        prompts: optional list of concept prompts for multi-concept diversity.

    Raises:
        GenerationFailed: nothing verifiable was produced.
    """
    if not prompt or not prompt.strip():
        raise GenerationFailed("refusing to generate from an empty prompt.")
    if count < 1:
        raise GenerationFailed(f"invalid variation count {count}.")

    if backend == AUTO:
        order = list(AUTO_ORDER)
    elif backend in _RUNNERS:
        order = [backend]
    else:
        raise GenerationFailed(
            f"unknown generation backend {backend!r}; expected one of "
            f"{AUTO}, {', '.join(_RUNNERS)}."
        )

    settings.outputs_path.mkdir(parents=True, exist_ok=True)
    attempts: list[str] = []

    for name in order:
        logger.info("Job %s: trying generation backend %s", job_id, name)
        try:
            primary_prompt = prompts[0] if prompts else prompt
            if name == FLOW_UI:
                produced = await _run_flow_ui(primary_prompt, job_id, count, reference_image=reference_image)
            elif name == POLLINATIONS:
                produced = await _run_pollinations(prompt, job_id, count, prompts=prompts)
            else:
                produced = await _RUNNERS[name](primary_prompt, job_id, count)
        except GenerationUnavailable as e:
            attempts.append(f"{name}: unavailable — {e}")
            logger.info("Job %s: backend %s unavailable — %s", job_id, name, e)
            continue
        except Exception as e:  # noqa: BLE001 — recorded in the attempt trail
            attempts.append(f"{name}: failed — {e}")
            logger.warning("Job %s: backend %s failed — %s", job_id, name, e)
            if backend != AUTO:
                # Explicitly requested: do not quietly hand the work to another
                # backend the operator did not ask for.
                raise GenerationFailed(
                    f"Requested backend {name!r} failed and no substitute was used.", attempts
                ) from e
            continue

        kept, rejected = _verify_produced(list(produced or []), name)
        if not kept:
            attempts.append(
                f"{name}: returned {len(produced or [])} path(s), none usable"
                + (f" ({'; '.join(rejected)})" if rejected else "")
            )
            continue

        if rejected:
            attempts.append(f"{name}: dropped {len(rejected)} unusable path(s): {'; '.join(rejected)}")
        result = GenerationResult(
            image_paths=kept,
            produced_by=name,
            requested_count=count,
            attempts=attempts,
        )
        if result.is_partial:
            logger.warning(
                "Job %s: %s produced %d of %d requested variations", job_id, name, result.count, count
            )
        else:
            logger.info("Job %s: %s produced %d variations", job_id, name, result.count)
        return result

    raise GenerationFailed(f"No generation backend produced images for job {job_id}.", attempts)
