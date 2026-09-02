"""
Record generated images as job outputs and pin drafts — in one place.

This logic used to exist three times: in `/generate-auto`, in `/upload-batch`
and in `scripts/run_flow_bg.py`. The copies drifted, and the drift was not
cosmetic:

  * `run_flow_bg` rewrote any path that did not start with `data/` to
    `flow_var_<idx>.jpg`, a filename only the browser automator produces — so
    direct-API output was recorded under a name that did not exist on disk;
  * two copies appended "(Look #N)" to the title, one did not;
  * the target board fell back to a board name hardcoded in three files;
  * `/upload-batch` set the job state directly instead of validating the
    transition.

`record_generation_outputs` is now the only writer. It does not commit at the end:
the API routes commit through their session dependency, and the background runner
commits its own session, so ownership of the final transaction stays with the
caller. It does commit once midway — after the outputs are recorded, before the
Pinterest SEO LLM call — because holding SQLite's write lock across that call
starved every other endpoint (`database is locked`, AUTO-BUG-20260824_172835).
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.models import Job, JobOutput, PinDraft, Product, PromptVersion, Reference
from app.services.generation import store_relative
from app.services.job_service import InvalidTransitionError, validate_transition

logger = logging.getLogger("pre.output_service")


class PinCopyUnavailable(RuntimeError):
    """
    Images were recorded, but Pinterest copy could not be generated.

    The images are real and already on disk, so they are kept and the job is left
    at OUTPUT_UPLOADED. Callers report this as a retryable error rather than
    inventing a caption.
    """

    def __init__(self, reason: str, output_ids: list[str]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.output_ids = output_ids


class PinDestinationUnavailable(RuntimeError):
    """
    Images were recorded, but no earning destination URL exists for them.

    A pin draft with an empty `destination_url` cannot earn, and one pointing at
    a lookbook that was never deployed 404s on click. Both are placeholders, so
    neither is written: the job stays at OUTPUT_UPLOADED and the operator is told
    to fix the product's affiliate link. Same contract as PinCopyUnavailable —
    keep the images, refuse to invent the URL.
    """

    def __init__(self, reason: str, output_ids: list[str]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.output_ids = output_ids


def _product_to_dict(product: Product) -> dict[str, Any]:
    """Plain dict for the pipeline stages (mirrors app.api.jobs._product_to_dict)."""
    return {
        "name": product.name,
        "brand": product.brand,
        "merchant": product.merchant,
        "category": product.category,
        "price": product.price,
        "currency": product.currency,
        "affiliate_url": product.affiliate_url or "",
        "seasons": json.loads(product.seasons) if product.seasons else [],
        "colors": json.loads(product.colors) if product.colors else [],
        "materials": json.loads(product.materials) if product.materials else [],
        "key_attributes": json.loads(product.key_attributes) if product.key_attributes else [],
    }


async def _record_outputs(
    db: AsyncSession,
    job: Job,
    image_paths: list[str],
    prompt_version_id: str | None,
) -> list[JobOutput]:
    # 1. Automatic Google Colab AI upscaling via Playwright if notebook is configured
    colab_notebook_url = getattr(settings, "colab_notebook_url", "").strip()
    if colab_notebook_url:
        try:
            from app.services.colab_automator import upscale_images_via_colab
            await upscale_images_via_colab(image_paths, colab_notebook_url)
        except Exception as e:
            logger.warning("Job %s: Colab AI upscaling note: %s. Continuing with local studio processing.", job.id, e)

    # 2. Guarantee all images are watermark-free, 1080p, and 98% 4:4:4 studio quality
    try:
        from app.services.anti_ai_processor import postprocess_batch
        postprocess_batch(image_paths)
    except Exception as e:
        logger.warning("Job %s: studio postprocessing note: %s", job.id, e)

    outputs: list[JobOutput] = []
    for path in image_paths:
        rec = JobOutput(
            id=str(uuid4())[:8],
            job_id=job.id,
            prompt_version_id=prompt_version_id,
            # Stored exactly as produced (normalised, never re-derived from an
            # index): the file on disk is the source of truth.
            image_path=store_relative(path),
        )
        db.add(rec)
        outputs.append(rec)
    await db.flush()
    return outputs


def _advance_to_output_uploaded(job: Job) -> None:
    """
    Walk the state machine to OUTPUT_UPLOADED.

    Not PASS: PASS is the realism critic's verdict, and writing it here is why 11
    jobs sat in PASS with zero critique rows.
    """
    if job.current_state == "OUTPUT_UPLOADED":
        return
    try:
        validate_transition(job.current_state, "OUTPUT_UPLOADED")
    except InvalidTransitionError:
        raise
    job.current_state = "OUTPUT_UPLOADED"


async def record_generation_outputs(
    db: AsyncSession,
    job: Job,
    product: Product,
    ref: Reference,
    image_paths: list[str],
    prompt_version: PromptVersion | None,
    produced_by: str,
) -> dict[str, Any]:
    """
    Record `image_paths` as this job's outputs, then create one pin draft each.

    Returns a summary dict. Raises:
        InvalidTransitionError: the job's state cannot accept new outputs.
        PinCopyUnavailable: outputs are recorded, SEO generation failed.
        PinDestinationUnavailable: outputs are recorded, but no earning destination
            URL exists — no affiliate link on the product and no deployed lookbook.
    """
    if not image_paths:
        raise ValueError("record_generation_outputs called with no image paths")

    outputs = await _record_outputs(db, job, image_paths, prompt_version.id if prompt_version else None)
    _advance_to_output_uploaded(job)
    # `provider` is the job's record of what actually made these images
    # ("flow_api", "flow_ui", "pollinations", or "manual_upload").
    job.provider = produced_by
    await db.flush()
    # Commit before the SEO call. The flushes above hold SQLite's single write
    # lock, and generate_pin_seo is an LLM round-trip that can take a minute —
    # holding the lock across it blocked every other writer (reference uploads,
    # pin updates) with `database is locked`. AUTO-BUG-20260824_172835.
    # expire_on_commit=False keeps every object below usable.
    await db.commit()

    product_data = _product_to_dict(product)
    scene_data = json.loads(job.scene_json) if job.scene_json else {}

    from app.pipeline.pinterest_seo import generate_pin_seo

    try:
        seo_data = await generate_pin_seo(
            product=product_data,
            scene=scene_data,
            trend_label=ref.trend_label,
        )
    except Exception as e:  # noqa: BLE001 — surfaced to the caller, never papered over
        logger.error("SEO generation failed for job %s: %s", job.id, e)
        raise PinCopyUnavailable(str(e), [o.id for o in outputs]) from e

    board = seo_data.get("board_suggestion") or settings.default_board_name
    base_title = seo_data["title"]

    # ── Generate UGC Lookbook Bridge Page ─────────
    # The direct affiliate link is the floor: if the lookbook cannot be deployed
    # the pin still earns through it. An empty bridge_url means the product came
    # in without an affiliate link, and the pin would ship with nothing to click.
    bridge_url: str = product.affiliate_url or ""
    try:
        from app.services.article_generator import generate_lookbook_html
        from app.services.vercel_publisher import deploy_article_to_vercel

        slug, html_content, og_image_bytes = await generate_lookbook_html(
            job_id=job.id,
            product_data=product_data,
            scene_data=scene_data,
            image_paths=image_paths,
            affiliate_url=product.affiliate_url,
        )
        deployed_url = await deploy_article_to_vercel(
            slug=slug,
            html_content=html_content,
            job_id=job.id,
            og_image_bytes=og_image_bytes,
        )
        if deployed_url:
            bridge_url = deployed_url
            logger.info("Job %s: bridge lookbook ready at %s", job.id, bridge_url)
    except Exception as e:
        if not bridge_url:
            # Nothing to fall back to — an empty destination_url is a placeholder,
            # not a result. Refuse to write pin drafts that cannot earn.
            raise PinDestinationUnavailable(
                f"lookbook deploy failed ({e}) and product {product.id} has no "
                "affiliate_url to fall back on",
                [o.id for o in outputs],
            ) from e
        logger.warning(
            "Job %s: bridge lookbook unavailable (%s); falling back to the direct "
            "affiliate link", job.id, e,
        )

    if not bridge_url:
        raise PinDestinationUnavailable(
            f"product {product.id} has no affiliate_url and no lookbook was deployed, "
            "so the pin drafts would have an empty destination_url",
            [o.id for o in outputs],
        )

    variations: list[dict[str, Any]] = []
    pins: list[PinDraft] = []
    for idx, out in enumerate(outputs, 1):
        pin = PinDraft(
            output_id=out.id,
            job_id=job.id,
            title=base_title if idx == 1 else f"{base_title} (Look #{idx})",
            description=seo_data["description"],
            keywords=json.dumps(seo_data.get("keywords", [])),
            destination_url=bridge_url,
            board_name=board,
            status="draft",
        )
        db.add(pin)
        pins.append(pin)
    await db.flush()

    for out, pin in zip(outputs, pins):
        variations.append({
            "output_id": out.id,
            "image_path": out.image_path,
            "pin_id": pin.id,
            "title": pin.title,
        })

    _sync_vault(job, product, pins, seo_data, scene_data, prompt_version)

    logger.info(
        "Job %s: recorded %d output(s) from %s with pin drafts on board %r",
        job.id, len(outputs), produced_by, board,
    )
    return {
        "job_id": job.id,
        "state": job.current_state,
        "produced_by": produced_by,
        "count": len(variations),
        "variations": variations,
        "board_name": board,
        "title": base_title,
        "description": seo_data["description"],
    }


def _sync_vault(
    job: Job,
    product: Product,
    pins: list[PinDraft],
    seo_data: dict[str, Any],
    scene_data: dict[str, Any],
    prompt_version: PromptVersion | None,
) -> None:
    """Mirror the run into the Obsidian vault. Never fatal — the DB is the record."""
    try:
        from app.services.vault_sync import sync_job_node, sync_pin_node

        sync_job_node(
            job_id=job.id,
            reference_id=job.reference_id,
            product_name=product.name,
            current_state=job.current_state,
            scene=scene_data,
            prompt_text=prompt_version.prompt_text if prompt_version else "",
            prompt_version=prompt_version.version if prompt_version else 0,
        )
        for pin in pins:
            sync_pin_node(
                pin_id=pin.id,
                job_id=job.id,
                title=pin.title,
                description=pin.description,
                keywords=seo_data.get("keywords", []),
                destination_url=pin.destination_url,
                board_name=pin.board_name,
                status="draft",
                product_name=product.name,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("Vault sync for job %s failed: %s", job.id, e)
