"""
Pinterest Realism Engine — pollinations.ai image generation (secondary backend).

NOTE: this is the lightweight API backend, not the primary one. It condenses the
compiled 13-section prompt down to a URL-safe string, so it necessarily loses
detail that Google Flow receives in full. Use it for quick tests; use the Flow
path (flow_direct_api / flow_automator) for real output.

It raises ImageGenerationError when generation fails. It must never write a
placeholder file: a job whose "output" is a copied reference photo looks
successful to every downstream stage.
"""

from __future__ import annotations

import asyncio
import logging
import urllib.parse
from pathlib import Path
from uuid import uuid4

import httpx

from app.config import settings

logger = logging.getLogger("pre.image_gen")

# pollinations encodes the prompt in the URL path, so it cannot take the full
# compiled prompt. Keep the sections that constrain the product and the scene.
PROMPT_CHAR_BUDGET = 1200


class ImageGenerationError(RuntimeError):
    """Image generation failed and produced no usable file."""


def _condense_prompt(prompt: str) -> str:
    """
    Reduce the compiled prompt to fit a URL while preserving the sections that
    matter most. PRODUCT TRUTH is kept first — dropping it is what allowed the
    model to invent product features.
    """
    blocks: dict[str, str] = {}
    current = "PREAMBLE"
    for raw_line in prompt.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if line.endswith(":") and line.isupper():
            current = line.rstrip(":")
            blocks[current] = ""
            continue
        blocks[current] = (blocks.get(current, "") + " " + line).strip()

    # Priority order: what the product is, what must stay true, then style.
    priority = [
        "PRODUCT TRUTH", "SUBJECT", "PHOTOGRAPHIC INTENT", "SCENE",
        "HUMAN INTERACTION", "CAMERA", "LIGHTING", "COMPOSITION",
        "MATERIALS", "ENVIRONMENT", "REALISM", "PREAMBLE",
    ]
    ordered = [blocks[k] for k in priority if blocks.get(k)]
    ordered += [v for k, v in blocks.items() if k not in priority and k != "AVOID" and v]

    out = ""
    for part in ordered:
        if len(out) + len(part) + 1 > PROMPT_CHAR_BUDGET:
            break
        out = f"{out} {part}".strip()
    return out or prompt[:PROMPT_CHAR_BUDGET]


async def generate_image_automated(
    prompt: str,
    job_id: str,
    width: int = 768,
    height: int = 1344,  # Standard Pinterest 9:16 aspect ratio
    seed: int | None = None,
) -> Path:
    """
    Generate an image via pollinations.ai.

    Saves the image to data/outputs/{job_id}/ and returns the file path.

    Raises:
        ImageGenerationError: if every endpoint and retry failed.
    """
    output_dir = settings.outputs_path / job_id
    output_dir.mkdir(parents=True, exist_ok=True)

    img_id = str(uuid4())[:8]
    output_file = output_dir / f"gen_{img_id}.jpg"

    encoded_prompt = urllib.parse.quote(_condense_prompt(prompt))
    seed_val = seed or int(uuid4().int % 900000)

    urls = [
        f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={width}&height={height}&model=flux-realism&nologo=true&seed={seed_val}",
        f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={width}&height={height}&model=flux&nologo=true&seed={seed_val}",
        f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={width}&height={height}&model=turbo&nologo=true&seed={seed_val}",
    ]

    logger.info("Triggering image generation for job %s (seed: %d)...", job_id, seed_val)

    failures: list[str] = []
    for url in urls:
        model = url.split("model=")[-1].split("&")[0]
        for attempt in range(1, 3):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(url)
                if resp.status_code == 200 and len(resp.content) > 3000:
                    output_file.write_bytes(resp.content)
                    logger.info("Image generation complete: %s (%d bytes)", output_file, len(resp.content))
                    return output_file
                if resp.status_code == 429:
                    failures.append(f"{model}: rate limited (429)")
                    await asyncio.sleep(attempt * 1.5)
                else:
                    failures.append(f"{model}: HTTP {resp.status_code}, {len(resp.content)} bytes")
            except Exception as e:
                failures.append(f"{model}: {e}")
                logger.warning("Generation attempt %d on model %s failed: %s", attempt, model, e)
                await asyncio.sleep(attempt * 0.5)

    # No placeholder file. Previously this copied references/maid_costume_ref.jpg
    # (or wrote zero bytes) and returned success, so failed generations became
    # jobs holding a Halloween costume photo as their "output".
    raise ImageGenerationError(
        f"All pollinations endpoints failed for job {job_id}. Attempts: " + " | ".join(failures)
    )
